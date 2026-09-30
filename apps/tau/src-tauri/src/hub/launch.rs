//! How the app starts the hub: `<python> -m tau_core hub run` in `TAU_HOME` with a small,
//! explicit environment, the same command the launchd plist from `tau hub install` runs.
//!
//! The hub is always the direct child (never `uv run …`), so the pid the app watches is the
//! pid in the hub lock, signals reach the hub itself, and `pkill -f "tau_core hub run"` finds
//! it.

use crate::settings::HubSettings;
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

/// `PATH` for the hub when the settings leave it empty: Homebrew and the system directories.
pub const DEFAULT_PATH: &str = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin";

/// The only variables a hub inherits from the app; the rest comes from the settings, so the
/// hub behaves the same whether the app was opened from Finder, at login or from a terminal.
const INHERITED: &[&str] = &[
    "HOME",
    "USER",
    "LOGNAME",
    "TMPDIR",
    "SHELL",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "__CF_USER_TEXT_ENCODING",
];

/// The launchd agent `tau hub install` writes.
pub const LAUNCHD_LABEL: &str = "com.tau.hub";

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Launch {
    pub program: PathBuf,
    pub args: Vec<String>,
    pub cwd: PathBuf,
    pub env: BTreeMap<String, String>,
}

impl Launch {
    /// A command with exactly this environment, stdin closed.
    pub fn command(&self) -> Command {
        let mut command = Command::new(&self.program);
        command
            .args(&self.args)
            .current_dir(&self.cwd)
            .env_clear()
            .envs(&self.env)
            .stdin(Stdio::null());
        command
    }

    /// `python -m tau_core hub run`, for logs and the window.
    pub fn display(&self) -> String {
        let mut parts = vec![self.program.display().to_string()];
        parts.extend(self.args.iter().cloned());
        parts.join(" ")
    }
}

/// The two commands the app runs: the hub itself and `tau hub status --json` (to learn the
/// lock, port and data dir the configuration resolves to).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct HubCommands {
    pub run: Launch,
    pub status: Launch,
}

impl HubCommands {
    /// `inherited` looks up the app's own environment (tests pass a closure).
    pub fn from_settings(
        settings: &HubSettings,
        inherited: impl Fn(&str) -> Option<String>,
    ) -> Result<Self, String> {
        let python = settings
            .python
            .clone()
            .filter(|p| !p.as_os_str().is_empty())
            .ok_or("the hub's Python is not set; pick the tau checkout in tau's settings window")?;
        let tau_home = settings
            .tau_home
            .clone()
            .filter(|p| !p.as_os_str().is_empty())
            .ok_or("TAU_HOME is not set; pick the tau checkout in tau's settings window")?;

        let mut env = BTreeMap::new();
        for name in INHERITED {
            if let Some(value) = inherited(name) {
                env.insert(name.to_string(), value);
            }
        }
        let path = settings
            .path
            .clone()
            .filter(|p| !p.is_empty())
            .unwrap_or_else(|| DEFAULT_PATH.to_string());
        env.insert("PATH".into(), path);
        env.insert("TAU_HOME".into(), tau_home.display().to_string());
        env.insert("TAU_ROLE".into(), "hub".into());
        if let Some(dir) = settings
            .data_dir
            .as_ref()
            .filter(|p| !p.as_os_str().is_empty())
        {
            env.insert("TAU_DATA_DIR".into(), dir.display().to_string());
        }
        if let Some(port) = settings.port {
            env.insert("TAU_HUB_PORT".into(), port.to_string());
        }
        for (key, value) in &settings.env {
            env.insert(key.clone(), value.clone());
        }

        let launch = |args: &[&str]| Launch {
            program: python.clone(),
            args: ["-m", "tau_core", "hub"]
                .iter()
                .chain(args)
                .map(|s| s.to_string())
                .collect(),
            cwd: tau_home.clone(),
            env: env.clone(),
        };
        Ok(Self {
            run: launch(&["run"]),
            status: launch(&["status", "--json"]),
        })
    }

    /// Complain early about paths that cannot work (the spawn error would be vaguer).
    pub fn check_paths(&self) -> Result<(), String> {
        if !self.run.program.is_file() {
            return Err(format!(
                "the hub's Python does not exist: {}",
                self.run.program.display()
            ));
        }
        if !self.run.cwd.is_dir() {
            return Err(format!(
                "TAU_HOME is not a directory: {}",
                self.run.cwd.display()
            ));
        }
        Ok(())
    }
}

/// What an installed `com.tau.hub` launchd agent runs (`~/Library/LaunchAgents/com.tau.hub.plist`).
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct LaunchdAgent {
    pub python: Option<PathBuf>,
    pub tau_home: Option<PathBuf>,
    pub data_dir: Option<PathBuf>,
    pub path: Option<String>,
}

impl LaunchdAgent {
    pub fn plist_path(user_home: &Path) -> PathBuf {
        user_home
            .join("Library/LaunchAgents")
            .join(format!("{LAUNCHD_LABEL}.plist"))
    }

    /// Read the plist; `None` when it is missing or not a launchd plist.
    pub fn read(path: &Path) -> Option<Self> {
        let value = plist::Value::from_file(path).ok()?;
        let dict = value.as_dictionary()?;
        let string = |v: &plist::Value| v.as_string().map(str::to_string);
        let env = dict
            .get("EnvironmentVariables")
            .and_then(plist::Value::as_dictionary);
        let var = |name: &str| env.and_then(|e| e.get(name)).and_then(string);
        Some(Self {
            python: dict
                .get("ProgramArguments")
                .and_then(plist::Value::as_array)
                .and_then(|args| args.first())
                .and_then(string)
                .map(PathBuf::from),
            tau_home: var("TAU_HOME")
                .or_else(|| dict.get("WorkingDirectory").and_then(string))
                .map(PathBuf::from),
            data_dir: var("TAU_DATA_DIR").map(PathBuf::from),
            path: var("PATH"),
        })
    }

    /// Hub settings that start the same hub the agent starts.
    pub fn to_settings(&self) -> HubSettings {
        HubSettings {
            python: self.python.clone(),
            tau_home: self.tau_home.clone(),
            data_dir: self.data_dir.clone(),
            path: self.path.clone(),
            ..HubSettings::default()
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn settings() -> HubSettings {
        HubSettings {
            python: Some("/path/to/tau/.venv/bin/python".into()),
            tau_home: Some("/path/to/tau".into()),
            ..HubSettings::default()
        }
    }

    fn inherit(name: &str) -> Option<String> {
        match name {
            "HOME" => Some("/example/home".into()),
            "LANG" => Some("en_US.UTF-8".into()),
            _ => None,
        }
    }

    #[test]
    fn runs_python_m_tau_core_in_tau_home() {
        let commands = HubCommands::from_settings(&settings(), inherit).unwrap();
        assert_eq!(
            commands.run.program,
            PathBuf::from("/path/to/tau/.venv/bin/python")
        );
        assert_eq!(commands.run.args, ["-m", "tau_core", "hub", "run"]);
        assert_eq!(
            commands.status.args,
            ["-m", "tau_core", "hub", "status", "--json"]
        );
        assert_eq!(commands.run.cwd, PathBuf::from("/path/to/tau"));
        assert_eq!(
            commands.run.display(),
            "/path/to/tau/.venv/bin/python -m tau_core hub run"
        );
    }

    #[test]
    fn builds_a_small_explicit_environment() {
        let env = HubCommands::from_settings(&settings(), inherit)
            .unwrap()
            .run
            .env;
        assert_eq!(env["TAU_HOME"], "/path/to/tau");
        assert_eq!(env["TAU_ROLE"], "hub");
        assert_eq!(env["PATH"], DEFAULT_PATH);
        assert_eq!(env["HOME"], "/example/home");
        assert!(!env.contains_key("TAU_DATA_DIR"));
        assert!(!env.contains_key("TAU_HUB_PORT"));
        assert!(!env.contains_key("USER")); // not set in the parent, not invented
    }

    #[test]
    fn overrides_and_extra_env_win() {
        let mut s = settings();
        s.data_dir = Some("/tmp/tau-data".into());
        s.port = Some(7897);
        s.path = Some("/usr/bin:/bin".into());
        s.env.insert("TELEGRAM_BOT_TOKEN".into(), String::new());
        s.env.insert("TAU_ROLE".into(), "node".into());
        let env = HubCommands::from_settings(&s, inherit).unwrap().run.env;
        assert_eq!(env["TAU_DATA_DIR"], "/tmp/tau-data");
        assert_eq!(env["TAU_HUB_PORT"], "7897");
        assert_eq!(env["PATH"], "/usr/bin:/bin");
        assert_eq!(env["TELEGRAM_BOT_TOKEN"], "");
        assert_eq!(env["TAU_ROLE"], "node");
    }

    #[test]
    fn missing_python_or_home_is_an_error() {
        let mut s = settings();
        s.python = None;
        assert!(HubCommands::from_settings(&s, inherit)
            .unwrap_err()
            .contains("Python"));
        let mut s = settings();
        s.tau_home = Some(PathBuf::new());
        assert!(HubCommands::from_settings(&s, inherit)
            .unwrap_err()
            .contains("TAU_HOME"));
    }

    #[test]
    fn check_paths_names_the_missing_one() {
        let commands = HubCommands::from_settings(&settings(), inherit).unwrap();
        assert!(commands
            .check_paths()
            .unwrap_err()
            .contains("Python does not exist"));
    }

    #[test]
    fn reads_the_launchd_plist_tau_hub_install_writes() {
        let dir = std::env::temp_dir().join(format!("tau-app-plist-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let path = dir.join("com.tau.hub.plist");
        // The committed example in infra/services, as `tau hub install` renders it.
        std::fs::write(
            &path,
            include_str!("../../../../../infra/services/com.tau.hub.plist"),
        )
        .unwrap();
        let agent = LaunchdAgent::read(&path).unwrap();
        assert_eq!(agent.python, Some("/path/to/venv/bin/python".into()));
        assert_eq!(agent.tau_home, Some("/path/to/tau".into()));
        assert_eq!(agent.data_dir, Some("/path/to/tau-data".into()));
        assert_eq!(
            agent.path.as_deref(),
            Some("/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin")
        );
        let settings = agent.to_settings();
        assert_eq!(settings.python, agent.python);
        assert!(settings.port.is_none() && settings.env.is_empty());
        assert!(LaunchdAgent::read(&dir.join("missing.plist")).is_none());
    }
}
