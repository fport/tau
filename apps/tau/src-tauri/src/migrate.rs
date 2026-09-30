//! The first start of the tau app on a Mac that ran TauBar or tau Desktop (roadmap 170).
//!
//! The app has a new bundle id, `com.tau.app`, and with it a new config directory, so the
//! choices made in the two old apps are taken over once: TauBar's `settings.json` (sleep mode,
//! "Run the hub" and how the hub is started) and tau Desktop's folder for its windows. Only
//! when the app has no file of its own yet; the old files are read and never written, moved or
//! removed. TauBar's `state.json` is not taken: the pid of its hub and its `disablesleep` belong
//! to TauBar, which undoes them itself when it quits.

use crate::chat::home::{self as chat_home, ChatSettings};
use crate::settings::{JsonFile, Settings, SETTINGS_FILE};
use serde::de::DeserializeOwned;
use std::fs;
use std::path::{Path, PathBuf};

/// TauBar's bundle id (roadmap 024–166).
pub const TAUBAR_ID: &str = "com.tau.taubar";
/// tau Desktop's bundle id (roadmap 116).
pub const DESKTOP_ID: &str = "com.tau.desktop";

/// An old app's `settings.json`: `~/Library/Application Support/<bundle id>/settings.json`.
pub fn legacy_settings(user_home: &Path, bundle_id: &str) -> PathBuf {
    user_home
        .join("Library")
        .join("Application Support")
        .join(bundle_id)
        .join("settings.json")
}

/// Read a JSON file without touching it: a missing, unreadable or broken file is `None`
/// (unlike [`JsonFile::load`], which moves a broken file aside).
fn read<T: DeserializeOwned>(path: &Path) -> Result<Option<T>, String> {
    let text = match fs::read_to_string(path) {
        Ok(text) => text,
        Err(err) if err.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(err) => return Err(format!("{} could not be read: {err}", path.display())),
    };
    serde_json::from_str(&text).map(Some).map_err(|err| {
        format!(
            "{} is not valid JSON ({err}); not taken over",
            path.display()
        )
    })
}

/// Take TauBar's and tau Desktop's settings over into `config`, each only when the app has no
/// file of its own. Returns one line per thing done or skipped, for the app's log.
pub fn import(config: &Path, user_home: &Path) -> Vec<String> {
    let mut report = Vec::new();

    let settings = JsonFile::new(config, SETTINGS_FILE);
    if !settings.path().exists() {
        let old = legacy_settings(user_home, TAUBAR_ID);
        match read::<Settings>(&old) {
            Ok(Some(taken)) => match settings.save(&taken) {
                Ok(()) => report.push(format!(
                    "TauBar's settings taken over from {}",
                    old.display()
                )),
                Err(err) => report.push(format!(
                    "TauBar's settings could not be taken over into {}: {err}",
                    settings.path().display()
                )),
            },
            Ok(None) => {}
            Err(problem) => report.push(problem),
        }
    }

    let chat = config.join(chat_home::SETTINGS_FILE);
    if !chat.exists() {
        let old = legacy_settings(user_home, DESKTOP_ID);
        match read::<ChatSettings>(&old) {
            Ok(Some(taken)) if taken.tau_home.is_some() => match taken.save(&chat) {
                Ok(()) => report.push(format!(
                    "tau Desktop's folder taken over from {}",
                    old.display()
                )),
                Err(err) => report.push(format!(
                    "tau Desktop's folder could not be taken over into {}: {err}",
                    chat.display()
                )),
            },
            Ok(_) => {}
            Err(problem) => report.push(problem),
        }
    }
    report
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::settings::SleepMode;

    fn tmpdir(name: &str) -> PathBuf {
        let dir =
            std::env::temp_dir().join(format!("tau-app-migrate-{name}-{}", std::process::id()));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).unwrap();
        dir
    }

    fn write(path: &Path, text: &str) {
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        fs::write(path, text).unwrap();
    }

    #[test]
    fn the_old_apps_live_under_their_bundle_ids() {
        let home = Path::new("/path/to/home");
        assert_eq!(
            legacy_settings(home, TAUBAR_ID),
            PathBuf::from("/path/to/home/Library/Application Support/com.tau.taubar/settings.json")
        );
        assert!(legacy_settings(home, DESKTOP_ID).ends_with("com.tau.desktop/settings.json"));
    }

    #[test]
    fn takes_taubar_and_tau_desktop_over_once() {
        let dir = tmpdir("both");
        let home = dir.join("home");
        let config = dir.join("config");
        let taubar = legacy_settings(&home, TAUBAR_ID);
        let desktop = legacy_settings(&home, DESKTOP_ID);
        write(
            &taubar,
            r#"{"sleep_mode": "normal", "run_hub": true,
                "hub": {"python": "/path/to/tau/.venv/bin/python", "tau_home": "/path/to/tau"}}"#,
        );
        write(&desktop, r#"{"tau_home": "/path/to/tau"}"#);
        let taubar_before = fs::read(&taubar).unwrap();

        let report = import(&config, &home);
        assert_eq!(report.len(), 2, "{report:?}");
        let (settings, problem) = JsonFile::new(&config, SETTINGS_FILE).load::<Settings>();
        assert!(problem.is_none());
        assert_eq!(settings.sleep_mode, SleepMode::Normal);
        assert!(settings.run_hub);
        assert_eq!(settings.hub.tau_home, Some(PathBuf::from("/path/to/tau")));
        assert!(settings.check_updates);
        assert_eq!(
            ChatSettings::load(&config.join(chat_home::SETTINGS_FILE)).tau_home,
            Some(PathBuf::from("/path/to/tau"))
        );
        assert_eq!(
            fs::read(&taubar).unwrap(),
            taubar_before,
            "TauBar's file is never written"
        );

        // The app's own files win from then on: a second start takes nothing over.
        write(&taubar, r#"{"sleep_mode": "keep_awake_lid_closed"}"#);
        assert!(import(&config, &home).is_empty());
        let (settings, _) = JsonFile::new(&config, SETTINGS_FILE).load::<Settings>();
        assert_eq!(settings.sleep_mode, SleepMode::Normal);
    }

    #[test]
    fn nothing_to_take_over_on_a_new_mac() {
        let dir = tmpdir("none");
        assert!(import(&dir.join("config"), &dir.join("home")).is_empty());
        assert!(!dir.join("config").join(SETTINGS_FILE).exists());
        assert!(!dir.join("config").join(chat_home::SETTINGS_FILE).exists());
    }

    #[test]
    fn a_broken_old_file_is_reported_and_left_alone() {
        let dir = tmpdir("broken");
        let home = dir.join("home");
        let taubar = legacy_settings(&home, TAUBAR_ID);
        write(&taubar, "{not json");
        let report = import(&dir.join("config"), &home);
        assert_eq!(report.len(), 1);
        assert!(report[0].contains("not valid JSON"), "{report:?}");
        assert_eq!(fs::read_to_string(&taubar).unwrap(), "{not json");
        assert!(!dir.join("config").join(SETTINGS_FILE).exists());
    }
}
