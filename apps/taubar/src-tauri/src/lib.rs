//! TauBar: tau's macOS menu bar app.
//!
//! Tray only (no Dock icon): a left click on the icon opens the panel (React, `panel.rs`) with
//! the hub switch and its status, the sleep modes and "Launch at login"; the right click shows
//! the same as a native menu. A settings window (React) opens from either. See
//! `apps/taubar/README.md`.

mod commands;
pub mod core;
pub mod eventlog;
pub mod hub;
pub mod login;
pub mod panel;
pub mod settings;
mod signals;
pub mod sleep;
pub mod tray;

use crate::core::{Core, Dirs};
use crate::hub::supervisor::SystemProbe;
use crate::settings::SleepMode;
use crate::sleep::SystemPower;
use crate::tray::{ids, TrayMenu};
use std::path::{Path, PathBuf};
use std::time::Duration;
use tauri::{AppHandle, Emitter, Manager, RunEvent, WebviewUrl, WebviewWindowBuilder, Wry};
use tauri_plugin_dialog::{DialogExt, MessageDialogKind};
use tauri_plugin_opener::OpenerExt;

pub type AppCore = Core<SystemPower, SystemProbe>;

/// Emitted to the settings window after every change.
pub const SNAPSHOT_EVENT: &str = "taubar://snapshot";
const SETTINGS_WINDOW: &str = "settings";
/// Login item and sudoers rule checks.
const TICK: Duration = Duration::from_secs(5);
/// The hub supervisor's step.
const HUB_TICK: Duration = Duration::from_secs(1);

pub fn run() {
    let app = tauri::Builder::default()
        // One TauBar per user (roadmap 091). A second launch, from Spotlight, Finder,
        // `open -n` or the build folder of a checkout, hands over to the running TauBar and
        // exits before it touches the hub or the sleep assertion; the running one shows its
        // window. Registered first, as the plugin requires.
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            open_settings(app);
        }))
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
            commands::set_run_hub,
            commands::save_hub_settings,
            commands::open_hub_log,
            commands::open_settings,
            commands::panel_fit,
            commands::panel_hide,
        ])
        .setup(|app| {
            // Tray only: no Dock icon, no app menu (Info.plist also sets LSUIElement).
            #[cfg(target_os = "macos")]
            app.set_activation_policy(tauri::ActivationPolicy::Accessory);
            let dirs = resolve_dirs(app.handle())?;
            let user_home = app.path().home_dir()?;
            let probe = SystemProbe {
                user_home: user_home.clone(),
            };
            app.manage(AppCore::start(dirs, SystemPower::new(), probe, user_home));
            let menu = TrayMenu::build(app.handle(), on_menu, panel::toggle)?;
            app.manage(menu);
            app.manage(panel::PanelState::default());
            if let Err(err) = panel::build(app.handle()) {
                // The menu still has everything; let the left click show it too.
                app.state::<AppCore>()
                    .log
                    .write(format!("the panel could not be created: {err}"));
                if let Some(tray) = app.tray_by_id(tray::TRAY_ID) {
                    let _ = tray.set_show_menu_on_left_click(true);
                }
            }
            refresh(app.handle());
            signals::install(app.handle().clone());
            spawn_ticker(app.handle().clone());
            spawn_hub_thread(app.handle().clone());
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

/// Turn "Run the hub" on or off, off the main thread (it can wait on the hub supervisor), and
/// explain when TauBar cannot do what the switch says.
pub fn toggle_hub(app: &AppHandle, on: bool) {
    let app = app.clone();
    let spawned = std::thread::Builder::new()
        .name("taubar-hub-switch".into())
        .spawn(move || {
            let message = app.state::<AppCore>().set_run_hub(on);
            refresh(&app);
            if let Some(message) = message {
                info_dialog(&app, "Run the hub", &message);
            }
        });
    if let Err(err) = spawned {
        eprintln!("taubar: hub switch thread could not start: {err}");
    }
}

fn on_menu(app: &AppHandle, id: &str) {
    let core = app.state::<AppCore>();
    match id {
        ids::HUB_RUN => {
            toggle_hub(app, !core.hub_switch());
            return;
        }
        ids::HUB_LOG => open_hub_log(app),
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

/// Every second: one hub supervisor step (reap, restart, poll `/health` and `/status`), then
/// refresh the menu and the window. A panic in a step is logged and the loop goes on, so
/// supervision never silently stops.
fn spawn_hub_thread(app: AppHandle) {
    let hub = app.clone();
    let spawned = std::thread::Builder::new()
        .name("taubar-hub".into())
        .spawn(move || loop {
            std::thread::sleep(HUB_TICK);
            let step = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                hub.state::<AppCore>().hub_tick();
            }));
            if step.is_err() {
                hub.state::<AppCore>()
                    .log
                    .write("hub: a supervisor step panicked; continuing");
            }
            refresh(&hub);
        });
    if let Err(err) = spawned {
        app.state::<AppCore>()
            .log
            .write(format!("hub thread could not start: {err}"));
    }
}

pub fn open_settings(app: &AppHandle) {
    panel::hide(app);
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
            let handle = app.clone();
            window.on_window_event(move |event| {
                if let tauri::WindowEvent::CloseRequested { .. } = event {
                    handle
                        .state::<AppCore>()
                        .log
                        .write("settings window closed");
                }
            });
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
    open_file(app, &path);
}

/// The hub's own log (`<TAU_DATA_DIR>/logs/tau.log`).
pub fn open_hub_log(app: &AppHandle) {
    match app.state::<AppCore>().hub_log() {
        Some(path) if path.exists() => open_file(app, &path),
        Some(path) => info_dialog(
            app,
            "Hub log",
            &format!("The hub has not written its log yet: {}", path.display()),
        ),
        None => info_dialog(
            app,
            "Hub log",
            "The hub is not set up yet: pick the tau checkout in TauBar's window.",
        ),
    }
}

fn open_file(app: &AppHandle, path: &Path) {
    if let Err(err) = app
        .opener()
        .open_path(path.display().to_string(), None::<&str>)
    {
        app.state::<AppCore>()
            .log
            .write(format!("{} could not be opened: {err}", path.display()));
    }
}

fn error_dialog(app: &AppHandle, title: &str, message: &str) {
    app.dialog()
        .message(message)
        .title(title)
        .kind(MessageDialogKind::Error)
        .show(|_| {});
}

fn info_dialog(app: &AppHandle, title: &str, message: &str) {
    app.dialog()
        .message(message)
        .title(title)
        .kind(MessageDialogKind::Info)
        .show(|_| {});
}
