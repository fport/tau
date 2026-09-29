//! TauBar: tau's macOS menu bar app.
//!
//! Tray only (no Dock icon): a native menu with the sleep modes and "Launch at login", plus a
//! small settings window (React) opened from the menu. See `apps/taubar/README.md`.

mod commands;
pub mod core;
pub mod eventlog;
pub mod login;
pub mod settings;
mod signals;
pub mod sleep;
pub mod tray;

use crate::core::{Core, Dirs};
use crate::settings::SleepMode;
use crate::sleep::SystemPower;
use crate::tray::{ids, TrayMenu};
use std::path::PathBuf;
use std::time::Duration;
use tauri::{AppHandle, Emitter, Manager, RunEvent, WebviewUrl, WebviewWindowBuilder, Wry};
use tauri_plugin_dialog::{DialogExt, MessageDialogKind};
use tauri_plugin_opener::OpenerExt;

pub type AppCore = Core<SystemPower>;

/// Emitted to the settings window after every change.
pub const SNAPSHOT_EVENT: &str = "taubar://snapshot";
const SETTINGS_WINDOW: &str = "settings";
const TICK: Duration = Duration::from_secs(5);

pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![
            commands::snapshot,
            commands::set_sleep_mode,
            commands::set_launch_at_login,
            commands::open_login_items,
            commands::log_tail,
            commands::open_log,
            commands::quit,
        ])
        .setup(|app| {
            // Tray only: no Dock icon, no app menu (Info.plist also sets LSUIElement).
            #[cfg(target_os = "macos")]
            app.set_activation_policy(tauri::ActivationPolicy::Accessory);
            let dirs = resolve_dirs(app.handle())?;
            app.manage(AppCore::start(dirs, SystemPower::new()));
            let menu = TrayMenu::build(app.handle(), on_menu)?;
            app.manage(menu);
            refresh(app.handle());
            signals::install(app.handle().clone());
            spawn_ticker(app.handle().clone());
            if app.state::<AppCore>().first_run {
                open_settings(app.handle());
            }
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("TauBar could not start");

    app.run(|app, event| match event {
        // Closing the settings window must not quit a tray app; only Quit (a code) does.
        RunEvent::ExitRequested {
            code: None, api, ..
        } => api.prevent_exit(),
        RunEvent::Exit => app.state::<AppCore>().shutdown(),
        // Opening TauBar.app again (Finder, Spotlight, `open -a TauBar`) shows its window:
        // the way in when macOS hides the menu bar icon behind the notch.
        #[cfg(target_os = "macos")]
        RunEvent::Reopen { .. } => open_settings(app),
        _ => {}
    });
}

/// Quit TauBar: undo what it holds, then leave the event loop.
pub fn quit(app: &AppHandle) {
    app.state::<AppCore>().shutdown();
    app.exit(0);
}

fn resolve_dirs(app: &AppHandle) -> Result<Dirs, Box<dyn std::error::Error>> {
    if let Some(home) = std::env::var_os("TAUBAR_HOME").filter(|v| !v.is_empty()) {
        return Ok(Dirs::from_home(PathBuf::from(home)));
    }
    Ok(Dirs {
        config: app.path().app_config_dir()?,
        logs: app.path().app_log_dir()?,
    })
}

/// Push the current state to the menu and the settings window.
pub fn refresh(app: &AppHandle) {
    let snapshot = app.state::<AppCore>().snapshot();
    if let Some(menu) = app.try_state::<TrayMenu<Wry>>() {
        menu.update(app, &snapshot);
    }
    let _ = app.emit(SNAPSHOT_EVENT, &snapshot);
}

fn on_menu(app: &AppHandle, id: &str) {
    let core = app.state::<AppCore>();
    match id {
        ids::SLEEP_NORMAL => {
            core.set_sleep_mode(SleepMode::Normal);
        }
        ids::SLEEP_AC => {
            core.set_sleep_mode(SleepMode::KeepAwakeOnAc);
        }
        ids::SLEEP_LID => {
            core.set_sleep_mode(SleepMode::KeepAwakeLidClosed);
        }
        ids::LOGIN => {
            let enable = !core.login_status().checked();
            if let Err(err) = core.set_launch_at_login(enable) {
                error_dialog(
                    app,
                    "Launch at login",
                    &format!(
                        "macOS refused to change the login item: {err}\n\nLaunch at login works \
                         for the TauBar.app bundle (not for `pnpm tauri dev`)."
                    ),
                );
            }
        }
        ids::SETTINGS => open_settings(app),
        ids::OPEN_LOG => open_log(app),
        ids::QUIT => {
            quit(app);
            return;
        }
        _ => {}
    }
    refresh(app);
}

/// Every few seconds: pick up changes made outside TauBar (login item toggled in System
/// Settings, sudoers rule installed or removed).
fn spawn_ticker(app: AppHandle) {
    let ticker = app.clone();
    let spawned = std::thread::Builder::new()
        .name("taubar-ticker".into())
        .spawn(move || loop {
            std::thread::sleep(TICK);
            let core = ticker.state::<AppCore>();
            let login_changed = core.refresh_login();
            let sleep_changed = core.recheck_sleep();
            if login_changed || sleep_changed {
                refresh(&ticker);
            }
        });
    if let Err(err) = spawned {
        app.state::<AppCore>()
            .log
            .write(format!("ticker thread could not start: {err}"));
    }
}

pub fn open_settings(app: &AppHandle) {
    if let Some(window) = app.get_webview_window(SETTINGS_WINDOW) {
        let _ = window.unminimize();
        let _ = window.show();
        let _ = window.set_focus();
        return;
    }
    let built =
        WebviewWindowBuilder::new(app, SETTINGS_WINDOW, WebviewUrl::App("index.html".into()))
            .title("TauBar Settings")
            .inner_size(560.0, 660.0)
            .min_inner_size(460.0, 420.0)
            .center()
            .focused(true)
            .build();
    match built {
        Ok(window) => {
            let _ = window.set_focus();
        }
        Err(err) => app
            .state::<AppCore>()
            .log
            .write(format!("the settings window could not open: {err}")),
    }
}

pub fn open_log(app: &AppHandle) {
    let core = app.state::<AppCore>();
    let path = core.log.path().to_path_buf();
    if !path.exists() {
        core.log.write("log opened");
    }
    if let Err(err) = app
        .opener()
        .open_path(path.display().to_string(), None::<&str>)
    {
        core.log
            .write(format!("the log could not be opened: {err}"));
    }
}

fn error_dialog(app: &AppHandle, title: &str, message: &str) {
    app.dialog()
        .message(message)
        .title(title)
        .kind(MessageDialogKind::Error)
        .show(|_| {});
}
