// No console window on Windows release builds (the app targets macOS; kept for portability).
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    tau_app_lib::run()
}
