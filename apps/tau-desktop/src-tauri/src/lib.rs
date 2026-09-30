//! tau Desktop: `tau tui` in a native window.
//!
//! Every window is a webview with xterm.js and its own PTY running
//! `<TAU_HOME>/.venv/bin/python -m tau_core tui`, so every TUI feature (and the guard's lock
//! screen) works unchanged; the TUI's channel is `tui`. The app itself never uses the camera or
//! the microphone (the guard runs in the hub), denies every webview permission request and opens
//! no network listener. See `apps/tau-desktop/README.md`.

mod commands;
pub mod home;
pub mod launch;
pub mod modes;
pub mod pty;

use crate::home::{Source, Validated};
use crate::pty::{Session, QUIT_GRACE};
use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, AtomicU32, Ordering};
use std::sync::{Arc, Mutex};
use tauri::menu::{Menu, MenuItemBuilder, SubmenuBuilder};
use tauri::webview::{Color, NewWindowResponse, PermissionResponse};
use tauri::{
    AppHandle, Manager, RunEvent, Runtime, Url, WebviewUrl, WebviewWindowBuilder, WindowEvent,
};

/// Window labels: `term-1`, `term-2`, … (`capabilities/terminal.json` matches `term-*`).
const WINDOW_PREFIX: &str = "term-";
const MENU_NEW_WINDOW: &str = "new-window";
const MENU_QUIT: &str = "quit";
/// Void, the brand background, so a new window never flashes white.
const BACKGROUND: Color = Color(0x05, 0x07, 0x1a, 0xff);
/// How far a new window sits from the one in front.
const CASCADE: f64 = 28.0;

/// State shared by the windows and the menu.
pub struct Desktop {
    /// The checkout this run uses, once validated, and where it came from.
    home: Mutex<Option<(Validated, Source)>>,
    /// One session per window label.
    sessions: Mutex<HashMap<String, Arc<Session>>>,
    /// tau Desktop's own `settings.json` (the first-run choice).
    settings_file: PathBuf,
    /// The user's home directory (TauBar's settings live under it).
    user_home: PathBuf,
    next_window: AtomicU32,
    quitting: AtomicBool,
}

impl Desktop {
    fn session(&self, label: &str) -> Option<Arc<Session>> {
        self.sessions
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .get(label)
            .cloned()
    }

    fn remove_session(&self, label: &str) -> Option<Arc<Session>> {
        self.sessions
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .remove(label)
    }

    /// Quit every TUI at once (ctrl+q each, one shared grace period, then kill what is left).
    /// Only for quitting the app: it also stops exits from closing windows or opening new ones.
    fn shutdown_all(&self) {
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

pub fn run() {
    let app = tauri::Builder::default()
        // Folder picker for the first run, driven from Rust; no page may call it.
        .plugin(tauri_plugin_dialog::init())
        // Wry grants camera and microphone requests when nothing answers them; the app has no
        // use for either, so every request from every webview is denied.
        .on_permission_request(|_, _| PermissionResponse::Deny)
        .menu(build_menu)
        .on_menu_event(|app, event| match event.id().as_ref() {
            MENU_NEW_WINDOW => open_window(app),
            MENU_QUIT => quit(app),
            _ => {}
        })
        .on_window_event(on_window_event)
        .invoke_handler(tauri::generate_handler![
            commands::home_status,
            commands::choose_home,
            commands::pty_start,
            commands::pty_write,
            commands::pty_resize,
            commands::open_link,
        ])
        .setup(|app| {
            let user_home = app.path().home_dir()?;
            let settings_file = app.path().app_config_dir()?.join(home::SETTINGS_FILE);
            app.manage(Desktop {
                home: Mutex::new(None),
                sessions: Mutex::new(HashMap::new()),
                settings_file,
                user_home,
                next_window: AtomicU32::new(1),
                quitting: AtomicBool::new(false),
            });
            install_signal_handlers(app.handle().clone());
            open_window(app.handle());
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("tau Desktop could not start");

    app.run(|app, event| match event {
        // The last window closed: stay running, like Terminal; ⌘N or the Dock opens a new one.
        RunEvent::ExitRequested {
            code: None, api, ..
        } if !app.state::<Desktop>().quitting.load(Ordering::SeqCst) => api.prevent_exit(),
        // Whatever path led here, no TUI outlives the app.
        RunEvent::Exit => app.state::<Desktop>().shutdown_all(),
        #[cfg(target_os = "macos")]
        RunEvent::Reopen {
            has_visible_windows: false,
            ..
        } => open_window(app),
        _ => {}
    });
}

/// The macOS menu: New Window (⌘N), Close Window (⌘W), Copy and Paste for the terminal, Quit.
fn build_menu<R: Runtime>(app: &AppHandle<R>) -> tauri::Result<Menu<R>> {
    let new_window = MenuItemBuilder::with_id(MENU_NEW_WINDOW, "New Window")
        .accelerator("CmdOrCtrl+N")
        .build(app)?;
    let quit = MenuItemBuilder::with_id(MENU_QUIT, "Quit tau Desktop")
        .accelerator("CmdOrCtrl+Q")
        .build(app)?;
    let app_menu = SubmenuBuilder::new(app, "tau Desktop")
        .about(None)
        .separator()
        .services()
        .separator()
        .hide()
        .hide_others()
        .show_all()
        .separator()
        .item(&quit)
        .build()?;
    let file = SubmenuBuilder::new(app, "File")
        .item(&new_window)
        .separator()
        .close_window()
        .build()?;
    // Copy and Paste reach xterm.js through the webview's copy and paste events. No Select All:
    // ⌘A goes to xterm.js, which selects the terminal's text.
    let edit = SubmenuBuilder::new(app, "Edit").copy().paste().build()?;
    let window = SubmenuBuilder::new(app, "Window")
        .minimize()
        .maximize()
        .separator()
        .fullscreen()
        .separator()
        .bring_all_to_front()
        .build()?;
    Menu::with_items(app, &[&app_menu, &file, &edit, &window])
}

/// A new window with its own terminal (and, once the page asks, its own PTY).
fn open_window(app: &AppHandle) {
    let desktop = app.state::<Desktop>();
    if desktop.quitting.load(Ordering::SeqCst) {
        return;
    }
    let n = desktop.next_window.fetch_add(1, Ordering::SeqCst);
    let label = format!("{WINDOW_PREFIX}{n}");
    let mut builder = WebviewWindowBuilder::new(app, &label, WebviewUrl::App("index.html".into()))
        .title("tau")
        .inner_size(1000.0, 680.0)
        .min_inner_size(480.0, 320.0)
        .background_color(BACKGROUND)
        .focused(true)
        .on_permission_request(|_, _| PermissionResponse::Deny)
        .on_navigation(is_app_url)
        .on_new_window(|_, _| NewWindowResponse::Deny)
        .disable_drag_drop_handler();
    builder = match cascade_from_front(app) {
        Some((x, y)) => builder.position(x, y),
        None => builder.center(),
    };
    match builder.build() {
        Ok(window) => {
            let _ = window.set_focus();
        }
        Err(err) => eprintln!("tau-desktop: a window could not open: {err}"),
    }
}

/// Just below and right of the focused terminal window, in logical coordinates.
fn cascade_from_front(app: &AppHandle) -> Option<(f64, f64)> {
    let front = app
        .webview_windows()
        .into_values()
        .find(|w| w.is_focused().unwrap_or(false))?;
    let scale = front.scale_factor().ok()?;
    let position = front.outer_position().ok()?.to_logical::<f64>(scale);
    Some((position.x + CASCADE, position.y + CASCADE))
}

/// The page may only ever show the app's own bundle (`tauri://localhost`, or Vite in dev).
fn is_app_url(url: &Url) -> bool {
    match url.scheme() {
        "tauri" => url.host_str() == Some("localhost"),
        "http" if cfg!(dev) => url.host_str() == Some("localhost") && url.port() == Some(1420),
        _ => false,
    }
}

fn on_window_event(window: &tauri::Window, event: &WindowEvent) {
    let app = window.app_handle();
    let desktop = app.state::<Desktop>();
    match event {
        // Closing a window quits its TUI first: ctrl+q, up to a second, then the process group
        // is killed. The window hides at once and goes away when the TUI is gone.
        WindowEvent::CloseRequested { api, .. } => {
            let Some(session) = desktop.session(window.label()) else {
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
                    .name("tau-desktop-close".into())
                    .spawn(move || {
                        session.shutdown(QUIT_GRACE);
                        let _ = window.destroy();
                    });
                if let Err(err) = spawned {
                    eprintln!("tau-desktop: close thread could not start: {err}");
                }
            }
        }
        WindowEvent::Destroyed => {
            if let Some(session) = desktop.remove_session(window.label()) {
                if session.exited().is_none() {
                    std::thread::spawn(move || {
                        session.begin_closing();
                        session.shutdown(QUIT_GRACE);
                    });
                }
            }
        }
        _ => {}
    }
}

/// Quit: every TUI quits (or is killed after the grace period), then the app exits.
fn quit(app: &AppHandle) {
    if app.state::<Desktop>().quitting.swap(true, Ordering::SeqCst) {
        return;
    }
    for window in app.webview_windows().values() {
        let _ = window.hide();
    }
    let app = app.clone();
    let spawned = std::thread::Builder::new()
        .name("tau-desktop-quit".into())
        .spawn(move || {
            app.state::<Desktop>().shutdown_all();
            app.exit(0);
        });
    if let Err(err) = spawned {
        eprintln!("tau-desktop: quit thread could not start: {err}");
    }
}

/// SIGTERM, SIGINT and SIGHUP (logout, `kill <pid>`, Ctrl-C in `pnpm tauri dev`) quit the same
/// way the menu does, so the TUIs get their ctrl+q.
fn install_signal_handlers(app: AppHandle) {
    use signal_hook::consts::{SIGHUP, SIGINT, SIGTERM};
    let mut signals = match signal_hook::iterator::Signals::new([SIGTERM, SIGINT, SIGHUP]) {
        Ok(signals) => signals,
        Err(err) => {
            eprintln!("tau-desktop: signal handlers could not be installed: {err}");
            return;
        }
    };
    let spawned = std::thread::Builder::new()
        .name("tau-desktop-signals".into())
        .spawn(move || {
            if signals.forever().next().is_some() {
                quit(&app);
            }
        });
    if let Err(err) = spawned {
        eprintln!("tau-desktop: signal thread could not start: {err}");
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_page_cannot_navigate_away() {
        assert!(is_app_url(&"tauri://localhost/index.html".parse().unwrap()));
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
}
