//! SIGTERM, SIGINT and SIGHUP quit TauBar the same way the Quit item does, so `kill <pid>`,
//! Ctrl-C in `bun run tauri dev` and a logout still release the sleep assertion, reset
//! `disablesleep` and stop the hub TauBar started. (A `kill -9` cannot be caught: macOS drops
//! the assertion with the process, and the next start resets `disablesleep`.)

use crate::AppCore;
use signal_hook::consts::{SIGHUP, SIGINT, SIGTERM};
use signal_hook::iterator::Signals;
use tauri::{AppHandle, Manager};

pub fn install(app: AppHandle) {
    let mut signals = match Signals::new([SIGTERM, SIGINT, SIGHUP]) {
        Ok(signals) => signals,
        Err(err) => {
            app.state::<AppCore>()
                .log
                .write(format!("signal handlers could not be installed: {err}"));
            return;
        }
    };
    let spawned = std::thread::Builder::new()
        .name("taubar-signals".into())
        .spawn(move || {
            if let Some(signal) = signals.forever().next() {
                let core = app.state::<AppCore>();
                core.log
                    .write(format!("received signal {signal}; quitting"));
                core.shutdown();
                app.exit(0);
            }
        });
    if let Err(err) = spawned {
        eprintln!("taubar: signal thread could not start: {err}");
    }
}
