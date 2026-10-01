//! Which tau a chat window runs: `TAU_HOME`, the folder with `tau.toml`, and the Python that
//! has tau-core.
//!
//! The folder, in this order:
//!
//! 1. the `TAU_HOME` environment variable (an app opened from a terminal, or `launchctl setenv`);
//! 2. the folder chosen for the chat windows earlier, or written by the setup wizard
//!    (`chat.json` in the app's config dir);
//! 3. otherwise the window asks. It offers the checkout the app runs the hub from as a hint (the
//!    hub settings' `tau_home`, never used without a click) and a native folder picker.
//!
//! The Python is the folder's own `.venv/bin/python` (a checkout), else the tau-core Python the
//! setup wizard found and saved in `chat.json` (a `uv tool install tau-core` next to `~/.tau`,
//! roadmap 171). It is never a path anyone types into a chat window, so a chat window cannot be
//! turned into a launcher for an arbitrary program. Every choice must pass [`validate`] before
//! it is used: `<python> -m tau_core version` has to run and report tau-core.

use super::launch::{venv_python, Launch};
use serde::{Deserialize, Serialize};
use std::fs;
use std::io::{self, Write};
use std::os::unix::process::CommandExt;
use std::path::{Path, PathBuf};
use std::process::Output;
use std::sync::mpsc;
use std::time::Duration;

/// The chat windows' own settings file, in the app's config directory.
pub const SETTINGS_FILE: &str = "chat.json";
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
    /// Chosen on an earlier run (or by the setup wizard) and saved.
    Saved,
    /// Chosen just now in the folder picker.
    Picked,
    /// The checkout the app runs the hub from, accepted with a click.
    Hub,
}

/// A home that passed [`validate`].
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Validated {
    /// The canonical folder (symlinks resolved).
    pub home: PathBuf,
    /// The Python that runs tau-core for it.
    pub python: PathBuf,
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

/// The Python for `home`: its own `.venv/bin/python` when there is one, else `installed` (the
/// tau-core Python the wizard found), else `None`.
pub fn python_for(home: &Path, installed: Option<&Path>) -> Option<PathBuf> {
    let venv = venv_python(home);
    if venv.is_file() {
        return Some(venv);
    }
    installed
        .filter(|p| !p.as_os_str().is_empty() && p.is_file())
        .map(Path::to_path_buf)
}

/// Check that `folder` is a tau home a chat window can run: a directory with a Python
/// ([`python_for`]) where `python -m tau_core version` succeeds and names tau-core. `installed`
/// is the tau-core Python the wizard saved, for a folder without a venv. `run` executes the
/// check (tests pass a fake; the app passes [`run_with_timeout`]).
pub fn validate(
    folder: &Path,
    installed: Option<&Path>,
    inherited: impl Fn(&str) -> Option<String>,
    run: impl FnOnce(&Launch) -> Result<Output, String>,
) -> Result<Validated, String> {
    if !folder.is_dir() {
        return Err(format!("{} is not a folder.", folder.display()));
    }
    let home = folder
        .canonicalize()
        .map_err(|err| format!("{} cannot be opened: {err}", folder.display()))?;
    let python = python_for(&home, installed).ok_or_else(|| {
        format!(
            "{} has no .venv/bin/python, and tau has not found an installed tau-core yet. Run \
             Set up tau… from the menu, or pick a tau checkout (the folder with tau.toml) after \
             `uv sync --all-packages` in it.",
            home.display()
        )
    })?;
    let check = Launch::version_check(&home, &python, inherited);
    let output = run(&check)?;
    let version = tau_core_version(&output).map_err(|detail| {
        let status = match output.status.code() {
            Some(code) => format!("exit code {code}"),
            None => "killed by a signal".to_string(),
        };
        if detail.is_empty() {
            format!("`{}` failed ({status}).", check.display())
        } else {
            format!("`{}` failed ({status}): {detail}", check.display())
        }
    })?;
    Ok(Validated {
        home,
        python,
        version,
    })
}

/// `tau-core <version>` from the output of `python -m tau_core version`, or the most useful
/// line of what went wrong (the last line of stderr, else the first of stdout).
pub fn tau_core_version(output: &Output) -> Result<String, String> {
    let stdout = String::from_utf8_lossy(&output.stdout);
    let first = stdout.lines().next().unwrap_or("").trim().to_string();
    if output.status.success() && first.starts_with("tau-core ") {
        return Ok(first);
    }
    let stderr = String::from_utf8_lossy(&output.stderr);
    Err(stderr
        .lines()
        .rev()
        .find(|l| !l.trim().is_empty())
        .unwrap_or(first.as_str())
        .trim()
        .to_string())
}

/// A home that passed the check, and where it came from.
pub type Found = (Validated, Source);

/// The home to use without asking: `TAU_HOME` (`env_home`), else the choice saved in
/// `settings_file`, and only if it passes `check`, which gets the folder and the installed
/// tau-core Python saved for folders without a venv. `Err(None)`: nothing is configured yet;
/// `Err(Some(problem))`: something is, but it does not work, and the window says why.
pub fn resolve(
    env_home: Option<String>,
    settings_file: &Path,
    check: impl FnOnce(&Path, Option<&Path>) -> Result<Validated, String>,
) -> Result<Found, Option<String>> {
    let saved = ChatSettings::load(settings_file);
    let (folder, source) = configured(env_home, saved.tau_home).ok_or(None)?;
    match check(&folder, saved.python.as_deref()) {
        Ok(validated) => Ok((validated, source)),
        Err(problem) => Err(Some(match source {
            Source::Env => format!("TAU_HOME is set to a folder tau cannot use. {problem}"),
            _ => format!("The folder chosen earlier no longer works. {problem}"),
        })),
    }
}

/// A folder the person just chose (in the picker, or the hub's checkout with a click): check it,
/// and save it in `settings_file` so the next run finds it (as [`Source::Saved`]). The installed
/// Python the wizard saved stays.
pub fn accept(
    folder: &Path,
    source: Source,
    settings_file: &Path,
    check: impl FnOnce(&Path, Option<&Path>) -> Result<Validated, String>,
) -> Result<Found, String> {
    let saved = ChatSettings::load(settings_file);
    let validated = check(folder, saved.python.as_deref())?;
    let settings = ChatSettings {
        tau_home: Some(validated.home.clone()),
        python: saved.python,
    };
    if let Err(err) = settings.save(settings_file) {
        eprintln!("tau: {} could not be saved: {err}", settings_file.display());
    }
    Ok((validated, source))
}

/// "Use This Folder": the checkout the app runs the hub from, if there is one, through
/// [`accept`].
pub fn accept_hint(
    hint: Option<PathBuf>,
    settings_file: &Path,
    check: impl FnOnce(&Path, Option<&Path>) -> Result<Validated, String>,
) -> Result<Found, String> {
    let folder = hint.ok_or("The hub has no tau checkout set yet.")?;
    accept(&folder, Source::Hub, settings_file, check)
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
        .name("tau-chat-version-check".into())
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

/// The chat windows' own choices, kept as JSON in the app's config directory
/// (`~/Library/Application Support/com.tau.app/chat.json`).
#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(default)]
pub struct ChatSettings {
    /// The folder chosen on the first run, or written by the setup wizard.
    pub tau_home: Option<PathBuf>,
    /// The tau-core Python the setup wizard found, for a folder without `.venv/bin/python`.
    /// Only the wizard's discovery writes it; a chat window never does.
    pub python: Option<PathBuf>,
}

impl ChatSettings {
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
        let dir = std::env::temp_dir().join(format!("tau-chat-{name}-{}", std::process::id()));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).unwrap();
        dir.canonicalize().unwrap()
    }

    fn script(path: &Path, text: &str) {
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        fs::write(path, text).unwrap();
        fs::set_permissions(path, fs::Permissions::from_mode(0o755)).unwrap();
    }

    /// A folder that looks like a checkout: `.venv/bin/python` is a shell script.
    fn checkout(name: &str, python: &str) -> PathBuf {
        let home = tmpdir(name);
        script(&home.join(".venv/bin/python"), python);
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
    fn accepts_a_checkout_whose_python_reports_tau_core() {
        let home = checkout("valid", "#!/bin/sh\n");
        let mut seen = None;
        let validated = validate(&home, None, no_env, |launch| {
            seen = Some(launch.clone());
            Ok(output(0, "tau-core 0.3.1\ntau-tui 0.3.1\n", ""))
        })
        .unwrap();
        assert_eq!(validated.home, home);
        assert_eq!(validated.python, home.join(".venv/bin/python"));
        assert_eq!(validated.version, "tau-core 0.3.1");
        let launch = seen.unwrap();
        assert_eq!(launch.program, home.join(".venv/bin/python"));
        assert_eq!(launch.args, ["-m", "tau_core", "version"]);
        assert_eq!(launch.cwd, home);
        assert_eq!(launch.env["TAU_HOME"], home.display().to_string());
    }

    #[test]
    fn a_folder_without_a_venv_runs_the_installed_python() {
        // `~/.tau` next to a `uv tool install tau-core`: no venv in the folder.
        let root = tmpdir("installed");
        let home = root.join(".tau");
        fs::create_dir_all(&home).unwrap();
        let python = root.join("tools/tau-core/bin/python");
        script(&python, "#!/bin/sh\n");
        let mut seen = None;
        let validated = validate(&home, Some(&python), no_env, |launch| {
            seen = Some(launch.clone());
            Ok(output(0, "tau-core 0.5.0\n", ""))
        })
        .unwrap();
        assert_eq!(validated.python, python);
        assert_eq!(seen.unwrap().program, python);
        // A checkout's own venv wins over the installed Python.
        let venv = home.join(".venv/bin/python");
        script(&venv, "#!/bin/sh\n");
        assert_eq!(python_for(&home, Some(&python)), Some(venv));
        // A saved Python that is gone does not count.
        assert_eq!(
            python_for(&root, Some(&root.join("gone/python"))),
            None,
            "a missing installed Python is no Python"
        );
    }

    #[test]
    fn rejects_a_folder_without_a_venv_or_an_installed_python() {
        let dir = tmpdir("no-venv");
        let err = validate(&dir, None, no_env, |_| panic!("nothing may run")).unwrap_err();
        assert!(err.contains("no .venv/bin/python"), "{err}");
        assert!(err.contains("Set up tau"), "{err}");
        let err = validate(&dir.join("missing"), None, no_env, |_| {
            panic!("nothing may run")
        })
        .unwrap_err();
        assert!(err.contains("is not a folder"), "{err}");
    }

    #[test]
    fn rejects_a_folder_where_tau_core_version_fails() {
        let home = checkout("broken", "#!/bin/sh\n");
        let err = validate(&home, None, no_env, |_| {
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
        let err = validate(&home, None, no_env, |_| {
            Ok(output(0, "Python 3.12.0\n", ""))
        })
        .unwrap_err();
        assert!(err.contains("failed"), "{err}");

        let err = validate(&home, None, no_env, |_| Err("could not start".into())).unwrap_err();
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
        let validated = validate(&good, None, no_env, |launch| {
            run_with_timeout(launch, Duration::from_secs(10))
        })
        .unwrap();
        assert_eq!(validated.version, "tau-core 9.9.9");

        let bad = checkout(
            "runner-bad",
            "#!/bin/sh\necho 'No module named tau_core' >&2\nexit 1\n",
        );
        let err = validate(&bad, None, no_env, |launch| {
            run_with_timeout(launch, Duration::from_secs(10))
        })
        .unwrap_err();
        assert!(err.contains("No module named tau_core"), "{err}");
    }

    #[test]
    fn the_real_runner_gives_up_on_a_hanging_python() {
        let slow = checkout("runner-slow", "#!/bin/sh\nexec sleep 30\n");
        let started = std::time::Instant::now();
        let err = validate(&slow, None, no_env, |launch| {
            run_with_timeout(launch, Duration::from_millis(300))
        })
        .unwrap_err();
        assert!(err.contains("did not finish"), "{err}");
        assert!(started.elapsed() < Duration::from_secs(10));
    }

    /// A stand-in for the version check: `good` passes, anything else fails.
    fn check_only(good: &Path) -> impl Fn(&Path, Option<&Path>) -> Result<Validated, String> + '_ {
        move |folder, _| {
            if folder == good {
                Ok(Validated {
                    home: folder.to_path_buf(),
                    python: venv_python(folder),
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
        ChatSettings {
            tau_home: Some("/saved/tau".into()),
            python: None,
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
            resolve(None, &file, |_: &Path, _: Option<&Path>| panic!(
                "nothing to check"
            )),
            Err(None)
        );
        ChatSettings {
            tau_home: Some("/moved/tau".into()),
            python: None,
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
    fn the_saved_installed_python_reaches_the_check() {
        let dir = tmpdir("resolve-python");
        let file = dir.join("settings.json");
        ChatSettings {
            tau_home: Some("/example/home/.tau".into()),
            python: Some("/example/tools/tau-core/bin/python".into()),
        }
        .save(&file)
        .unwrap();
        let mut seen = None;
        let _ = resolve(None, &file, |folder: &Path, python: Option<&Path>| {
            seen = Some((folder.to_path_buf(), python.map(Path::to_path_buf)));
            Err("checked".to_string())
        });
        assert_eq!(
            seen,
            Some((
                PathBuf::from("/example/home/.tau"),
                Some(PathBuf::from("/example/tools/tau-core/bin/python"))
            ))
        );
        // Picking another folder keeps the installed Python for it.
        let good = PathBuf::from("/path/to/tau");
        accept(&good, Source::Picked, &file, check_only(&good)).unwrap();
        assert_eq!(
            ChatSettings::load(&file).python,
            Some(PathBuf::from("/example/tools/tau-core/bin/python"))
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
        assert_eq!(ChatSettings::load(&file).tau_home, None);
        let (found, source) = accept(&good, Source::Picked, &file, check_only(&good)).unwrap();
        assert_eq!(
            (found.home.as_path(), source),
            (good.as_path(), Source::Picked)
        );
        assert_eq!(ChatSettings::load(&file).tau_home, Some(good.clone()));
        let (found, source) = resolve(None, &file, check_only(&good)).unwrap();
        assert_eq!((found.home, source), (good, Source::Saved));
    }

    #[test]
    fn using_the_hint_needs_one() {
        let dir = tmpdir("accept-hint");
        let file = dir.join("settings.json");
        let good = PathBuf::from("/path/to/tau");
        assert_eq!(
            accept_hint(None, &file, |_: &Path, _: Option<&Path>| panic!(
                "nothing to check"
            ))
            .unwrap_err(),
            "The hub has no tau checkout set yet."
        );
        let (found, source) = accept_hint(Some(good.clone()), &file, check_only(&good)).unwrap();
        assert_eq!((found.home, source), (good, Source::Hub));
    }

    #[test]
    fn a_timeout_stops_what_the_check_started() {
        // A Python that leaves a child behind holding the output pipes, then hangs.
        let home = checkout(
            "runner-grandchild",
            "#!/bin/sh\nsleep 30 &\necho $! > grandchild.pid\nexec sleep 30\n",
        );
        let started = std::time::Instant::now();
        let err = validate(&home, None, no_env, |launch| {
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
        assert_eq!(ChatSettings::load(&file), ChatSettings::default());
        let chosen = ChatSettings {
            tau_home: Some("/path/to/tau".into()),
            python: None,
        };
        chosen.save(&file).unwrap();
        assert_eq!(ChatSettings::load(&file), chosen);
        // A file from before the wizard (no `python`) still loads.
        fs::write(&file, r#"{"tau_home": "/path/to/tau"}"#).unwrap();
        assert_eq!(ChatSettings::load(&file), chosen);
        fs::write(&file, "{not json").unwrap();
        assert_eq!(ChatSettings::load(&file), ChatSettings::default());
    }
}
