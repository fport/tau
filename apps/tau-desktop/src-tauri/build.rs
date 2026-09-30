//! The app's own commands get ACL permissions (`allow-<command>`), so a window can call only what
//! `capabilities/terminal.json` grants it, and only windows that capability names can call any.

const COMMANDS: &[&str] = &[
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
