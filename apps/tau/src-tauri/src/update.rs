//! Updates through the Tauri updater (`tauri-plugin-updater`).
//!
//! CI builds every release (`.github/workflows/app.yml`): `tau.app.tar.gz`, signed with the
//! updater key (minisign, bound to the version), and `latest.json`, attached to the GitHub
//! release. The app asks for `latest.json` at the endpoint in `tauri.conf.json`, checks the
//! archive's signature against the public key there, replaces itself and opens again. Every
//! build is signed with the same code-signing identity, so macOS keeps the camera grant.
//!
//! "Check for Updates…" works in any build that has the public key. Release builds (CI sets
//! `TAU_APP_RELEASE=1` at compile time) also look once a minute after the start and then once a
//! day, unless the owner switched that off in the settings window; a check sends GitHub the
//! usual request headers and nothing else.

use crate::AppCore;
use std::sync::Mutex;
use std::time::Duration;
use tauri::{AppHandle, Manager};
use tauri_plugin_dialog::{DialogExt, MessageDialogButtons, MessageDialogKind};
use tauri_plugin_updater::{Update, UpdaterExt};

/// The first automatic check after the start, then the pause between two.
const FIRST_CHECK: Duration = Duration::from_secs(60);
const EVERY: Duration = Duration::from_secs(24 * 60 * 60);

/// Built by CI for a release: the automatic check is on.
pub fn release_build() -> bool {
    option_env!("TAU_APP_RELEASE") == Some("1")
}

/// What the update checks remember during one run.
#[derive(Default)]
pub struct Updates {
    /// The version the automatic check offered last, so it asks once per version and run.
    offered: Mutex<Option<String>>,
    /// A check or an installation is running.
    busy: Mutex<bool>,
}

impl Updates {
    fn first_offer(&self, version: &str) -> bool {
        let mut offered = self.offered.lock().unwrap_or_else(|e| e.into_inner());
        if offered.as_deref() == Some(version) {
            return false;
        }
        *offered = Some(version.to_string());
        true
    }

    /// Take the busy flag; `false` while another check or installation runs.
    fn start(&self) -> bool {
        let mut busy = self.busy.lock().unwrap_or_else(|e| e.into_inner());
        !std::mem::replace(&mut *busy, true)
    }

    fn done(&self) {
        *self.busy.lock().unwrap_or_else(|e| e.into_inner()) = false;
    }
}

/// The updater's public key from `tauri.conf.json`, when one is set.
fn public_key(app: &AppHandle) -> Option<String> {
    app.config()
        .plugins
        .0
        .get("updater")?
        .get("pubkey")?
        .as_str()
        .map(str::trim)
        .filter(|key| !key.is_empty())
        .map(str::to_string)
}

/// Look for an update. `asked`: from "Check for Updates…", which always answers; the automatic
/// check says something only when there is an update.
pub fn check(app: &AppHandle, asked: bool) {
    if public_key(app).is_none() {
        crate::log(
            app,
            "updates: this build has no updater key; nothing to check",
        );
        if asked {
            message(
                app,
                MessageDialogKind::Info,
                "This build of tau cannot update itself: it has no updater key. Release builds \
                 from GitHub have one; a build from the checkout is updated by building it again.",
            );
        }
        return;
    }
    if !app.state::<Updates>().start() {
        if asked {
            message(
                app,
                MessageDialogKind::Info,
                "tau is already looking for an update.",
            );
        }
        return;
    }
    let app = app.clone();
    tauri::async_runtime::spawn(async move {
        let result = match app.updater() {
            Ok(updater) => updater.check().await,
            Err(err) => Err(err),
        };
        app.state::<Updates>().done();
        match result {
            Ok(Some(update)) => offer(&app, update, asked),
            Ok(None) => {
                crate::log(&app, "updates: none");
                if asked {
                    let version = app.package_info().version.to_string();
                    message(
                        &app,
                        MessageDialogKind::Info,
                        &format!("tau {version} is the newest version."),
                    );
                }
            }
            Err(err) => {
                crate::log(&app, format!("updates: the check failed: {err}"));
                if asked {
                    message(
                        &app,
                        MessageDialogKind::Error,
                        &format!("tau could not look for an update: {err}"),
                    );
                }
            }
        }
    });
}

/// Ask whether to install `update` now.
fn offer(app: &AppHandle, update: Update, asked: bool) {
    crate::log(app, format!("updates: tau {} is available", update.version));
    if !asked && !app.state::<Updates>().first_offer(&update.version) {
        return;
    }
    let text = format!(
        "tau {} is available; this is tau {}.\n\nInstall it now? tau quits and opens again: \
         the hub it runs restarts, and open chat windows close.",
        update.version, update.current_version
    );
    let handle = app.clone();
    app.dialog()
        .message(text)
        .title("Update tau")
        .kind(MessageDialogKind::Info)
        .buttons(MessageDialogButtons::OkCancelCustom(
            "Install and Restart".into(),
            "Later".into(),
        ))
        .show(move |install| {
            if install {
                self::install(handle, update);
            }
        });
}

/// Download, check the signature, replace the app, then restart through the app's own quit
/// path (the hub stops, sleep is restored, the TUIs quit).
fn install(app: AppHandle, update: Update) {
    if !app.state::<Updates>().start() {
        return;
    }
    tauri::async_runtime::spawn(async move {
        crate::log(&app, format!("updates: installing tau {}", update.version));
        let result = update.download_and_install(|_, _| {}, || {}).await;
        app.state::<Updates>().done();
        match result {
            Ok(()) => {
                crate::log(&app, "updates: installed; restarting");
                crate::restart(&app);
            }
            Err(err) => {
                crate::log(&app, format!("updates: the installation failed: {err}"));
                message(
                    &app,
                    MessageDialogKind::Error,
                    &format!("The update could not be installed: {err}"),
                );
            }
        }
    });
}

/// Release builds: a check a minute after the start, then once a day, while the setting is on.
pub fn spawn_automatic_checks(app: AppHandle) {
    if !release_build() {
        return;
    }
    let spawned = std::thread::Builder::new()
        .name("tau-app-updates".into())
        .spawn(move || {
            std::thread::sleep(FIRST_CHECK);
            loop {
                if app.state::<AppCore>().settings().check_updates {
                    check(&app, false);
                }
                std::thread::sleep(EVERY);
            }
        });
    if let Err(err) = spawned {
        eprintln!("tau: the update thread could not start: {err}");
    }
}

fn message(app: &AppHandle, kind: MessageDialogKind, text: &str) {
    app.dialog()
        .message(text)
        .title("Update tau")
        .kind(kind)
        .show(|_| {});
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn an_automatic_check_offers_each_version_once() {
        let updates = Updates::default();
        assert!(updates.first_offer("0.5.0"));
        assert!(!updates.first_offer("0.5.0"));
        assert!(updates.first_offer("0.5.1"));
    }

    #[test]
    fn one_check_or_installation_at_a_time() {
        let updates = Updates::default();
        assert!(updates.start());
        assert!(!updates.start());
        updates.done();
        assert!(updates.start());
    }

    /// The committed config points the updater at the GitHub release and binds signatures to
    /// the version; the public key is added by `scripts/make-signing-identity.sh`.
    #[test]
    fn the_updater_reads_latest_json_from_the_release() {
        let path = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("tauri.conf.json");
        let config: serde_json::Value =
            serde_json::from_str(&std::fs::read_to_string(path).unwrap()).unwrap();
        let updater = &config["plugins"]["updater"];
        assert_eq!(
            updater["endpoints"],
            serde_json::json!([
                "https://github.com/fport/tau/releases/latest/download/latest.json"
            ])
        );
        assert_eq!(updater["requireSignedVersion"], true);
        assert!(updater["pubkey"].is_string());
        // Local builds need no updater key; CI turns the artifacts on (`app.yml`).
        assert_eq!(config["bundle"]["createUpdaterArtifacts"], false);
    }
}
