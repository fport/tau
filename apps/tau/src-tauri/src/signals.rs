//! SIGTERM, SIGINT and SIGHUP quit the app the same way the Quit item does, so `kill <pid>`,
//! Ctrl-C in `bun run tauri dev` and a logout still quit the TUIs of the chat windows, release
//! the sleep assertion, reset `disablesleep` and stop the hub the app started. (A `kill -9`
//! cannot be caught: macOS drops the assertion with the process, and the next start resets
//! `disablesleep`.)

use signal_hook::consts::{SIGHUP, SIGINT, SIGTERM};
use signal_hook::iterator::Signals;
use tauri::AppHandle;

pub fn install(app: AppHandle) {
    let mut signals = match Signals::new([SIGTERM, SIGINT, SIGHUP]) {
        Ok(signals) => signals,
        Err(err) => {
            crate::log(
                &app,
                format!("signal handlers could not be installed: {err}"),
            );
            return;
        }
    };
    let spawned = std::thread::Builder::new()
        .name("tau-app-signals".into())
        .spawn(move || {
            if let Some(signal) = signals.forever().next() {
                crate::log(&app, format!("received signal {signal}; quitting"));
                crate::quit(&app);
            }
        });
    if let Err(err) = spawned {
        eprintln!("tau-app: signal thread could not start: {err}");
    }
}
