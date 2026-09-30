//! Commands the settings window and the panel call (`invoke` from `src/api.ts`). The hub
//! commands are `async` so they run off the main thread (they can wait on the hub supervisor).

use crate::core::Snapshot;
use crate::settings::{HubSettings, SleepMode};
use crate::{refresh, AppCore};
use serde::Serialize;
use tauri::{AppHandle, Manager, State};

#[derive(Serialize)]
pub struct HubSwitchResult {
    pub snapshot: Snapshot,
    /// Why the switch could not do what it says (a hub TauBar did not start).
    pub message: Option<String>,
}

#[tauri::command]
pub async fn set_run_hub(app: AppHandle, on: bool) -> HubSwitchResult {
    let message = app.state::<AppCore>().set_run_hub(on);
    refresh(&app);
    HubSwitchResult {
        snapshot: app.state::<AppCore>().snapshot(),
        message,
    }
}

/// Save the hub settings; `Err` names what is wrong with them (they are saved anyway).
#[tauri::command]
pub async fn save_hub_settings(app: AppHandle, hub: HubSettings) -> Result<Snapshot, String> {
    let result = app.state::<AppCore>().save_hub_settings(hub);
    refresh(&app);
    result.map(|()| app.state::<AppCore>().snapshot())
}

/// "Lock now" from the window; `Err` says why tau may not be locked. The signed request blocks
/// (up to two attempts of [`crate::hub::guard::LOCK_TIMEOUT`] each), so it runs on a blocking
/// thread instead of holding an async runtime worker.
#[tauri::command]
pub async fn lock_guard(app: AppHandle) -> Result<Snapshot, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let result = app.state::<AppCore>().guard_lock();
        refresh(&app);
        result.map(|()| app.state::<AppCore>().snapshot())
    })
    .await
    .map_err(|err| format!("the lock request stopped: {err}"))?
}

#[tauri::command]
pub fn open_camera_settings(app: AppHandle) {
    crate::open_camera_settings(&app);
}

#[tauri::command]
pub fn open_hub_log(app: AppHandle) {
    crate::open_hub_log(&app);
}

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

#[tauri::command]
pub fn open_settings(app: AppHandle) {
    crate::open_settings(&app);
}

/// The panel's content height, so its window fits it.
#[tauri::command]
pub fn panel_fit(app: AppHandle, height: f64) {
    crate::panel::fit(&app, height);
}

#[tauri::command]
pub fn panel_hide(app: AppHandle) {
    crate::panel::hide(&app);
}
