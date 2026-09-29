// No console window on Windows release builds (TauBar targets macOS; kept for portability).
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    taubar_lib::run()
}
