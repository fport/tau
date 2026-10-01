//! The macOS menu bar of the app: visible while a chat window is open (the app is then a
//! regular app, `chat/mod.rs`); without one the app lives in the menu bar icon, and these items
//! still answer their keys in the settings window.
//!
//! Its items share the ids of the tray menu's (`tray::ids`), and one handler answers both
//! (`crate::on_menu`): Tauri hands every menu event to every menu handler.
//!
//! Keys are ⌘ only, never `CmdOrCtrl`, which would become ctrl+n and ctrl+q on other systems
//! and take the TUI's own new-session and quit keys before xterm.js sees them. There is no
//! Select All: ⌘A goes to xterm.js, which selects the terminal's text (the settings window
//! handles ⌘A in its fields itself).

use crate::tray::ids;
use tauri::menu::{Menu, MenuItemBuilder, SubmenuBuilder};
use tauri::{AppHandle, Runtime};

pub const NEW_CHAT_ACCELERATOR: &str = "Cmd+N";
pub const SETTINGS_ACCELERATOR: &str = "Cmd+,";
pub const QUIT_ACCELERATOR: &str = "Cmd+Q";

/// tau · File · Edit · Window.
pub fn build<R: Runtime>(app: &AppHandle<R>) -> tauri::Result<Menu<R>> {
    let updates = MenuItemBuilder::with_id(ids::UPDATES, "Check for Updates…").build(app)?;
    let settings = MenuItemBuilder::with_id(ids::SETTINGS, "Settings…")
        .accelerator(SETTINGS_ACCELERATOR)
        .build(app)?;
    let wizard = MenuItemBuilder::with_id(ids::WIZARD, "Set up tau…").build(app)?;
    let quit = MenuItemBuilder::with_id(ids::QUIT_ASK, "Quit tau")
        .accelerator(QUIT_ACCELERATOR)
        .build(app)?;
    let new_chat = MenuItemBuilder::with_id(ids::NEW_CHAT, "New Chat Window")
        .accelerator(NEW_CHAT_ACCELERATOR)
        .build(app)?;
    let app_menu = SubmenuBuilder::new(app, "tau")
        .about(None)
        .item(&updates)
        .separator()
        .item(&settings)
        .item(&wizard)
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
        .item(&new_chat)
        .separator()
        .close_window()
        .build()?;
    // Copy and Paste reach xterm.js through the webview's copy and paste events.
    let edit = SubmenuBuilder::new(app, "Edit")
        .undo()
        .redo()
        .separator()
        .cut()
        .copy()
        .paste()
        .build()?;
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn menu_keys_leave_ctrl_to_the_tui() {
        for accelerator in [NEW_CHAT_ACCELERATOR, SETTINGS_ACCELERATOR, QUIT_ACCELERATOR] {
            let modifiers: Vec<String> = accelerator
                .split('+')
                .rev()
                .skip(1)
                .map(str::to_ascii_lowercase)
                .collect();
            assert_eq!(modifiers, ["cmd"], "{accelerator}");
        }
    }

    /// No Select All in the menu: ⌘A must reach xterm.js in a chat window.
    #[test]
    fn select_all_is_not_a_menu_item() {
        let path = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("src/app_menu.rs");
        let src = std::fs::read_to_string(path).unwrap();
        let menu = &src[..src.find("#[cfg(test)]").unwrap()];
        assert!(!menu.contains(concat!(".select", "_all()")));
    }
}
