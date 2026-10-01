//! The commands the wizard's page may call (only the `wizard` window, `capabilities/wizard.json`),
//! and `open_wizard` for the other windows.
//!
//! None takes a program, a Python or an environment: the page names a job (`jobs::Spec`), a
//! permission or the words of a tau subcommand for its terminal, and Rust runs it with the tau
//! that discovery found. Keys and tokens arrive in a job's `input`, go to the child's stdin and
//! nowhere else: not argv, not the environment, not the app's log.

use super::discover::{self, Found, Kind, Places, Rejected};
use super::jobs::{self, Context, Lang, Spec};
use super::runner::{self, Ended, Job};
use super::{Wizard, WINDOW};
use crate::chat::home::{self, ChatSettings};
use crate::chat::launch::{Launch, DEFAULT_PATH};
use crate::chat::pty::{pty_size, ExitInfo, Session};
use crate::chat::{inherited_env, Chats};
use crate::permissions::{self, Access, Permission};
use crate::settings::HubSettings;
use crate::AppCore;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::path::{Path, PathBuf};
use std::sync::atomic::AtomicBool;
use tauri::ipc::{Channel, InvokeResponseBody};
use tauri::{AppHandle, Manager, State, WebviewWindow};
use tauri_plugin_opener::OpenerExt;

async fn blocking<T: Send + 'static>(f: impl FnOnce() -> T + Send + 'static) -> Result<T, String> {
    tauri::async_runtime::spawn_blocking(f)
        .await
        .map_err(|err| format!("internal error: {err}"))
}

/// Every name in the app's environment (for the `UV_*` and `XDG_*` passthrough).
fn env_names() -> Vec<String> {
    std::env::vars_os()
        .filter_map(|(name, _)| name.into_string().ok())
        .collect()
}

/// What a job needs from the app: the user's home, the environment names and the hub settings.
struct Inputs {
    user_home: PathBuf,
    names: Vec<String>,
    hub: HubSettings,
    uv: Option<PathBuf>,
}

impl Inputs {
    fn gather(app: &AppHandle) -> Result<Self, String> {
        Ok(Self {
            user_home: app.path().home_dir().map_err(|err| err.to_string())?,
            names: env_names(),
            hub: app.state::<AppCore>().settings().hub,
            uv: app.state::<Wizard>().uv(),
        })
    }

    fn context(&self) -> Context<'_> {
        Context {
            user_home: &self.user_home,
            inherited: &inherited_env,
            names: &self.names,
            data_dir: self.hub.data_dir.as_deref(),
            hub_path: self.hub.path.as_deref(),
            uv: self.uv.as_deref(),
        }
    }

    fn hub_path(&self) -> String {
        self.hub
            .path
            .clone()
            .filter(|p| !p.is_empty())
            .unwrap_or_else(|| DEFAULT_PATH.to_string())
    }
}

fn launch_of(job: &Job) -> Launch {
    Launch {
        program: job.program.clone(),
        args: job.args.clone(),
        cwd: job.cwd.clone(),
        env: job.env.clone(),
    }
}

/// `tau setup run guard --json`, for the app's log: the words after `-m tau_core`, never input.
fn describe(job: &Job) -> String {
    match job.args.iter().position(|a| a == "tau_core") {
        Some(at) => format!("tau {}", job.args[at + 1..].join(" ")),
        None => job.display(),
    }
}

// -- discovery -------------------------------------------------------------------------------

/// What the wizard knows about tau on this Mac.
#[derive(Clone, Debug, Serialize)]
pub struct Discovery {
    pub tau: Option<Found>,
    pub uv: Option<PathBuf>,
    pub rejected: Vec<Rejected>,
    /// Discovery wrote the hub settings (`hub.python`, `hub.tau_home`).
    pub saved_hub: bool,
    /// Discovery wrote the chat windows' folder (and Python) into `chat.json`.
    pub saved_chat: bool,
    /// `TAU_HOME` for an installed tau (`~/.tau`, or the app's `TAU_HOME`).
    pub default_home: PathBuf,
    /// `TAU_INSTALL_VERSION`, when set to a version.
    pub install_version: Option<String>,
    /// The hub settings name a Python and a `TAU_HOME`: "Start the hub" can work.
    pub hub_ready: bool,
}

/// Find tau, remember it for the wizard's jobs and write it into the settings that lack it.
#[tauri::command]
pub async fn wizard_discover(app: AppHandle) -> Result<Discovery, String> {
    blocking(move || discover_now(&app)).await?
}

fn discover_now(app: &AppHandle) -> Result<Discovery, String> {
    let mut inputs = Inputs::gather(app)?;
    let chats = app.state::<Chats>();
    let chat_saved = ChatSettings::load(chats.settings_file());
    let path = inputs.hub_path();
    let places = Places {
        user_home: &inputs.user_home,
        var: &inherited_env,
        path: &path,
    };
    let uv = places.find_uv();
    inputs.uv = uv.clone();
    let default_home = places.install_home(&inputs.hub);
    let cx = inputs.context();
    let uv_tool_dir = uv.as_deref().and_then(|uv| uv_tool_dir(&cx, uv));
    let candidates = places.candidates(&inputs.hub, chat_saved.tau_home.as_deref(), uv_tool_dir);
    let (found, rejected) =
        discover::first_working(candidates, |candidate| version_of(&cx, candidate));
    let (saved_hub, saved_chat) = match &found {
        Some(found) => save(app, found),
        None => (false, false),
    };
    match &found {
        Some(found) => crate::log(
            app,
            format!(
                "setup wizard: found {} ({:?}) at {}, TAU_HOME {}",
                found.version,
                found.kind,
                found.python.display(),
                found.home.display()
            ),
        ),
        None => crate::log(app, "setup wizard: no tau found"),
    }
    app.state::<Wizard>().set_found(found.clone(), uv.clone());
    let hub = app.state::<AppCore>().settings().hub;
    Ok(Discovery {
        hub_ready: hub.python.as_ref().is_some_and(|p| p.is_file())
            && hub.tau_home.as_ref().is_some_and(|h| h.is_dir()),
        tau: found,
        uv,
        rejected,
        saved_hub,
        saved_chat,
        default_home,
        install_version: jobs::install_version(inherited_env("TAU_INSTALL_VERSION")),
    })
}

/// What `uv tool dir` prints: where uv keeps its tool environments.
fn uv_tool_dir(cx: &Context, uv: &Path) -> Option<PathBuf> {
    let job = cx.uv_tool_dir(uv);
    let output = home::run_with_timeout(&launch_of(&job), job.timeout).ok()?;
    if !output.status.success() {
        return None;
    }
    let text = String::from_utf8_lossy(&output.stdout);
    let line = text.lines().rev().find(|l| !l.trim().is_empty())?.trim();
    line.starts_with('/').then(|| PathBuf::from(line))
}

/// `python -m tau_core version` for a candidate: `tau-core <version>`, or what went wrong.
fn version_of(cx: &Context, candidate: &discover::Candidate) -> Result<String, String> {
    let found = Found {
        python: candidate.python.clone(),
        home: candidate.home.clone(),
        kind: candidate.kind,
        via: candidate.via.clone(),
        version: String::new(),
        uv_tool: false,
    };
    let job = cx.tau(
        &found,
        Lang::En,
        vec!["version".into()],
        None,
        home::VERSION_TIMEOUT,
    );
    // `tau --lang en version` works on every tau-core; the plain form is what chat checks.
    let mut launch = launch_of(&job);
    launch.args = vec!["-m".into(), "tau_core".into(), "version".into()];
    let output = home::run_with_timeout(&launch, home::VERSION_TIMEOUT)?;
    home::tau_core_version(&output)
}

/// Write what discovery found where it is missing: the hub settings without a working Python
/// and `TAU_HOME`, and the chat windows' folder and Python. Settings that work are kept.
/// Returns what was written (hub, chat).
fn save(app: &AppHandle, found: &Found) -> (bool, bool) {
    // An installed tau's home (`~/.tau`) may not exist before `tau init`: create it, so the
    // hub and the jobs can run in it.
    if matches!(found.kind, Kind::UvTool | Kind::Command) {
        if let Err(err) = std::fs::create_dir_all(&found.home) {
            crate::log(
                app,
                format!(
                    "setup wizard: {} could not be created: {err}",
                    found.home.display()
                ),
            );
        }
    }
    let core = app.state::<AppCore>();
    let mut hub = core.settings().hub;
    let hub_works = hub.python.as_ref().is_some_and(|p| p.is_file())
        && hub
            .tau_home
            .as_ref()
            .is_some_and(|h| !h.as_os_str().is_empty());
    let mut saved_hub = false;
    if !hub_works {
        hub.python = Some(found.python.clone());
        hub.tau_home = Some(found.home.clone());
        if let Err(err) = core.save_hub_settings(hub) {
            crate::log(app, format!("setup wizard: the hub settings: {err}"));
        }
        crate::log(
            app,
            "setup wizard: wrote the hub settings (python, tau_home)",
        );
        crate::refresh(app);
        saved_hub = true;
    }

    let chats = app.state::<Chats>();
    let saved = ChatSettings::load(chats.settings_file());
    let mut next = saved.clone();
    let env_home = std::env::var(home::TAU_HOME_VAR)
        .ok()
        .filter(|h| !h.trim().is_empty())
        .map(PathBuf::from);
    if env_home.is_none() && !next.tau_home.as_ref().is_some_and(|h| h.is_dir()) {
        next.tau_home = Some(found.home.clone());
    }
    if let Some(folder) = env_home.or_else(|| next.tau_home.clone()) {
        if home::python_for(&folder, next.python.as_deref()).is_none() {
            next.python = Some(found.python.clone());
        }
    }
    let mut saved_chat = false;
    if next != saved {
        match next.save(chats.settings_file()) {
            Ok(()) => {
                chats.forget_home();
                saved_chat = true;
                crate::log(app, "setup wizard: wrote the chat windows' folder");
            }
            Err(err) => crate::log(
                app,
                format!(
                    "setup wizard: {} could not be saved: {err}",
                    chats.settings_file().display()
                ),
            ),
        }
    }
    (saved_hub, saved_chat)
}

// -- status ------------------------------------------------------------------------------------

/// Why `tau setup status --json` gave no status.
#[derive(Clone, Debug, Serialize)]
pub struct StatusProblem {
    /// `no_tau` (nothing found yet), `too_old` (a tau-core without `tau setup`), `failed`.
    pub code: &'static str,
    pub message: String,
}

/// `tau setup status --json`: the catalog, the platform, what is installed and set up.
#[tauri::command]
pub async fn wizard_status(app: AppHandle, lang: Lang) -> Result<Value, StatusProblem> {
    blocking(move || status_now(&app, lang))
        .await
        .map_err(|message| StatusProblem {
            code: "failed",
            message,
        })?
}

fn status_now(app: &AppHandle, lang: Lang) -> Result<Value, StatusProblem> {
    let tau = app.state::<Wizard>().tau().ok_or(StatusProblem {
        code: "no_tau",
        message: "tau is not installed yet.".into(),
    })?;
    let inputs = Inputs::gather(app).map_err(|message| StatusProblem {
        code: "failed",
        message,
    })?;
    let job = inputs.context().tau(
        &tau,
        lang,
        vec!["setup".into(), "status".into(), "--json".into()],
        None,
        jobs::STATUS_TIMEOUT,
    );
    let output =
        home::run_with_timeout(&launch_of(&job), job.timeout).map_err(|message| StatusProblem {
            code: "failed",
            message,
        })?;
    parse_status(&output.stdout, &output.stderr, output.status.success())
}

/// The status object, or why there is none: a tau-core without `tau setup` says "No such
/// command 'setup'" (exit 2).
pub fn parse_status(stdout: &[u8], stderr: &[u8], success: bool) -> Result<Value, StatusProblem> {
    let errors = String::from_utf8_lossy(stderr);
    if !success {
        if errors.contains("No such command 'setup'") {
            return Err(StatusProblem {
                code: "too_old",
                message: "This tau-core has no `tau setup` yet.".into(),
            });
        }
        let last = errors
            .lines()
            .rev()
            .find(|l| !l.trim().is_empty())
            .unwrap_or("no output")
            .trim();
        return Err(StatusProblem {
            code: "failed",
            message: format!("`tau setup status --json` failed: {last}"),
        });
    }
    match serde_json::from_slice::<Value>(stdout) {
        Ok(value) if value.get("protocol").is_some() && value["features"].is_array() => Ok(value),
        _ => Err(StatusProblem {
            code: "failed",
            message: "`tau setup status --json` printed something that is not its status object."
                .into(),
        }),
    }
}

// -- jobs --------------------------------------------------------------------------------------

/// Run one `tau` job: its events go to `events`, the end comes back. One job at a time.
#[tauri::command]
pub async fn wizard_run(
    app: AppHandle,
    spec: Spec,
    input: Option<Value>,
    lang: Lang,
    events: Channel<Value>,
) -> Result<Ended, String> {
    blocking(move || {
        let tau = app
            .state::<Wizard>()
            .tau()
            .ok_or("tau is not installed yet.")?;
        let words = spec.words()?;
        let stdin = jobs::stdin_line(input.as_ref())?;
        let inputs = Inputs::gather(&app)?;
        let job = inputs
            .context()
            .tau(&tau, lang, words, stdin, spec.timeout());
        let ended = with_job(&app, |cancel| run_logged(&app, &job, cancel, &events))?;
        Ok(send_ended(&events, ended))
    })
    .await?
}

/// The last event on a job's channel: how it ended. The page settles on it, so it never acts
/// before the events that came first (a command's answer and its channel take separate paths).
fn send_ended(events: &Channel<Value>, ended: Ended) -> Ended {
    let mut event = serde_json::to_value(&ended).unwrap_or_else(|_| json!({}));
    event["event"] = json!("ended");
    let _ = events.send(event);
    ended
}

/// What the "Install tau" step installs.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Install {
    /// uv, with Astral's installer (downloaded first, never piped into a shell).
    Uv,
    /// `uv tool install tau-core --with tau-tui`.
    Tau,
    /// `uv tool upgrade tau-core`.
    Upgrade,
}

/// Install uv or tau, or upgrade tau, streaming the output. The page runs discovery after it.
#[tauri::command]
pub async fn wizard_install(
    app: AppHandle,
    what: Install,
    events: Channel<Value>,
) -> Result<Ended, String> {
    blocking(move || {
        let mut inputs = Inputs::gather(&app)?;
        let path = inputs.hub_path();
        let found_uv = Places {
            user_home: &inputs.user_home,
            var: &inherited_env,
            path: &path,
        }
        .find_uv();
        inputs.uv = found_uv.clone();
        let cx = inputs.context();
        let ended = with_job(&app, |cancel| match what {
            Install::Uv => install_uv(&app, &cx, found_uv.as_deref(), cancel, &events),
            Install::Tau | Install::Upgrade => {
                let uv = found_uv
                    .as_deref()
                    .ok_or("uv is not installed yet: install it first.")?;
                let job = if what == Install::Tau {
                    let version = jobs::install_version(inherited_env("TAU_INSTALL_VERSION"));
                    cx.install_tau(uv, version.as_deref())
                } else {
                    cx.upgrade_tau(uv)
                };
                let _ =
                    events.send(json!({"event": "progress", "phase": "install", "argv": job.args}));
                run_logged(&app, &job, cancel, &events)
            }
        })?;
        Ok(send_ended(&events, ended))
    })
    .await?
}

/// Astral's installer: download it into a private folder, run it with `/bin/sh`, delete it.
fn install_uv(
    app: &AppHandle,
    cx: &Context,
    found: Option<&Path>,
    cancel: &AtomicBool,
    events: &Channel<Value>,
) -> Result<Ended, String> {
    if let Some(uv) = found {
        let _ = events.send(json!({"event": "progress", "phase": "found", "uv": uv}));
        return Ok(Ended {
            code: Some(0),
            ..Ended::default()
        });
    }
    let dir = private_dir()?;
    let file = dir.join("uv-installer.sh");
    let _ = events.send(json!({
        "event": "progress", "phase": "download", "url": jobs::UV_INSTALLER_URL
    }));
    let result = (|| {
        let ended = run_logged(app, &cx.download_uv_installer(&file), cancel, events)?;
        if !ended.success() {
            return Ok(ended);
        }
        let _ = events.send(json!({"event": "progress", "phase": "install_uv"}));
        run_logged(app, &cx.run_uv_installer(&file), cancel, events)
    })();
    let _ = std::fs::remove_dir_all(&dir);
    result
}

/// A new folder only this user can read, for the downloaded installer.
fn private_dir() -> Result<PathBuf, String> {
    use std::os::unix::fs::DirBuilderExt;
    let mut random = [0u8; 8];
    getrandom::fill(&mut random).map_err(|err| err.to_string())?;
    let dir = std::env::temp_dir().join(format!("tau-app-uv-{}", hex::encode(random)));
    std::fs::DirBuilder::new()
        .mode(0o700)
        .create(&dir)
        .map_err(|err| format!("{} could not be created: {err}", dir.display()))?;
    Ok(dir)
}

/// Claim the job slot for `f` (one job at a time); `Err` while another runs.
fn with_job(
    app: &AppHandle,
    f: impl FnOnce(&AtomicBool) -> Result<Ended, String>,
) -> Result<Ended, String> {
    let wizard = app.state::<Wizard>();
    let slot = wizard.begin_job()?;
    f(&slot.cancel)
}

/// Run `job`, its events to `events`, its start and end to the app's log (never its input).
fn run_logged(
    app: &AppHandle,
    job: &Job,
    cancel: &AtomicBool,
    events: &Channel<Value>,
) -> Result<Ended, String> {
    let what = describe(job);
    crate::log(app, format!("setup wizard: {what}"));
    let ended = runner::run(job, cancel, |event| {
        let _ = events.send(event);
    });
    match &ended {
        Ok(end) => {
            let how = match (end.code, end.signal) {
                (Some(code), _) => format!("exit code {code}"),
                (None, Some(signal)) => format!("signal {signal}"),
                _ => "an unknown end".into(),
            };
            let why = if end.cancelled {
                ", cancelled"
            } else if end.timed_out {
                ", timed out"
            } else {
                ""
            };
            crate::log(app, format!("setup wizard: {what} ended ({how}{why})"));
        }
        Err(err) => crate::log(app, format!("setup wizard: {err}")),
    }
    ended
}

/// Stop the running job (SIGINT, then SIGKILL after a grace period).
#[tauri::command]
pub fn wizard_cancel(wizard: State<'_, Wizard>) {
    wizard.cancel();
}

// -- the terminal ------------------------------------------------------------------------------

/// Run `tau <command>` in the wizard's own terminal (a step that needs one, such as
/// `tau guard setup`): a PTY like a chat window's, as the app's child, so macOS attributes its
/// camera use to the app. Output arrives as raw bytes on `output`, the end on `exit`.
#[allow(clippy::too_many_arguments)]
#[tauri::command]
pub fn wizard_pty_start(
    app: AppHandle,
    window: WebviewWindow,
    command: Vec<String>,
    lang: Lang,
    cols: u16,
    rows: u16,
    output: Channel<InvokeResponseBody>,
    exit: Channel<ExitInfo>,
) -> Result<(), String> {
    if window.label() != WINDOW {
        return Err("Only the setup wizard has a terminal.".into());
    }
    let tau = app
        .state::<Wizard>()
        .tau()
        .ok_or("tau is not installed yet.")?;
    let words = jobs::terminal_words(&command)?;
    let what = format!("tau {}", words.join(" "));
    let inputs = Inputs::gather(&app)?;
    let launch = inputs.context().terminal(&tau, lang, words);
    let log_app = app.clone();
    let log_what = what.clone();
    app.state::<Chats>().start_session(WINDOW, || {
        Session::spawn(
            &launch,
            pty_size(cols, rows),
            move |batch| {
                let _ = output.send(InvokeResponseBody::Raw(batch));
            },
            move |info: ExitInfo| {
                crate::log(
                    &log_app,
                    format!(
                        "setup wizard: terminal `{log_what}` ended (success: {})",
                        info.success
                    ),
                );
                let _ = exit.send(info);
            },
        )
    })?;
    crate::log(&app, format!("setup wizard: terminal runs `{what}`"));
    Ok(())
}

// -- permissions -------------------------------------------------------------------------------

/// Where `permission` stands (`request: false`), or ask macOS for it (`request: true`): its
/// prompt appears while the answer is not determined.
#[tauri::command]
pub async fn wizard_permission(
    app: AppHandle,
    permission: Permission,
    request: bool,
) -> Result<Access, String> {
    blocking(move || {
        let access = if request {
            permissions::request(permission)
        } else {
            permissions::status(permission)
        };
        if request {
            crate::log(
                &app,
                format!("setup wizard: asked for {permission:?}: {access:?}"),
            );
        }
        access
    })
    .await
}

/// The System Settings pane for `permission` (to change an earlier answer).
#[tauri::command]
pub fn wizard_permission_settings(app: AppHandle, permission: Permission) {
    if let Err(err) = app
        .opener()
        .open_url(permissions::settings_url(permission), None::<&str>)
    {
        crate::log(&app, format!("System Settings could not be opened: {err}"));
    }
}

/// "Set up tau…" from the settings window, the panel or a chat window.
#[tauri::command]
pub fn open_wizard(app: AppHandle) {
    super::open(&app);
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_status_object_passes_and_an_old_tau_core_is_named() {
        let status = br#"{"protocol": 1, "version": "0.5.0", "features": []}"#;
        assert_eq!(parse_status(status, b"", true).unwrap()["protocol"], 1);
        let old = parse_status(
            b"",
            b"Usage: tau [OPTIONS] COMMAND [ARGS]...\n\nError: No such command 'setup'.\n",
            false,
        )
        .unwrap_err();
        assert_eq!(old.code, "too_old");
        let failed =
            parse_status(b"", b"Traceback\nConfigError: tau.toml is broken\n", false).unwrap_err();
        assert_eq!(failed.code, "failed");
        assert!(
            failed.message.contains("tau.toml is broken"),
            "{}",
            failed.message
        );
        let garbage = parse_status(b"[]", b"", true).unwrap_err();
        assert_eq!(garbage.code, "failed");
    }

    #[test]
    fn the_log_line_names_the_tau_words_only() {
        let job = Job {
            program: "/example/home/.local/share/uv/tools/tau-core/bin/python".into(),
            args: [
                "-m", "tau_core", "--lang", "en", "setup", "run", "init", "--json",
            ]
            .map(String::from)
            .to_vec(),
            cwd: "/example/home".into(),
            env: Default::default(),
            stdin: Some(br#"{"inputs": {"key": "sk-example"}}"#.to_vec()),
            timeout: jobs::RUN_TIMEOUT,
            stop_grace: runner::STOP_GRACE,
        };
        let line = describe(&job);
        assert_eq!(line, "tau --lang en setup run init --json");
        assert!(!line.contains("sk-example"));
    }
}
