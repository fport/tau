//! Chat windows: `tau tui` in a native window (what tau Desktop was, roadmap 116 and 170).
//!
//! Every chat window is a webview with xterm.js and its own PTY running
//! `<TAU_HOME>/.venv/bin/python -m tau_core tui`, so every TUI feature (and the guard's lock
//! screen) works unchanged; the TUI's channel is `tui`. The window itself never uses the camera
//! or the microphone: like every webview of the app it denies every permission request
//! (`webview.rs`), and it opens no network listener.
//!
//! While at least one chat window is open the app is a regular app, with a Dock icon and the
//! menu bar (`app_menu.rs`); when the last one closes it goes back to the menu bar only.

pub mod commands;
pub mod home;
pub mod launch;
pub mod modes;
pub mod pty;

use crate::webview;
use home::{Source, Validated};
use pty::{Session, QUIT_GRACE};
use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, AtomicU32, Ordering};
use std::sync::{Arc, Mutex};
use tauri::webview::{Color, NewWindowResponse};
use tauri::{AppHandle, Manager, Url, WebviewUrl, WebviewWindowBuilder, WindowEvent};

/// Window labels: `chat-1`, `chat-2`, … (`capabilities/chat.json` matches `chat-*`).
pub const WINDOW_PREFIX: &str = "chat-";
/// The page a chat window shows (`src/main.tsx` picks the chat view by the hash).
const PAGE: &str = "index.html#chat";
/// Void, the brand background, so a new window never flashes white.
const BACKGROUND: Color = Color(0x05, 0x07, 0x1a, 0xff);
/// How far a new window sits from the one in front.
const CASCADE: f64 = 28.0;

/// State shared by the chat windows.
pub struct Chats {
    /// The checkout the chat windows use, once validated, and where it came from.
    home: Mutex<Option<(Validated, Source)>>,
    /// One session per window label.
    sessions: Mutex<HashMap<String, Arc<Session>>>,
    /// The chat windows' own `chat.json` (the folder chosen for them).
    settings_file: PathBuf,
    /// The user's home directory (where the folder picker starts without a hint).
    user_home: PathBuf,
    next_window: AtomicU32,
    quitting: AtomicBool,
}

impl Chats {
    pub fn new(settings_file: PathBuf, user_home: PathBuf) -> Self {
        Self {
            home: Mutex::new(None),
            sessions: Mutex::new(HashMap::new()),
            settings_file,
            user_home,
            next_window: AtomicU32::new(1),
            quitting: AtomicBool::new(false),
        }
    }

    /// The PTY session of the window `label` (a chat window, or the wizard's terminal).
    pub(crate) fn session(&self, label: &str) -> Option<Arc<Session>> {
        self.sessions
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .get(label)
            .cloned()
    }

    pub(crate) fn remove_session(&self, label: &str) -> Option<Arc<Session>> {
        self.sessions
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .remove(label)
    }

    /// Give the window `label` a new session, unless it still runs one. `start` is called with
    /// the sessions locked, so two calls cannot both start one.
    pub(crate) fn start_session(
        &self,
        label: &str,
        start: impl FnOnce() -> Result<Arc<Session>, String>,
    ) -> Result<(), String> {
        let mut sessions = self.sessions.lock().unwrap_or_else(|e| e.into_inner());
        if let Some(running) = sessions.get(label) {
            if running.exited().is_none() {
                return Err("A command is still running in this window.".into());
            }
        }
        let session = start()?;
        sessions.insert(label.to_string(), session);
        Ok(())
    }

    /// The chat windows' `chat.json`.
    pub fn settings_file(&self) -> &std::path::Path {
        &self.settings_file
    }

    /// Forget the home validated in this run, so the next window resolves it again (after the
    /// setup wizard saved a new one).
    pub fn forget_home(&self) {
        *self.home.lock().unwrap_or_else(|e| e.into_inner()) = None;
    }

    /// The app is quitting: no new windows, and TUI exits no longer close windows.
    pub fn begin_quit(&self) -> bool {
        !self.quitting.swap(true, Ordering::SeqCst)
    }

    pub fn quitting(&self) -> bool {
        self.quitting.load(Ordering::SeqCst)
    }

    /// A checkout for the chat windows is known without asking: `TAU_HOME`, or one chosen
    /// earlier. (It is validated when a window starts.)
    pub fn has_home(&self) -> bool {
        let env = std::env::var(home::TAU_HOME_VAR).ok();
        let saved = home::ChatSettings::load(&self.settings_file).tau_home;
        home::configured(env, saved).is_some()
    }

    /// Quit every TUI at once (ctrl+q each, one shared grace period, then kill what is left).
    /// Only for quitting the app; idempotent (the sessions are drained).
    pub fn shutdown_all(&self) {
        self.quitting.store(true, Ordering::SeqCst);
        let sessions: Vec<Arc<Session>> = self
            .sessions
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .drain()
            .map(|(_, s)| s)
            .collect();
        let handles: Vec<_> = sessions
            .into_iter()
            .map(|session| {
                std::thread::spawn(move || {
                    session.begin_closing();
                    session.shutdown(QUIT_GRACE);
                })
            })
            .collect();
        for handle in handles {
            let _ = handle.join();
        }
    }
}

/// The app's own environment, for the allowlist in `launch.rs`.
pub(crate) fn inherited_env(name: &str) -> Option<String> {
    std::env::var(name).ok()
}

pub fn is_chat_window(label: &str) -> bool {
    label.starts_with(WINDOW_PREFIX)
}

/// A new chat window with its own terminal (and, once the page asks, its own PTY).
pub fn open_window(app: &AppHandle) {
    let chats = app.state::<Chats>();
    if chats.quitting() {
        return;
    }
    crate::panel::hide(app);
    let n = chats.next_window.fetch_add(1, Ordering::SeqCst);
    let label = format!("{WINDOW_PREFIX}{n}");
    let mut builder = WebviewWindowBuilder::new(app, &label, WebviewUrl::App(PAGE.into()))
        .title("tau")
        .inner_size(1000.0, 680.0)
        .min_inner_size(480.0, 320.0)
        .background_color(BACKGROUND)
        .focused(true)
        // The app holds the camera grant for its hub; no chat page may use it (ADR 0008).
        .on_permission_request(|_, kind| webview::permission(kind))
        .on_navigation(is_app_url)
        .on_new_window(|_, _| NewWindowResponse::Deny)
        .disable_drag_drop_handler();
    builder = match cascade_from_front(app) {
        Some((x, y)) => builder.position(x, y),
        None => builder.center(),
    };
    match builder.build() {
        Ok(window) => {
            dock(app, true);
            let _ = window.set_focus();
        }
        Err(err) => crate::log(app, format!("a chat window could not open: {err}")),
    }
}

/// Just below and right of the focused chat window, in logical coordinates.
fn cascade_from_front(app: &AppHandle) -> Option<(f64, f64)> {
    let front = app
        .webview_windows()
        .into_iter()
        .find(|(label, w)| is_chat_window(label) && w.is_focused().unwrap_or(false))?
        .1;
    let scale = front.scale_factor().ok()?;
    let position = front.outer_position().ok()?.to_logical::<f64>(scale);
    Some((position.x + CASCADE, position.y + CASCADE))
}

/// A chat page (and the wizard's) may only ever show the app's own bundle (`tauri://localhost`,
/// or Vite in dev).
pub(crate) fn is_app_url(url: &Url) -> bool {
    match url.scheme() {
        "tauri" => url.host_str() == Some("localhost"),
        "http" if cfg!(dev) => url.host_str() == Some("localhost") && url.port() == Some(1420),
        _ => false,
    }
}

/// With a chat window open the app shows in the Dock and has the menu bar (a regular app);
/// without one it lives in the menu bar only (an accessory app, as `Info.plist` starts it).
fn dock(app: &AppHandle, shown: bool) {
    #[cfg(target_os = "macos")]
    {
        let policy = if shown {
            tauri::ActivationPolicy::Regular
        } else {
            tauri::ActivationPolicy::Accessory
        };
        if let Err(err) = app.set_activation_policy(policy) {
            crate::log(app, format!("the Dock icon could not be changed: {err}"));
        }
    }
    #[cfg(not(target_os = "macos"))]
    let _ = (app, shown);
}

/// Whether a chat window other than `closing` is still there.
fn other_chat_windows(app: &AppHandle, closing: &str) -> bool {
    app.webview_windows()
        .keys()
        .any(|label| is_chat_window(label) && label != closing)
}

/// Every window's events (installed on the app builder); only chat windows are handled here.
pub fn on_window_event(window: &tauri::Window, event: &WindowEvent) {
    let label = window.label();
    if !is_chat_window(label) {
        return;
    }
    let app = window.app_handle();
    let chats = app.state::<Chats>();
    match event {
        // Closing a window quits its TUI first: ctrl+q, up to a second, then the process group
        // is killed. The window hides at once and goes away when the TUI is gone.
        WindowEvent::CloseRequested { api, .. } => {
            let Some(session) = chats.session(label) else {
                return;
            };
            if session.exited().is_some() {
                return;
            }
            api.prevent_close();
            if session.begin_closing() {
                let _ = window.hide();
                let window = window.clone();
                let spawned = std::thread::Builder::new()
                    .name("tau-chat-close".into())
                    .spawn(move || {
                        session.shutdown(QUIT_GRACE);
                        let _ = window.destroy();
                    });
                if let Err(err) = spawned {
                    crate::log(app, format!("a chat close thread could not start: {err}"));
                }
            }
        }
        WindowEvent::Destroyed => {
            if let Some(session) = chats.remove_session(label) {
                if session.exited().is_none() {
                    std::thread::spawn(move || {
                        session.begin_closing();
                        session.shutdown(QUIT_GRACE);
                    });
                }
            }
            if !chats.quitting() && !other_chat_windows(app, label) {
                dock(app, false);
            }
        }
        _ => {}
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_page_cannot_navigate_away() {
        assert!(is_app_url(&"tauri://localhost/index.html".parse().unwrap()));
        assert!(is_app_url(
            &"tauri://localhost/index.html#chat".parse().unwrap()
        ));
        for url in [
            "https://example.com/",
            "tauri://example.com/",
            "file:///etc/passwd",
            "http://localhost:7877/status",
            "about:blank",
        ] {
            assert!(!is_app_url(&url.parse().unwrap()), "{url}");
        }
    }

    #[test]
    fn chat_windows_are_told_apart_by_their_label() {
        assert!(is_chat_window("chat-1"));
        assert!(is_chat_window("chat-12"));
        for label in ["settings", "panel", crate::wizard::WINDOW, "chat"] {
            assert!(!is_chat_window(label), "{label}");
        }
    }

    /// The capability that grants the PTY commands names exactly the chat windows.
    #[test]
    fn the_chat_capability_matches_the_window_labels() {
        let path = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("capabilities/chat.json");
        let text = std::fs::read_to_string(path).unwrap();
        let capability: serde_json::Value = serde_json::from_str(&text).unwrap();
        assert_eq!(
            capability["windows"],
            serde_json::json!([format!("{WINDOW_PREFIX}*")])
        );
    }
}
