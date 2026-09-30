// No console window on Windows release builds (tau Desktop targets macOS; kept for portability).
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    tau_desktop_lib::run()
}
