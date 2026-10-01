//! tau, the Mac app (ADR 0014 §3, roadmap 170): what TauBar and tau Desktop were, in one app.
//!
//! - **The menu bar icon.** A left click opens the panel (React, `panel.rs`) with the hub
//!   switch and its status, the owner guard's state, the sleep modes, "Launch at login" and
//!   "New Chat Window"; the right click shows the same as a native menu (`tray.rs`). A settings
//!   window (React) opens from either.
//! - **The hub's supervisor** (`hub/`): with "Run the hub" on, the app starts `tau hub run` as
//!   its child and restarts it after a crash; the camera grant the hub's guard needs belongs to
//!   the app (ADR 0008).
//! - **Chat windows** (`chat/`): `tau tui` in a PTY with xterm.js, one per window.
//! - **The setup wizard** (`wizard/`, roadmap 171): on the first start and from "Set up tau…",
//!   it finds or installs tau and drives `tau setup`'s JSON protocol, asking macOS for the
//!   permissions of the chosen features only (`permissions.rs`).
//! - **Updates** (`update.rs`) from the public downloads, signed for the Tauri updater.
//!
//! The app starts without a Dock icon; it has one, and the menu bar (`app_menu.rs`), while a
//! chat window is open. Every webview denies every permission request (`webview.rs`), and each
//! window may call only the commands its capability grants (`capabilities/`). See
//! `apps/tau/README.md`.

mod app_menu;
pub mod chat;
mod commands;
pub mod core;
pub mod eventlog;
pub mod hub;
pub mod login;
pub mod migrate;
pub mod panel;
pub mod permissions;
pub mod settings;
mod signals;
pub mod sleep;
pub mod tray;
pub mod update;
pub mod webview;
pub mod wizard;

use crate::chat::Chats;
use crate::core::{Core, Dirs};
use crate::hub::guard::CAMERA_SETTINGS_URL;
use crate::hub::supervisor::SystemProbe;
use crate::settings::{SleepMode, SETTINGS_FILE};
use crate::sleep::SystemPower;
use crate::tray::{ids, TrayMenu};
use std::path::{Path, PathBuf};
use std::time::Duration;
use tauri::{AppHandle, Emitter, Manager, RunEvent, WebviewUrl, WebviewWindowBuilder, Wry};
use tauri_plugin_dialog::{DialogExt, MessageDialogButtons, MessageDialogKind};
use tauri_plugin_opener::OpenerExt;

pub type AppCore = Core<SystemPower, SystemProbe>;

/// Emitted to the settings window and the panel after every change.
pub const SNAPSHOT_EVENT: &str = "tau-app://snapshot";
/// Where the app keeps its settings, state and log instead, when set (tests, a second copy).
pub const HOME_VAR: &str = "TAU_APP_HOME";
const SETTINGS_WINDOW: &str = "settings";
/// Login item and sudoers rule checks.
const TICK: Duration = Duration::from_secs(5);
/// The hub supervisor's step.
const HUB_TICK: Duration = Duration::from_secs(1);

pub fn run() {
    let app = tauri::Builder::default()
        // The app holds the camera grant for its hub; no webview may use it (ADR 0008).
        .on_permission_request(|_, kind| webview::permission(kind))
        // One tau app per user (roadmap 091). A second launch, from Spotlight, Finder,
        // `open -n` or the build folder of a checkout, hands over to the running app and exits
        // before it touches the hub or the sleep assertion; the running one shows a window.
        // Registered first, as the plugin requires.
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            show(app);
        }))
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .menu(app_menu::build)
        // The one menu handler: the tray menu's clicks and the app menu's (shared ids).
        .on_menu_event(|app, event| on_menu(app, event.id().as_ref()))
        .on_window_event(|window, event| {
            chat::on_window_event(window, event);
            wizard::on_window_event(window, event);
        })
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
            commands::set_check_updates,
            commands::open_hub_log,
            commands::lock_guard,
            commands::open_camera_settings,
            commands::open_settings,
            commands::new_chat,
            commands::check_updates,
            commands::panel_fit,
            commands::panel_hide,
            chat::commands::home_status,
            chat::commands::choose_home,
            chat::commands::pty_start,
            chat::commands::pty_write,
            chat::commands::pty_resize,
            chat::commands::open_link,
            wizard::commands::wizard_discover,
            wizard::commands::wizard_status,
            wizard::commands::wizard_run,
            wizard::commands::wizard_install,
            wizard::commands::wizard_cancel,
            wizard::commands::wizard_pty_start,
            wizard::commands::wizard_permission,
            wizard::commands::wizard_permission_settings,
            wizard::commands::open_wizard,
        ])
        .setup(|app| {
            // The menu bar only, until a chat window opens (Info.plist also sets LSUIElement).
            #[cfg(target_os = "macos")]
            app.set_activation_policy(tauri::ActivationPolicy::Accessory);
            let user_home = app.path().home_dir()?;
            let (dirs, own_home) = resolve_dirs(app.handle())?;
            // The very first start of the app: it opens its window once, also after taking
            // TauBar's settings over, so the owner sees the new app.
            let fresh = !dirs.config.join(SETTINGS_FILE).exists();
            let imported = if own_home {
                Vec::new()
            } else {
                migrate::import(&dirs.config, &user_home)
            };
            let probe = SystemProbe {
                user_home: user_home.clone(),
            };
            let version = app.package_info().version.to_string();
            let core = AppCore::start(
                dirs.clone(),
                version,
                SystemPower::new(),
                probe,
                user_home.clone(),
            );
            for line in imported {
                core.log.write(line);
            }
            let first_run = fresh || core.first_run;
            app.manage(core);
            app.manage(Chats::new(
                dirs.config.join(chat::home::SETTINGS_FILE),
                user_home,
            ));
            app.manage(update::Updates::default());
            app.manage(wizard::Wizard::default());
            let menu = TrayMenu::build(app.handle(), panel::toggle)?;
            app.manage(menu);
            app.manage(panel::PanelState::default());
            if let Err(err) = panel::build(app.handle()) {
                // The menu still has everything; let the left click show it too.
                log(
                    app.handle(),
                    format!("the panel could not be created: {err}"),
                );
                if let Some(tray) = app.tray_by_id(tray::TRAY_ID) {
                    let _ = tray.set_show_menu_on_left_click(true);
                }
            }
            refresh(app.handle());
            signals::install(app.handle().clone());
            spawn_ticker(app.handle().clone());
            spawn_hub_thread(app.handle().clone());
            update::spawn_automatic_checks(app.handle().clone());
            // The first start shows the setup wizard (roadmap 171): it finds or installs tau
            // and sets it up; the settings window stays one click away.
            if first_run {
                wizard::open(app.handle());
            }
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("tau could not start");

    app.run(|app, event| match event {
        // Closing a window, the last chat window included, must not quit a menu bar app; only
        // Quit (a code) does.
        RunEvent::ExitRequested {
            code: None, api, ..
        } => api.prevent_exit(),
        // Whatever path led here, no TUI outlives the app, the hub stops and sleep is restored.
        RunEvent::Exit => shutdown(app),
        // Opening tau.app again (Finder, Spotlight, the Dock, `open -a tau`) shows a window:
        // the way in when macOS hides the menu bar icon behind the notch.
        #[cfg(target_os = "macos")]
        RunEvent::Reopen {
            has_visible_windows: false,
            ..
        } => show(app),
        _ => {}
    });
}

/// A line in the app's log, from any thread (before the core exists: stderr).
pub fn log(app: &AppHandle, line: impl AsRef<str>) {
    match app.try_state::<AppCore>() {
        Some(core) => core.log.write(line),
        None => eprintln!("tau-app: {}", line.as_ref()),
    }
}

/// Undo what the app holds: the chat windows' TUIs quit (ctrl+q, then a kill after the grace
/// period), the hub the app started stops, normal sleep comes back. Idempotent.
fn shutdown(app: &AppHandle) {
    if let Some(chats) = app.try_state::<Chats>() {
        chats.shutdown_all();
    }
    if let Some(core) = app.try_state::<AppCore>() {
        core.shutdown();
    }
}

/// Quit the app: windows hide at once, [`shutdown`] runs off the main thread, then the app
/// exits. Callable from any thread, more than once.
pub fn quit(app: &AppHandle) {
    leave(app, false);
}

/// The same as [`quit`], then the app opens again (after an update).
pub fn restart(app: &AppHandle) {
    leave(app, true);
}

fn leave(app: &AppHandle, restart: bool) {
    if !app.state::<Chats>().begin_quit() {
        return;
    }
    panel::hide(app);
    for window in app.webview_windows().values() {
        let _ = window.hide();
    }
    let app = app.clone();
    let spawned = std::thread::Builder::new()
        .name("tau-app-quit".into())
        .spawn(move || {
            shutdown(&app);
            if restart {
                app.request_restart();
            } else {
                app.exit(0);
            }
        });
    if let Err(err) = spawned {
        eprintln!("tau-app: quit thread could not start: {err}");
    }
}

/// ⌘Q from the app menu (a chat window in front): quitting also stops the hub and lets the Mac
/// sleep, which the owner may not expect from closing a chat, so ask first while the app runs
/// the hub.
fn ask_quit(app: &AppHandle) {
    if !app.state::<AppCore>().hub_switch() {
        quit(app);
        return;
    }
    let handle = app.clone();
    app.dialog()
        .message(
            "Quitting tau also stops the hub it runs on this Mac: Telegram, routines and the \
             guard stop until tau opens again, and the Mac sleeps as usual.\n\nTo keep tau \
             running in the menu bar, close the chat windows instead (⌘W).",
        )
        .title("Quit tau?")
        .kind(MessageDialogKind::Warning)
        .buttons(MessageDialogButtons::OkCancelCustom(
            "Quit tau".into(),
            "Cancel".into(),
        ))
        .show(move |confirmed| {
            if confirmed {
                quit(&handle);
            }
        });
}

/// `$TAU_APP_HOME` when set (`true`: everything in one directory, nothing taken over from the
/// old apps), else the app's config and log directories.
fn resolve_dirs(app: &AppHandle) -> Result<(Dirs, bool), Box<dyn std::error::Error>> {
    if let Some(home) = std::env::var_os(HOME_VAR).filter(|v| !v.is_empty()) {
        return Ok((Dirs::from_home(PathBuf::from(home)), true));
    }
    let dirs = Dirs {
        config: app.path().app_config_dir()?,
        logs: app.path().app_log_dir()?,
    };
    Ok((dirs, false))
}

/// Opening the app again, or a second launch: the window in front comes forward; with none,
/// a chat window, or the setup wizard while tau is not set up yet (no tau for the hub and none
/// for the chat windows).
fn show(app: &AppHandle) {
    let front = app.webview_windows().into_iter().find(|(label, window)| {
        label != panel::PANEL_WINDOW && window.is_visible().unwrap_or(false)
    });
    if let Some((_, window)) = front {
        let _ = window.unminimize();
        let _ = window.set_focus();
        return;
    }
    let hub_checkout = app.state::<AppCore>().settings().hub.tau_home.is_some();
    if hub_checkout || app.state::<Chats>().has_home() {
        chat::open_window(app);
    } else {
        wizard::open(app);
    }
}

/// Push the current state to the menu, the panel and the settings window. Callable from any
/// thread.
///
/// The menu is changed on the main thread only. Off it, every Tauri menu call posts a task to
/// the event loop and blocks until the main thread has run it, so the hub thread (which
/// refreshes every second) must never make one: holding any lock across such a call deadlocks
/// against a main-thread handler waiting for that lock, and the event loop freezes for good.
/// `run_on_main_thread` never blocks: on the main thread it runs the update in place
/// (tauri-runtime-wry's `send_user_message`), elsewhere it queues it for the event loop.
pub fn refresh(app: &AppHandle) {
    let snapshot = app.state::<AppCore>().snapshot();
    let _ = app.emit(SNAPSHOT_EVENT, &snapshot);
    let handle = app.clone();
    // An error means the event loop is gone (the app is quitting): nothing to show then.
    let _ = app.run_on_main_thread(move || {
        if let Some(menu) = handle.try_state::<TrayMenu<Wry>>() {
            menu.update(&handle, &snapshot);
        }
    });
}

/// Turn "Run the hub" on or off, off the main thread (it can wait on the hub supervisor), and
/// explain when the app cannot do what the switch says.
pub fn toggle_hub(app: &AppHandle, on: bool) {
    let app = app.clone();
    let spawned = std::thread::Builder::new()
        .name("tau-app-hub-switch".into())
        .spawn(move || {
            let message = app.state::<AppCore>().set_run_hub(on);
            refresh(&app);
            if let Some(message) = message {
                info_dialog(&app, "Run the hub", &message);
            }
        });
    if let Err(err) = spawned {
        eprintln!("tau-app: hub switch thread could not start: {err}");
    }
}

/// Every menu click, from the tray menu and the app menu.
fn on_menu(app: &AppHandle, id: &str) {
    let core = app.state::<AppCore>();
    match id {
        ids::HUB_RUN => {
            toggle_hub(app, !core.hub_switch());
            return;
        }
        ids::HUB_LOG => open_hub_log(app),
        ids::GUARD_LOCK => {
            lock_guard(app);
            return;
        }
        ids::GUARD_CAMERA => open_camera_settings(app),
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
                         for the tau.app bundle (not for `bun run tauri dev`)."
                    ),
                );
            }
        }
        ids::NEW_CHAT => {
            chat::open_window(app);
            return;
        }
        ids::SETTINGS => open_settings(app),
        ids::WIZARD => {
            wizard::open(app);
            return;
        }
        ids::UPDATES => {
            update::check(app, true);
            return;
        }
        ids::OPEN_LOG => open_log(app),
        ids::QUIT => {
            quit(app);
            return;
        }
        ids::QUIT_ASK => {
            ask_quit(app);
            return;
        }
        _ => return,
    }
    refresh(app);
}

/// "Lock now" from the menu: the signed request runs off the main thread; a lock the hub did
/// not confirm is shown, because the owner expects tau to be locked.
fn lock_guard(app: &AppHandle) {
    let worker = app.clone();
    let spawned = std::thread::Builder::new()
        .name("tau-app-guard-lock".into())
        .spawn(move || {
            let result = worker.state::<AppCore>().guard_lock();
            refresh(&worker);
            if let Err(err) = result {
                error_dialog(
                    &worker,
                    "Lock now",
                    &format!("tau may not be locked: {err}"),
                );
            }
        });
    if let Err(err) = spawned {
        log(app, format!("guard lock thread could not start: {err}"));
    }
}

/// System Settings → Privacy & Security → Camera, where the app's camera grant lives.
pub fn open_camera_settings(app: &AppHandle) {
    if let Err(err) = app.opener().open_url(CAMERA_SETTINGS_URL, None::<&str>) {
        log(
            app,
            format!("the camera settings could not be opened: {err}"),
        );
    }
}

/// Every few seconds: pick up changes made outside the app (login item toggled in System
/// Settings, sudoers rule installed or removed).
fn spawn_ticker(app: AppHandle) {
    let ticker = app.clone();
    let spawned = std::thread::Builder::new()
        .name("tau-app-ticker".into())
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
        log(&app, format!("ticker thread could not start: {err}"));
    }
}

/// Every second: one hub supervisor step (reap, restart, poll `/health` and `/status`), then
/// refresh the menu and the window. A panic in a step is logged and the loop goes on, so
/// supervision never silently stops.
fn spawn_hub_thread(app: AppHandle) {
    let hub = app.clone();
    let spawned = std::thread::Builder::new()
        .name("tau-app-hub".into())
        .spawn(move || loop {
            std::thread::sleep(HUB_TICK);
            let step = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                hub.state::<AppCore>().hub_tick();
            }));
            if step.is_err() {
                log(&hub, "hub: a supervisor step panicked; continuing");
            }
            refresh(&hub);
        });
    if let Err(err) = spawned {
        log(&app, format!("hub thread could not start: {err}"));
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
            .title("tau Settings")
            .inner_size(560.0, 660.0)
            .min_inner_size(460.0, 420.0)
            .center()
            .focused(true)
            .on_permission_request(|_, kind| webview::permission(kind))
            .build();
    match built {
        Ok(window) => {
            let _ = window.set_focus();
            let handle = app.clone();
            window.on_window_event(move |event| {
                if let tauri::WindowEvent::CloseRequested { .. } = event {
                    log(&handle, "settings window closed");
                }
            });
        }
        Err(err) => log(app, format!("the settings window could not open: {err}")),
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
            "The hub is not set up yet: pick the tau checkout in tau's settings window.",
        ),
    }
}

fn open_file(app: &AppHandle, path: &Path) {
    if let Err(err) = app
        .opener()
        .open_path(path.display().to_string(), None::<&str>)
    {
        log(
            app,
            format!("{} could not be opened: {err}", path.display()),
        );
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
