//! Which tau checkout tau Desktop runs: `TAU_HOME`, the folder with `tau.toml` and `.venv`.
//!
//! In this order:
//!
//! 1. the `TAU_HOME` environment variable (an app opened from a terminal, or `launchctl setenv`);
//! 2. the folder chosen on an earlier first run (tau Desktop's own `settings.json`);
//! 3. otherwise the window asks. It offers the checkout TauBar runs the hub from as a hint (read
//!    only from TauBar's `settings.json`, never written, never used without a click) and a
//!    native folder picker.
//!
//! Every folder must pass [`validate`] before it is used: `<folder>/.venv/bin/python -m tau_core
//! version` has to run and report tau-core. The Python is always the checkout's own venv, never a
//! path anyone can type, so the app cannot be turned into a launcher for an arbitrary program.

use crate::launch::{venv_python, Launch};
use serde::{Deserialize, Serialize};
use std::fs;
use std::io::{self, Write};
use std::os::unix::process::CommandExt;
use std::path::{Path, PathBuf};
use std::process::Output;
use std::sync::mpsc;
use std::time::Duration;

/// tau Desktop's own settings file, in its app config directory.
pub const SETTINGS_FILE: &str = "settings.json";
/// The environment variable that names the checkout.
pub const TAU_HOME_VAR: &str = "TAU_HOME";
/// How long `python -m tau_core version` may take (a cold venv on a slow disk takes seconds).
pub const VERSION_TIMEOUT: Duration = Duration::from_secs(30);
/// After a timed-out check is killed, how long its output pipes get to close.
pub const KILL_GRACE: Duration = Duration::from_secs(1);

/// Where a home came from.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Source {
    /// The `TAU_HOME` environment variable.
    Env,
    /// Chosen on an earlier run and saved.
    Saved,
    /// Chosen just now in the folder picker.
    Picked,
    /// TauBar's hub checkout, accepted with a click.
    Taubar,
}

/// A checkout that passed [`validate`].
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Validated {
    /// The canonical folder (symlinks resolved).
    pub home: PathBuf,
    /// `tau-core <version>`, the first line `tau version` printed.
    pub version: String,
}

/// The home to try first, without asking: `TAU_HOME`, else the saved choice.
pub fn configured(env_home: Option<String>, saved: Option<PathBuf>) -> Option<(PathBuf, Source)> {
    if let Some(home) = env_home.filter(|h| !h.trim().is_empty()) {
        return Some((PathBuf::from(home), Source::Env));
    }
    saved
        .filter(|p| !p.as_os_str().is_empty())
        .map(|p| (p, Source::Saved))
}

/// TauBar's settings file (`com.tau.taubar` is TauBar's bundle id).
pub fn taubar_settings_path(user_home: &Path) -> PathBuf {
    user_home
        .join("Library")
        .join("Application Support")
        .join("com.tau.taubar")
        .join("settings.json")
}

/// The checkout TauBar runs the hub from (`hub.tau_home`), or `None` when TauBar is not set up.
/// Read only; TauBar's `python` field is deliberately ignored.
pub fn taubar_hint(settings_file: &Path) -> Option<PathBuf> {
    #[derive(Deserialize)]
    struct TaubarSettings {
        hub: Option<TaubarHub>,
    }
    #[derive(Deserialize)]
    struct TaubarHub {
        tau_home: Option<PathBuf>,
    }
    let text = fs::read_to_string(settings_file).ok()?;
    let settings: TaubarSettings = serde_json::from_str(&text).ok()?;
    settings.hub?.tau_home.filter(|p| !p.as_os_str().is_empty())
}

/// Check that `folder` is a tau checkout tau Desktop can run: a directory with
/// `.venv/bin/python`, where `python -m tau_core version` succeeds and names tau-core.
/// `run` executes the check (tests pass a fake; the app passes [`run_with_timeout`]).
pub fn validate(
    folder: &Path,
    inherited: impl Fn(&str) -> Option<String>,
    run: impl FnOnce(&Launch) -> Result<Output, String>,
) -> Result<Validated, String> {
    if !folder.is_dir() {
        return Err(format!("{} is not a folder.", folder.display()));
    }
    let home = folder
        .canonicalize()
        .map_err(|err| format!("{} cannot be opened: {err}", folder.display()))?;
    let python = venv_python(&home);
    if !python.is_file() {
        return Err(format!(
            "{} has no .venv/bin/python. Pick the tau checkout (the folder with tau.toml), \
             or run `uv sync --all-packages` in it first.",
            home.display()
        ));
    }
    let check = Launch::version_check(&home, inherited);
    let output = run(&check)?;
    let stdout = String::from_utf8_lossy(&output.stdout);
    let first = stdout.lines().next().unwrap_or("").trim().to_string();
    if !output.status.success() || !first.starts_with("tau-core ") {
        let stderr = String::from_utf8_lossy(&output.stderr);
        let detail = stderr
            .lines()
            .rev()
            .find(|l| !l.trim().is_empty())
            .unwrap_or(first.as_str())
            .trim();
        let status = match output.status.code() {
            Some(code) => format!("exit code {code}"),
            None => "killed by a signal".to_string(),
        };
        return Err(if detail.is_empty() {
            format!("`{}` failed ({status}).", check.display())
        } else {
            format!("`{}` failed ({status}): {detail}", check.display())
        });
    }
    Ok(Validated {
        home,
        version: first,
    })
}

/// A checkout that passed the check, and where it came from.
pub type Found = (Validated, Source);

/// The home to use without asking: `TAU_HOME` (`env_home`), else the choice saved in
/// `settings_file`, and only if it passes `check`. `Err(None)`: nothing is configured yet;
/// `Err(Some(problem))`: something is, but it does not work, and the window says why.
pub fn resolve(
    env_home: Option<String>,
    settings_file: &Path,
    check: impl FnOnce(&Path) -> Result<Validated, String>,
) -> Result<Found, Option<String>> {
    let saved = DesktopSettings::load(settings_file).tau_home;
    let (folder, source) = configured(env_home, saved).ok_or(None)?;
    match check(&folder) {
        Ok(validated) => Ok((validated, source)),
        Err(problem) => Err(Some(match source {
            Source::Env => format!("TAU_HOME is set to a folder tau Desktop cannot use. {problem}"),
            _ => format!("The folder chosen earlier no longer works. {problem}"),
        })),
    }
}

/// A folder the person just chose (in the picker, or TauBar's hint with a click): check it, and
/// save it in `settings_file` so the next run finds it (as [`Source::Saved`]).
pub fn accept(
    folder: &Path,
    source: Source,
    settings_file: &Path,
    check: impl FnOnce(&Path) -> Result<Validated, String>,
) -> Result<Found, String> {
    let validated = check(folder)?;
    let settings = DesktopSettings {
        tau_home: Some(validated.home.clone()),
    };
    if let Err(err) = settings.save(settings_file) {
        eprintln!(
            "tau-desktop: {} could not be saved: {err}",
            settings_file.display()
        );
    }
    Ok((validated, source))
}

/// "Use This Folder": TauBar's hub checkout, if TauBar has one, through [`accept`].
pub fn accept_hint(
    hint: Option<PathBuf>,
    settings_file: &Path,
    check: impl FnOnce(&Path) -> Result<Validated, String>,
) -> Result<Found, String> {
    let folder = hint.ok_or("TauBar has no hub checkout set.")?;
    accept(&folder, Source::Taubar, settings_file, check)
}

/// Run `launch` to completion, killing it after `timeout`.
///
/// The check runs in its own process group, so a timeout kills whatever it started as well.
/// After the kill, the output pipes get [`KILL_GRACE`] to close; something that left the group
/// and still holds them is not waited for.
pub fn run_with_timeout(launch: &Launch, timeout: Duration) -> Result<Output, String> {
    let mut command = launch.command();
    command.process_group(0);
    let child = command
        .spawn()
        .map_err(|err| format!("`{}` could not start: {err}", launch.display()))?;
    let pid = child.id();
    let (tx, rx) = mpsc::channel();
    std::thread::Builder::new()
        .name("tau-desktop-version-check".into())
        .spawn(move || {
            let _ = tx.send(child.wait_with_output());
        })
        .map_err(|err| format!("the check could not run: {err}"))?;
    let result = match rx.recv_timeout(timeout) {
        Ok(result) => result,
        Err(_) => {
            // SAFETY: killpg(2) on the group of our own child. The waiting thread reaps the
            // child only after both pipes have closed, so its pid (the group id) is still ours.
            unsafe {
                libc::killpg(pid as libc::pid_t, libc::SIGKILL);
            }
            let _ = rx.recv_timeout(KILL_GRACE);
            return Err(format!(
                "`{}` did not finish within {} s.",
                launch.display(),
                timeout.as_secs()
            ));
        }
    };
    result.map_err(|err| format!("`{}` failed: {err}", launch.display()))
}

/// tau Desktop's own choices, kept as JSON in its app config directory
/// (`~/Library/Application Support/com.tau.desktop/settings.json`).
#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(default)]
pub struct DesktopSettings {
    /// The checkout chosen on the first run.
    pub tau_home: Option<PathBuf>,
}

impl DesktopSettings {
    /// The stored settings, or the defaults when the file is missing or unreadable.
    pub fn load(file: &Path) -> Self {
        fs::read_to_string(file)
            .ok()
            .and_then(|text| serde_json::from_str(&text).ok())
            .unwrap_or_default()
    }

    /// Write atomically (temp file + rename).
    pub fn save(&self, file: &Path) -> io::Result<()> {
        if let Some(parent) = file.parent() {
            fs::create_dir_all(parent)?;
        }
        let mut tmp = file.as_os_str().to_owned();
        tmp.push(".tmp");
        let tmp = PathBuf::from(tmp);
        {
            let mut out = fs::File::create(&tmp)?;
            let text = serde_json::to_string_pretty(self).map_err(io::Error::other)?;
            out.write_all(text.as_bytes())?;
            out.write_all(b"\n")?;
            out.sync_all()?;
        }
        fs::rename(&tmp, file)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::os::unix::fs::PermissionsExt;
    use std::os::unix::process::ExitStatusExt;
    use std::process::ExitStatus;

    fn tmpdir(name: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!("tau-desktop-{name}-{}", std::process::id()));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).unwrap();
        dir.canonicalize().unwrap()
    }

    /// A folder that looks like a checkout: `.venv/bin/python` is a shell script.
    fn checkout(name: &str, python: &str) -> PathBuf {
        let home = tmpdir(name);
        let bin = home.join(".venv/bin");
        fs::create_dir_all(&bin).unwrap();
        let script = bin.join("python");
        fs::write(&script, python).unwrap();
        fs::set_permissions(&script, fs::Permissions::from_mode(0o755)).unwrap();
        home
    }

    fn no_env(_: &str) -> Option<String> {
        None
    }

    fn output(code: i32, stdout: &str, stderr: &str) -> Output {
        Output {
            status: ExitStatus::from_raw(code << 8),
            stdout: stdout.as_bytes().to_vec(),
            stderr: stderr.as_bytes().to_vec(),
        }
    }

    #[test]
    fn the_env_var_wins_over_the_saved_choice() {
        assert_eq!(
            configured(Some("/path/to/tau".into()), Some("/other/tau".into())),
            Some((PathBuf::from("/path/to/tau"), Source::Env))
        );
        assert_eq!(
            configured(Some("  ".into()), Some("/other/tau".into())),
            Some((PathBuf::from("/other/tau"), Source::Saved))
        );
        assert_eq!(configured(None, Some(PathBuf::new())), None);
        assert_eq!(configured(None, None), None);
    }

    #[test]
    fn reads_taubars_hub_checkout_as_a_hint_only() {
        let dir = tmpdir("taubar-hint");
        let file = taubar_settings_path(&dir);
        assert_eq!(taubar_hint(&file), None); // TauBar not installed
        fs::create_dir_all(file.parent().unwrap()).unwrap();
        fs::write(
            &file,
            r#"{"sleep_mode": "normal", "run_hub": true,
                "hub": {"python": "/somewhere/else/python", "tau_home": "/path/to/tau",
                        "env": {"TELEGRAM_BOT_TOKEN": ""}}}"#,
        )
        .unwrap();
        let before = fs::read(&file).unwrap();
        assert_eq!(taubar_hint(&file), Some(PathBuf::from("/path/to/tau")));
        assert_eq!(
            fs::read(&file).unwrap(),
            before,
            "TauBar's file is never written"
        );
        fs::write(&file, r#"{"hub": {"tau_home": null}}"#).unwrap();
        assert_eq!(taubar_hint(&file), None);
        fs::write(&file, r#"{"sleep_mode": "normal"}"#).unwrap();
        assert_eq!(taubar_hint(&file), None);
        fs::write(&file, "{not json").unwrap();
        assert_eq!(taubar_hint(&file), None);
        assert!(file.ends_with("Library/Application Support/com.tau.taubar/settings.json"));
    }

    #[test]
    fn accepts_a_checkout_whose_python_reports_tau_core() {
        let home = checkout("valid", "#!/bin/sh\n");
        let mut seen = None;
        let validated = validate(&home, no_env, |launch| {
            seen = Some(launch.clone());
            Ok(output(0, "tau-core 0.3.1\ntau-tui 0.3.1\n", ""))
        })
        .unwrap();
        assert_eq!(validated.home, home);
        assert_eq!(validated.version, "tau-core 0.3.1");
        let launch = seen.unwrap();
        assert_eq!(launch.program, home.join(".venv/bin/python"));
        assert_eq!(launch.args, ["-m", "tau_core", "version"]);
        assert_eq!(launch.cwd, home);
        assert_eq!(launch.env["TAU_HOME"], home.display().to_string());
    }

    #[test]
    fn rejects_a_folder_without_a_venv() {
        let dir = tmpdir("no-venv");
        let err = validate(&dir, no_env, |_| panic!("nothing may run")).unwrap_err();
        assert!(err.contains("no .venv/bin/python"), "{err}");
        let err =
            validate(&dir.join("missing"), no_env, |_| panic!("nothing may run")).unwrap_err();
        assert!(err.contains("is not a folder"), "{err}");
    }

    #[test]
    fn rejects_a_folder_where_tau_core_version_fails() {
        let home = checkout("broken", "#!/bin/sh\n");
        let err = validate(&home, no_env, |_| {
            Ok(output(
                1,
                "",
                "Traceback (most recent call last):\nModuleNotFoundError: No module named 'tau_core'\n",
            ))
        })
        .unwrap_err();
        assert!(err.contains("-m tau_core version"), "{err}");
        assert!(err.contains("exit code 1"), "{err}");
        assert!(err.contains("No module named 'tau_core'"), "{err}");

        // Exit 0 but not tau: some other Python answering.
        let err = validate(&home, no_env, |_| Ok(output(0, "Python 3.12.0\n", ""))).unwrap_err();
        assert!(err.contains("failed"), "{err}");

        let err = validate(&home, no_env, |_| Err("could not start".into())).unwrap_err();
        assert_eq!(err, "could not start");
    }

    #[test]
    fn the_real_runner_executes_the_checkout_python() {
        let good = checkout(
            "runner-good",
            "#!/bin/sh\n[ \"$1 $2 $3\" = \"-m tau_core version\" ] || exit 9\n\
             [ \"$TERM\" = xterm-256color ] || exit 8\n\
             [ \"$PWD\" = \"$TAU_HOME\" ] || exit 7\n\
             echo 'tau-core 9.9.9'\necho 'tau-tui 9.9.9'\n",
        );
        let validated = validate(&good, no_env, |launch| {
            run_with_timeout(launch, Duration::from_secs(10))
        })
        .unwrap();
        assert_eq!(validated.version, "tau-core 9.9.9");

        let bad = checkout(
            "runner-bad",
            "#!/bin/sh\necho 'No module named tau_core' >&2\nexit 1\n",
        );
        let err = validate(&bad, no_env, |launch| {
            run_with_timeout(launch, Duration::from_secs(10))
        })
        .unwrap_err();
        assert!(err.contains("No module named tau_core"), "{err}");
    }

    #[test]
    fn the_real_runner_gives_up_on_a_hanging_python() {
        let slow = checkout("runner-slow", "#!/bin/sh\nexec sleep 30\n");
        let started = std::time::Instant::now();
        let err = validate(&slow, no_env, |launch| {
            run_with_timeout(launch, Duration::from_millis(300))
        })
        .unwrap_err();
        assert!(err.contains("did not finish"), "{err}");
        assert!(started.elapsed() < Duration::from_secs(10));
    }

    /// A stand-in for the version check: `good` passes, anything else fails.
    fn check_only(good: &Path) -> impl Fn(&Path) -> Result<Validated, String> + '_ {
        move |folder| {
            if folder == good {
                Ok(Validated {
                    home: folder.to_path_buf(),
                    version: "tau-core 0.3.1".into(),
                })
            } else {
                Err(format!("{} has no .venv/bin/python.", folder.display()))
            }
        }
    }

    #[test]
    fn a_broken_tau_home_asks_and_says_tau_home() {
        let dir = tmpdir("resolve-env");
        let file = dir.join("settings.json");
        let good = PathBuf::from("/path/to/tau");
        let err = resolve(Some("/broken/tau".into()), &file, check_only(&good)).unwrap_err();
        let problem = err.expect("a problem, not an empty first run");
        assert!(
            problem.starts_with("TAU_HOME is set to a folder"),
            "{problem}"
        );
        assert!(problem.contains("/broken/tau has no .venv"), "{problem}");
        // A working TAU_HOME wins over the saved choice.
        DesktopSettings {
            tau_home: Some("/saved/tau".into()),
        }
        .save(&file)
        .unwrap();
        let (found, source) =
            resolve(Some("/path/to/tau".into()), &file, check_only(&good)).unwrap();
        assert_eq!((found.home, source), (good, Source::Env));
    }

    #[test]
    fn a_saved_choice_that_broke_asks_again() {
        let dir = tmpdir("resolve-saved");
        let file = dir.join("settings.json");
        let good = PathBuf::from("/path/to/tau");
        // Nothing configured: ask, with no problem, and check nothing.
        assert_eq!(
            resolve(None, &file, |_| panic!("nothing to check")),
            Err(None)
        );
        DesktopSettings {
            tau_home: Some("/moved/tau".into()),
        }
        .save(&file)
        .unwrap();
        let problem = resolve(None, &file, check_only(&good))
            .unwrap_err()
            .unwrap();
        assert!(
            problem.starts_with("The folder chosen earlier no longer works."),
            "{problem}"
        );
    }

    #[test]
    fn an_accepted_folder_comes_back_as_saved() {
        let dir = tmpdir("accept");
        let file = dir.join("settings.json");
        let good = PathBuf::from("/path/to/tau");
        // A rejected folder is not saved.
        let err = accept(
            Path::new("/other"),
            Source::Picked,
            &file,
            check_only(&good),
        )
        .unwrap_err();
        assert!(err.contains("/other has no .venv"), "{err}");
        assert_eq!(DesktopSettings::load(&file).tau_home, None);
        let (found, source) = accept(&good, Source::Picked, &file, check_only(&good)).unwrap();
        assert_eq!(
            (found.home.as_path(), source),
            (good.as_path(), Source::Picked)
        );
        assert_eq!(DesktopSettings::load(&file).tau_home, Some(good.clone()));
        let (found, source) = resolve(None, &file, check_only(&good)).unwrap();
        assert_eq!((found.home, source), (good, Source::Saved));
    }

    #[test]
    fn using_the_hint_needs_one() {
        let dir = tmpdir("accept-hint");
        let file = dir.join("settings.json");
        let good = PathBuf::from("/path/to/tau");
        assert_eq!(
            accept_hint(None, &file, |_| panic!("nothing to check")).unwrap_err(),
            "TauBar has no hub checkout set."
        );
        let (found, source) = accept_hint(Some(good.clone()), &file, check_only(&good)).unwrap();
        assert_eq!((found.home, source), (good, Source::Taubar));
    }

    #[test]
    fn a_timeout_stops_what_the_check_started() {
        // A Python that leaves a child behind holding the output pipes, then hangs.
        let home = checkout(
            "runner-grandchild",
            "#!/bin/sh\nsleep 30 &\necho $! > grandchild.pid\nexec sleep 30\n",
        );
        let started = std::time::Instant::now();
        let err = validate(&home, no_env, |launch| {
            run_with_timeout(launch, Duration::from_millis(500))
        })
        .unwrap_err();
        assert!(err.contains("did not finish"), "{err}");
        assert!(
            started.elapsed() < Duration::from_secs(5),
            "waited for the pipes: {:?}",
            started.elapsed()
        );
        let grandchild: libc::pid_t = fs::read_to_string(home.join("grandchild.pid"))
            .unwrap()
            .trim()
            .parse()
            .unwrap();
        let deadline = std::time::Instant::now() + Duration::from_secs(5);
        while unsafe { libc::kill(grandchild, 0) } == 0 {
            assert!(
                std::time::Instant::now() < deadline,
                "the check's child {grandchild} survived"
            );
            std::thread::sleep(Duration::from_millis(20));
        }
    }

    #[test]
    fn remembers_the_first_run_choice() {
        let dir = tmpdir("settings");
        let file = dir.join("settings.json");
        assert_eq!(DesktopSettings::load(&file), DesktopSettings::default());
        let chosen = DesktopSettings {
            tau_home: Some("/path/to/tau".into()),
        };
        chosen.save(&file).unwrap();
        assert_eq!(DesktopSettings::load(&file), chosen);
        fs::write(&file, "{not json").unwrap();
        assert_eq!(DesktopSettings::load(&file), DesktopSettings::default());
    }
}
