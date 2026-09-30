//! The commands a window's page may call (allowed per window in `capabilities/terminal.json`).
//!
//! Every command acts on the calling window's own PTY: the window label is the key, taken from
//! the IPC call itself, never from an argument. No command accepts a program, a Python path or a
//! folder: `choose_home` opens the native folder picker itself, or re-reads TauBar's hint.

use crate::home::{self, DesktopSettings, Source, Validated};
use crate::launch::Launch;
use crate::pty::{pty_size, ExitInfo, Session};
use crate::{inherited_env, Desktop};
use serde::Serialize;
use std::path::PathBuf;
use tauri::ipc::{Channel, InvokeBody, InvokeResponseBody, Request};
use tauri::{AppHandle, Manager, State, WebviewWindow};
use tauri_plugin_dialog::DialogExt;

/// What the window shows first: the terminal, or the first-run folder choice.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
#[serde(tag = "state", rename_all = "snake_case")]
pub enum HomeStatus {
    /// A checkout passed the check; the window can start `tau tui`.
    Ready {
        home: String,
        source: Source,
        version: String,
    },
    /// The window must ask: `hint` is TauBar's hub checkout, `problem` why the last try failed.
    Choose {
        hint: Option<String>,
        problem: Option<String>,
    },
}

impl Desktop {
    fn hint(&self) -> Option<PathBuf> {
        home::taubar_hint(&home::taubar_settings_path(&self.user_home))
    }

    fn choose(&self, problem: Option<String>) -> HomeStatus {
        HomeStatus::Choose {
            hint: self.hint().map(|p| p.display().to_string()),
            problem,
        }
    }

    fn ready(&self, validated: Validated, source: Source) -> HomeStatus {
        let status = HomeStatus::Ready {
            home: validated.home.display().to_string(),
            source,
            version: validated.version.clone(),
        };
        *self.home.lock().unwrap_or_else(|e| e.into_inner()) = Some((validated, source));
        status
    }

    /// The validated home of this run, if there is one.
    pub fn home(&self) -> Option<Validated> {
        self.home
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .as_ref()
            .map(|(validated, _)| validated.clone())
    }

    /// `TAU_HOME`, else the saved choice, validated once per run; otherwise ask.
    fn resolve(&self) -> HomeStatus {
        let cached = self.home.lock().unwrap_or_else(|e| e.into_inner()).clone();
        if let Some((validated, source)) = cached {
            return HomeStatus::Ready {
                home: validated.home.display().to_string(),
                source,
                version: validated.version,
            };
        }
        let saved = DesktopSettings::load(&self.settings_file).tau_home;
        let Some((folder, source)) =
            home::configured(std::env::var(home::TAU_HOME_VAR).ok(), saved)
        else {
            return self.choose(None);
        };
        match check(&folder) {
            Ok(validated) => self.ready(validated, source),
            Err(problem) => self.choose(Some(match source {
                Source::Env => {
                    format!("TAU_HOME is set to a folder tau Desktop cannot use. {problem}")
                }
                _ => format!("The folder chosen earlier no longer works. {problem}"),
            })),
        }
    }

    /// Validate a folder the person just chose and remember it.
    fn accept(&self, folder: PathBuf, source: Source) -> HomeStatus {
        match check(&folder) {
            Ok(validated) => {
                let settings = DesktopSettings {
                    tau_home: Some(validated.home.clone()),
                };
                if let Err(err) = settings.save(&self.settings_file) {
                    eprintln!(
                        "tau-desktop: {} could not be saved: {err}",
                        self.settings_file.display()
                    );
                }
                self.ready(validated, source)
            }
            Err(problem) => self.choose(Some(problem)),
        }
    }
}

fn check(folder: &std::path::Path) -> Result<Validated, String> {
    home::validate(folder, inherited_env, |launch| {
        home::run_with_timeout(launch, home::VERSION_TIMEOUT)
    })
}

async fn blocking<T: Send + 'static>(f: impl FnOnce() -> T + Send + 'static) -> Result<T, String> {
    tauri::async_runtime::spawn_blocking(f)
        .await
        .map_err(|err| format!("internal error: {err}"))
}

/// Where tau Desktop stands: ready with a checkout, or asking for one.
#[tauri::command]
pub async fn home_status(app: AppHandle) -> Result<HomeStatus, String> {
    blocking(move || app.state::<Desktop>().resolve()).await
}

/// First run: take TauBar's checkout (`use_hint`) or open the folder picker, then validate.
#[tauri::command]
pub async fn choose_home(
    app: AppHandle,
    window: WebviewWindow,
    use_hint: bool,
) -> Result<HomeStatus, String> {
    blocking(move || {
        let desktop = app.state::<Desktop>();
        if use_hint {
            return match desktop.hint() {
                Some(folder) => desktop.accept(folder, Source::Taubar),
                None => desktop.choose(Some("TauBar has no hub checkout set.".into())),
            };
        }
        let mut picker = app
            .dialog()
            .file()
            .set_title("Choose your tau checkout (TAU_HOME)")
            .set_can_create_directories(false)
            .set_parent(&window);
        if let Some(start) = desktop.hint().or_else(|| Some(desktop.user_home.clone())) {
            picker = picker.set_directory(start);
        }
        match picker.blocking_pick_folder() {
            None => desktop.choose(None),
            Some(picked) => match picked.into_path() {
                Ok(folder) => desktop.accept(folder, Source::Picked),
                Err(err) => desktop.choose(Some(format!("That folder cannot be used: {err}"))),
            },
        }
    })
    .await
}

/// Start `tau tui` in this window's PTY. Output arrives as raw bytes on `output`; `exit` gets
/// the status when the TUI ends on its own (a clean exit closes the window instead).
#[tauri::command]
pub fn pty_start(
    app: AppHandle,
    window: WebviewWindow,
    desktop: State<'_, Desktop>,
    cols: u16,
    rows: u16,
    output: Channel<InvokeResponseBody>,
    exit: Channel<ExitInfo>,
) -> Result<(), String> {
    let home = desktop.home().ok_or("No tau checkout is chosen yet.")?.home;
    let label = window.label().to_string();
    let mut sessions = desktop.sessions.lock().unwrap_or_else(|e| e.into_inner());
    if let Some(running) = sessions.get(&label) {
        if running.exited().is_none() {
            return Err("tau tui is already running in this window.".into());
        }
    }
    let launch = Launch::tui(&home, inherited_env);
    let exit_label = label.clone();
    let session = Session::spawn(
        &launch,
        pty_size(cols, rows),
        move |batch| {
            let _ = output.send(InvokeResponseBody::Raw(batch));
        },
        move |info| tui_exited(&app, &exit_label, info, &exit),
    )?;
    sessions.insert(label, session);
    Ok(())
}

/// The TUI ended. A clean exit (ctrl+q) closes the window; anything else is shown in it.
/// Nothing happens while the window or the whole app is closing it.
fn tui_exited(app: &AppHandle, label: &str, info: ExitInfo, exit: &Channel<ExitInfo>) {
    let desktop = app.state::<Desktop>();
    let closing = desktop.quitting.load(std::sync::atomic::Ordering::SeqCst)
        || desktop.session(label).is_some_and(|s| s.is_closing());
    if closing {
        return;
    }
    if info.success {
        if let Some(window) = app.get_webview_window(label) {
            let _ = window.close();
            return;
        }
    }
    let _ = exit.send(info);
}

/// Keys, pastes and mouse reports: the raw request body is written to this window's PTY, off
/// the main thread. The page keeps one write in flight at a time, so the order holds.
#[tauri::command]
pub async fn pty_write(
    window: WebviewWindow,
    desktop: State<'_, Desktop>,
    request: Request<'_>,
) -> Result<(), String> {
    let InvokeBody::Raw(bytes) = request.body() else {
        return Err("pty_write takes raw bytes.".into());
    };
    let session = desktop
        .session(window.label())
        .ok_or("tau tui is not running in this window.")?;
    let bytes = bytes.clone();
    blocking(move || session.write(&bytes))
        .await?
        .map_err(|err| format!("the PTY could not be written: {err}"))
}

/// xterm.js resized its grid: resize this window's PTY.
#[tauri::command]
pub fn pty_resize(
    window: WebviewWindow,
    desktop: State<'_, Desktop>,
    cols: u16,
    rows: u16,
) -> Result<(), String> {
    match desktop.session(window.label()) {
        Some(session) if session.exited().is_none() => session.resize(cols, rows),
        _ => Ok(()),
    }
}

/// A ⌘-clicked link in the terminal: http and https only, opened in the default browser.
#[tauri::command]
pub fn open_link(url: String) -> Result<(), String> {
    if !is_web_link(&url) {
        return Err(format!("Only http and https links are opened, not {url}"));
    }
    tauri_plugin_opener::open_url(url, None::<&str>).map_err(|err| err.to_string())
}

/// `http://` or `https://` with a host; nothing else (no `file:`, no app schemes).
pub fn is_web_link(url: &str) -> bool {
    match tauri::Url::parse(url) {
        Ok(parsed) => {
            matches!(parsed.scheme(), "http" | "https")
                && parsed.host_str().is_some_and(|h| !h.is_empty())
        }
        Err(_) => false,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn opens_only_web_links() {
        assert!(is_web_link("https://example.com/docs"));
        assert!(is_web_link("http://localhost:8000/"));
        for url in [
            "file:///etc/passwd",
            "javascript:alert(1)",
            "x-apple.systempreferences:com.apple.preference.security",
            "tauri://localhost/",
            "https://",
            "not a url",
        ] {
            assert!(!is_web_link(url), "{url}");
        }
    }

    #[test]
    fn home_status_serializes_for_the_page() {
        let ready = HomeStatus::Ready {
            home: "/path/to/tau".into(),
            source: Source::Env,
            version: "tau-core 0.3.1".into(),
        };
        assert_eq!(
            serde_json::to_value(&ready).unwrap(),
            serde_json::json!({
                "state": "ready", "home": "/path/to/tau", "source": "env",
                "version": "tau-core 0.3.1"
            })
        );
        let choose = HomeStatus::Choose {
            hint: Some("/path/to/tau".into()),
            problem: None,
        };
        assert_eq!(
            serde_json::to_value(&choose).unwrap(),
            serde_json::json!({"state": "choose", "hint": "/path/to/tau", "problem": null})
        );
    }
}
