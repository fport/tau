//! Commands the settings window calls (`invoke` from `src/api.ts`).

use crate::core::Snapshot;
use crate::settings::SleepMode;
use crate::{refresh, AppCore};
use tauri::{AppHandle, Manager, State};

#[tauri::command]
pub fn snapshot(core: State<'_, AppCore>) -> Snapshot {
    core.snapshot()
}

#[tauri::command]
pub fn set_sleep_mode(app: AppHandle, mode: SleepMode) -> Snapshot {
    app.state::<AppCore>().set_sleep_mode(mode);
    refresh(&app);
    app.state::<AppCore>().snapshot()
}

#[tauri::command]
pub fn set_launch_at_login(app: AppHandle, enabled: bool) -> Result<Snapshot, String> {
    let result = app.state::<AppCore>().set_launch_at_login(enabled);
    refresh(&app);
    result.map(|_| app.state::<AppCore>().snapshot())
}

#[tauri::command]
pub fn open_login_items() {
    crate::login::open_system_settings();
}

#[tauri::command]
pub fn log_tail(core: State<'_, AppCore>, lines: Option<usize>) -> Vec<String> {
    core.log.tail(lines.unwrap_or(40).min(500))
}

#[tauri::command]
pub fn open_log(app: AppHandle) {
    crate::open_log(&app);
}

#[tauri::command]
pub fn quit(app: AppHandle) {
    crate::quit(&app);
}
