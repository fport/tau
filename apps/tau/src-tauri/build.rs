//! Every command of the app gets an ACL permission (`allow-<command>`), so a window can call
//! only what its capability grants it: the settings window and the panel get the hub, sleep
//! and login commands (`capabilities/settings.json`, `panel.json`), a chat window only its own
//! PTY, the first-run folder choice and links (`capabilities/chat.json`). A chat page can never
//! change how the hub is started, which would run a program under the app's camera grant.

const COMMANDS: &[&str] = &[
    // The settings window and the panel (`src/commands.rs`).
    "snapshot",
    "set_sleep_mode",
    "set_launch_at_login",
    "open_login_items",
    "log_tail",
    "open_log",
    "quit",
    "set_run_hub",
    "save_hub_settings",
    "set_check_updates",
    "open_hub_log",
    "lock_guard",
    "open_camera_settings",
    "open_settings",
    "new_chat",
    "check_updates",
    "panel_fit",
    "panel_hide",
    // Chat windows (`src/chat/commands.rs`).
    "home_status",
    "choose_home",
    "pty_start",
    "pty_write",
    "pty_resize",
    "open_link",
];

fn main() {
    tauri_build::try_build(
        tauri_build::Attributes::new()
            .app_manifest(tauri_build::AppManifest::new().commands(COMMANDS)),
    )
    .expect("tauri-build failed");
}
