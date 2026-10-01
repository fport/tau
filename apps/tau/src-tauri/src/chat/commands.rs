//! The commands a chat window's page may call (allowed only for `chat-*` windows, in
//! `capabilities/chat.json`).
//!
//! Every command acts on the calling window's own PTY: the window label is the key, taken from
//! the IPC call itself, never from an argument. No command accepts a program, a Python path or a
//! folder: `choose_home` opens the native folder picker itself, or reads the hub's checkout.

use super::home::{self, Source, Validated};
use super::launch::Launch;
use super::pty::{pty_size, ExitInfo, Session};
use super::{inherited_env, Chats};
use crate::AppCore;
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
    /// The window must ask: `hint` is the hub's checkout, `problem` why the last try failed.
    Choose {
        hint: Option<String>,
        problem: Option<String>,
    },
}

/// The checkout the app runs the hub from (the hub settings' `tau_home`): the first-run hint.
/// Only the folder is taken; the hub's `python` never reaches a chat window.
fn hub_checkout(app: &AppHandle) -> Option<PathBuf> {
    app.state::<AppCore>()
        .settings()
        .hub
        .tau_home
        .filter(|p| !p.as_os_str().is_empty())
}

impl Chats {
    fn choose(&self, hint: Option<PathBuf>, problem: Option<String>) -> HomeStatus {
        HomeStatus::Choose {
            hint: hint.map(|p| p.display().to_string()),
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
    fn resolve(&self, hint: Option<PathBuf>) -> HomeStatus {
        let cached = self.home.lock().unwrap_or_else(|e| e.into_inner()).clone();
        if let Some((validated, source)) = cached {
            return HomeStatus::Ready {
                home: validated.home.display().to_string(),
                source,
                version: validated.version,
            };
        }
        let env_home = std::env::var(home::TAU_HOME_VAR).ok();
        match home::resolve(env_home, &self.settings_file, check) {
            Ok((validated, source)) => self.ready(validated, source),
            Err(problem) => self.choose(hint, problem),
        }
    }

    /// What a first-run choice led to: ready, or ask again with the problem.
    fn after_choice(
        &self,
        hint: Option<PathBuf>,
        found: Result<home::Found, String>,
    ) -> HomeStatus {
        match found {
            Ok((validated, source)) => self.ready(validated, source),
            Err(problem) => self.choose(hint, Some(problem)),
        }
    }
}

fn check(
    folder: &std::path::Path,
    installed: Option<&std::path::Path>,
) -> Result<Validated, String> {
    home::validate(folder, installed, inherited_env, |launch| {
        home::run_with_timeout(launch, home::VERSION_TIMEOUT)
    })
}

async fn blocking<T: Send + 'static>(f: impl FnOnce() -> T + Send + 'static) -> Result<T, String> {
    tauri::async_runtime::spawn_blocking(f)
        .await
        .map_err(|err| format!("internal error: {err}"))
}

/// Where the chat windows stand: ready with a checkout, or asking for one.
#[tauri::command]
pub async fn home_status(app: AppHandle) -> Result<HomeStatus, String> {
    blocking(move || app.state::<Chats>().resolve(hub_checkout(&app))).await
}

/// First run: take the hub's checkout (`use_hint`) or open the folder picker, then validate.
#[tauri::command]
pub async fn choose_home(
    app: AppHandle,
    window: WebviewWindow,
    use_hint: bool,
) -> Result<HomeStatus, String> {
    blocking(move || {
        let chats = app.state::<Chats>();
        let hint = hub_checkout(&app);
        if use_hint {
            let found = home::accept_hint(hint.clone(), &chats.settings_file, check);
            return chats.after_choice(hint, found);
        }
        let mut picker = app
            .dialog()
            .file()
            .set_title("Choose your tau checkout (TAU_HOME)")
            .set_can_create_directories(false)
            .set_parent(&window);
        if let Some(start) = hint.clone().or_else(|| Some(chats.user_home.clone())) {
            picker = picker.set_directory(start);
        }
        match picker.blocking_pick_folder() {
            None => chats.choose(hint, None),
            Some(picked) => match picked.into_path() {
                Ok(folder) => chats.after_choice(
                    hint,
                    home::accept(&folder, Source::Picked, &chats.settings_file, check),
                ),
                Err(err) => chats.choose(hint, Some(format!("That folder cannot be used: {err}"))),
            },
        }
    })
    .await
}

/// Start `tau tui` in this window's PTY. Output arrives as raw bytes on `output`; `exit` gets
/// the status when the TUI ends on its own (a clean exit closes the window instead).
///
/// If this window's TUI is still running, the page was reloaded (Tauri reloads a page whose web
/// content process crashed; `bun run tauri dev` reloads on some edits): the new page takes the
/// running TUI over instead of starting a second one, so nothing is left running out of reach.
#[tauri::command]
pub fn pty_start(
    app: AppHandle,
    window: WebviewWindow,
    chats: State<'_, Chats>,
    cols: u16,
    rows: u16,
    output: Channel<InvokeResponseBody>,
    exit: Channel<ExitInfo>,
) -> Result<(), String> {
    let home = chats.home().ok_or("No tau checkout is chosen yet.")?;
    let label = window.label().to_string();
    let mut sessions = chats.sessions.lock().unwrap_or_else(|e| e.into_inner());
    if let Some(running) = sessions.get(&label).cloned() {
        if running.is_closing() {
            return Err("tau tui is closing in this window.".into());
        }
        let attached = running.reattach(
            output_sink(output.clone()),
            exit_sink(app.clone(), label.clone(), exit.clone()),
        );
        if attached {
            // Without the repaint the screen fills in as the TUI draws; the keys work either way.
            if let Err(err) = running.repaint(cols, rows) {
                crate::log(&app, format!("the TUI could not be made to repaint: {err}"));
            }
            return Ok(());
        }
        // Its exit was already reported: that TUI is over, start a new one.
    }
    let launch = Launch::tui(&home.home, &home.python, inherited_env);
    let session = Session::spawn(
        &launch,
        pty_size(cols, rows),
        output_sink(output),
        exit_sink(app, label.clone(), exit),
    )?;
    sessions.insert(label, session);
    Ok(())
}

/// Output batches to the page, as raw bytes (a page that is gone just drops them).
fn output_sink(output: Channel<InvokeResponseBody>) -> impl FnMut(Vec<u8>) + Send + 'static {
    move |batch| {
        let _ = output.send(InvokeResponseBody::Raw(batch));
    }
}

fn exit_sink(
    app: AppHandle,
    label: String,
    exit: Channel<ExitInfo>,
) -> impl FnOnce(ExitInfo) + Send + 'static {
    move |info| tui_exited(&app, &label, info, &exit)
}

/// The TUI ended. A clean exit (ctrl+q) closes the window; anything else is shown in it.
/// Nothing happens while the window or the whole app is closing it.
fn tui_exited(app: &AppHandle, label: &str, info: ExitInfo, exit: &Channel<ExitInfo>) {
    let chats = app.state::<Chats>();
    let closing = chats.quitting() || chats.session(label).is_some_and(|s| s.is_closing());
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
    chats: State<'_, Chats>,
    request: Request<'_>,
) -> Result<(), String> {
    let InvokeBody::Raw(bytes) = request.body() else {
        return Err("pty_write takes raw bytes.".into());
    };
    let session = chats
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
    chats: State<'_, Chats>,
    cols: u16,
    rows: u16,
) -> Result<(), String> {
    match chats.session(window.label()) {
        Some(session) if session.exited().is_none() => session.resize(cols, rows),
        _ => Ok(()),
    }
}

/// A ⌘-clicked link in the terminal: http and https only, opened in the default browser.
/// What is opened is the URL as parsed and checked, never the raw text from the page.
#[tauri::command]
pub fn open_link(url: String) -> Result<(), String> {
    let link =
        web_link(&url).ok_or_else(|| format!("Only http and https links are opened, not {url}"))?;
    tauri_plugin_opener::open_url(link, None::<&str>).map_err(|err| err.to_string())
}

/// The canonical form of an `http://` or `https://` URL with a host; `None` for anything else
/// (no `file:`, no app schemes).
pub fn web_link(url: &str) -> Option<String> {
    let parsed = tauri::Url::parse(url).ok()?;
    let web = matches!(parsed.scheme(), "http" | "https")
        && parsed.host_str().is_some_and(|h| !h.is_empty());
    web.then(|| parsed.as_str().to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn opens_only_web_links() {
        assert_eq!(
            web_link("https://example.com/docs").as_deref(),
            Some("https://example.com/docs")
        );
        assert_eq!(
            web_link("http://localhost:8000/").as_deref(),
            Some("http://localhost:8000/")
        );
        for url in [
            "file:///etc/passwd",
            "javascript:alert(1)",
            "x-apple.systempreferences:com.apple.preference.security",
            "tauri://localhost/",
            "https://",
            "not a url",
        ] {
            assert_eq!(web_link(url), None, "{url}");
        }
    }

    #[test]
    fn opens_the_url_that_was_checked_not_the_raw_text() {
        // The parser drops outer spaces and control characters and inner tabs and newlines;
        // what is opened is that parsed form.
        assert_eq!(
            web_link(" https://example.com/a b\n").as_deref(),
            Some("https://example.com/a%20b")
        );
        assert_eq!(
            web_link("https://exa\tmple.com/").as_deref(),
            Some("https://example.com/")
        );
        assert_eq!(
            web_link("HTTPS://Example.COM").as_deref(),
            Some("https://example.com/")
        );
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
