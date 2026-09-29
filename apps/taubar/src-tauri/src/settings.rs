//! What the user chose in TauBar, kept as JSON in TauBar's directory
//! (`~/Library/Application Support/com.tau.taubar/settings.json`, or `$TAUBAR_HOME`).
//!
//! "Launch at login" is not stored here: the login item registration (SMAppService) is the
//! source of truth and the system keeps it across restarts.

use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::fs;
use std::io::{self, Write};
use std::path::{Path, PathBuf};

pub const SETTINGS_FILE: &str = "settings.json";
pub const STATE_FILE: &str = "state.json";

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SleepMode {
    /// The Mac sleeps as usual.
    Normal,
    /// An IOKit `PreventSystemSleep` assertion: no sleep on AC power (like `caffeinate -s`).
    #[default]
    KeepAwakeOnAc,
    /// The assertion plus `pmset -a disablesleep 1` (needs the narrow sudoers rule).
    KeepAwakeLidClosed,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(default)]
pub struct Settings {
    pub sleep_mode: SleepMode,
    /// "Run the hub": TauBar starts and supervises the hub whenever TauBar runs.
    pub run_hub: bool,
    /// How TauBar starts the hub.
    pub hub: HubSettings,
}

impl Default for Settings {
    fn default() -> Self {
        Self {
            sleep_mode: SleepMode::KeepAwakeOnAc,
            run_hub: false,
            hub: HubSettings::default(),
        }
    }
}

/// How TauBar starts the hub: `<python> -m tau_core hub run` in `tau_home` with
/// `TAU_HOME=<tau_home>`, like the launchd plist `tau hub install` renders. Nothing here has a
/// built-in personal default: the first start imports these values from an installed
/// `com.tau.hub` launchd agent, or the user picks a checkout in the window.
#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(default)]
pub struct HubSettings {
    /// A Python that has tau-core installed (a checkout's `.venv/bin/python`).
    pub python: Option<PathBuf>,
    /// `TAU_HOME` (the directory with `tau.toml`) and the hub's working directory.
    pub tau_home: Option<PathBuf>,
    /// `TAU_DATA_DIR`; unset: whatever the config resolves to (`~/.local/share/tau`).
    pub data_dir: Option<PathBuf>,
    /// `TAU_HUB_PORT`; unset: `[hub] control_port` from `tau.toml` (7877).
    pub port: Option<u16>,
    /// `PATH` for the hub; unset: Homebrew and the system directories.
    pub path: Option<String>,
    /// More environment for the hub; wins over everything above.
    pub env: BTreeMap<String, String>,
}

/// What TauBar changed on the system and must undo, kept across a crash of TauBar itself.
#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(default)]
pub struct RuntimeState {
    /// TauBar ran `pmset -a disablesleep 1` and has not reset it yet.
    pub lid_engaged: bool,
    /// The pid of the hub TauBar started and has not seen exit. If TauBar itself dies, the
    /// next TauBar adopts that hub (when it still holds the hub lock) instead of calling it
    /// a stranger.
    pub hub_pid: Option<u32>,
}

/// A JSON file of type `T`, read with defaults and written atomically (temp file + rename).
pub struct JsonFile {
    path: PathBuf,
}

impl JsonFile {
    pub fn new(dir: &Path, name: &str) -> Self {
        Self {
            path: dir.join(name),
        }
    }

    pub fn path(&self) -> &Path {
        &self.path
    }

    /// The stored value, or the default. A file that cannot be parsed is moved aside
    /// (`<name>.bad`) and reported, so one bad edit never keeps TauBar from starting.
    pub fn load<T: Default + for<'de> Deserialize<'de>>(&self) -> (T, Option<String>) {
        let text = match fs::read_to_string(&self.path) {
            Ok(text) => text,
            Err(err) if err.kind() == io::ErrorKind::NotFound => return (T::default(), None),
            Err(err) => {
                return (
                    T::default(),
                    Some(format!("{} could not be read: {err}", self.path.display())),
                )
            }
        };
        match serde_json::from_str(&text) {
            Ok(value) => (value, None),
            Err(err) => {
                let mut bad = self.path.as_os_str().to_owned();
                bad.push(".bad");
                let _ = fs::rename(&self.path, &bad);
                (
                    T::default(),
                    Some(format!(
                        "{} was not valid JSON ({err}); moved to {} and using defaults",
                        self.path.display(),
                        PathBuf::from(bad).display()
                    )),
                )
            }
        }
    }

    pub fn save<T: Serialize>(&self, value: &T) -> io::Result<()> {
        if let Some(parent) = self.path.parent() {
            fs::create_dir_all(parent)?;
        }
        let mut tmp = self.path.as_os_str().to_owned();
        tmp.push(".tmp");
        let tmp = PathBuf::from(tmp);
        {
            let mut file = fs::File::create(&tmp)?;
            let text = serde_json::to_string_pretty(value).map_err(io::Error::other)?;
            file.write_all(text.as_bytes())?;
            file.write_all(b"\n")?;
            file.sync_all()?;
        }
        fs::rename(&tmp, &self.path)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn tmpdir(name: &str) -> PathBuf {
        let dir =
            std::env::temp_dir().join(format!("taubar-settings-{name}-{}", std::process::id()));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).unwrap();
        dir
    }

    #[test]
    fn defaults_keep_awake_on_ac_and_leave_the_hub_off() {
        let settings = Settings::default();
        assert_eq!(settings.sleep_mode, SleepMode::KeepAwakeOnAc);
        assert!(!settings.run_hub);
        assert_eq!(settings.hub, HubSettings::default());
        let parsed: Settings = serde_json::from_str("{}").unwrap();
        assert_eq!(parsed, settings);
        // A 024-era file (sleep mode only) still loads.
        let old: Settings = serde_json::from_str(r#"{"sleep_mode": "normal"}"#).unwrap();
        assert_eq!(old.sleep_mode, SleepMode::Normal);
        assert!(!old.run_hub);
    }

    #[test]
    fn sleep_modes_have_stable_names() {
        let names: Vec<String> = [
            SleepMode::Normal,
            SleepMode::KeepAwakeOnAc,
            SleepMode::KeepAwakeLidClosed,
        ]
        .iter()
        .map(|m| serde_json::to_string(m).unwrap())
        .collect();
        assert_eq!(
            names,
            [
                "\"normal\"",
                "\"keep_awake_on_ac\"",
                "\"keep_awake_lid_closed\""
            ]
        );
    }

    #[test]
    fn round_trip_and_missing_file() {
        let dir = tmpdir("roundtrip");
        let file = JsonFile::new(&dir, SETTINGS_FILE);
        let (loaded, warning) = file.load::<Settings>();
        assert_eq!(loaded, Settings::default());
        assert!(warning.is_none());

        let chosen = Settings {
            sleep_mode: SleepMode::Normal,
            run_hub: true,
            hub: HubSettings {
                python: Some("/path/to/tau/.venv/bin/python".into()),
                tau_home: Some("/path/to/tau".into()),
                port: Some(7897),
                env: [("TELEGRAM_BOT_TOKEN".to_string(), String::new())].into(),
                ..HubSettings::default()
            },
        };
        file.save(&chosen).unwrap();
        let (loaded, warning) = file.load::<Settings>();
        assert_eq!(loaded, chosen);
        assert!(warning.is_none());
    }

    #[test]
    fn broken_file_is_moved_aside() {
        let dir = tmpdir("broken");
        let file = JsonFile::new(&dir, STATE_FILE);
        fs::write(file.path(), "{not json").unwrap();
        let (loaded, warning) = file.load::<RuntimeState>();
        assert_eq!(loaded, RuntimeState::default());
        assert!(warning.unwrap().contains("not valid JSON"));
        assert!(dir.join("state.json.bad").is_file());
        assert!(!file.path().exists());
    }
}
