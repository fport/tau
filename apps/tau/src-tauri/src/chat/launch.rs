//! How a chat window starts tau: `<TAU_HOME>/.venv/bin/python -m tau_core tui` in `TAU_HOME`,
//! with a small, explicit environment built like the hub's (`hub/launch.rs`).
//!
//! A GUI app gets launchd's minimal environment (no `TERM`, no locale, a short `PATH`), and one
//! opened from a terminal gets that terminal's whole environment. Neither is assumed: the child
//! starts from an empty environment, inherits a fixed allowlist and gets the terminal variables
//! xterm.js needs, so the TUI behaves the same however the app was opened.
//!
//! The Python is always derived from `TAU_HOME`, never configured: an editable interpreter path
//! would let anyone at the Mac run an arbitrary executable through the app.

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

/// `PATH` for the TUI: Homebrew and the system directories (the default for the hub, `hub/launch.rs`).
pub const DEFAULT_PATH: &str = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin";

/// The only variables the TUI inherits from the app (the hub's list, minus the locale, which
/// is set below).
const INHERITED: &[&str] = &[
    "HOME",
    "USER",
    "LOGNAME",
    "TMPDIR",
    "SHELL",
    "__CF_USER_TEXT_ENCODING",
];

/// Locale overrides that win over `LANG`: inherited only when they keep UTF-8, so a stray
/// `LC_ALL=C` can never turn the TUI's output into mojibake.
const LOCALE_OVERRIDES: &[&str] = &["LC_ALL", "LC_CTYPE"];

/// What xterm.js is: a 256-colour, truecolor terminal that speaks UTF-8.
pub const TERMINAL_ENV: &[(&str, &str)] = &[
    ("TERM", "xterm-256color"),
    ("COLORTERM", "truecolor"),
    ("LANG", "en_US.UTF-8"),
];

/// The interpreter of a tau checkout: `<TAU_HOME>/.venv/bin/python` (what `uv sync` creates).
pub fn venv_python(home: &Path) -> PathBuf {
    home.join(".venv").join("bin").join("python")
}

/// A process to start: program, arguments, working directory and its complete environment.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Launch {
    pub program: PathBuf,
    pub args: Vec<String>,
    pub cwd: PathBuf,
    pub env: BTreeMap<String, String>,
}

impl Launch {
    /// `python -m tau_core tui`: what every window runs in its PTY.
    pub fn tui(home: &Path, inherited: impl Fn(&str) -> Option<String>) -> Self {
        Self::tau(home, &["tui"], inherited)
    }

    /// `python -m tau_core version`: the check a folder must pass before a chat window uses it.
    pub fn version_check(home: &Path, inherited: impl Fn(&str) -> Option<String>) -> Self {
        Self::tau(home, &["version"], inherited)
    }

    fn tau(home: &Path, args: &[&str], inherited: impl Fn(&str) -> Option<String>) -> Self {
        Self {
            program: venv_python(home),
            args: ["-m", "tau_core"]
                .iter()
                .chain(args)
                .map(|s| s.to_string())
                .collect(),
            cwd: home.to_path_buf(),
            env: build_env(home, inherited),
        }
    }

    /// The command for a PTY: exactly this environment (`env_clear` first) and working directory.
    pub fn pty_command(&self) -> portable_pty::CommandBuilder {
        let mut command = portable_pty::CommandBuilder::new(&self.program);
        command.args(&self.args);
        command.cwd(&self.cwd);
        command.env_clear();
        for (key, value) in &self.env {
            command.env(key, value);
        }
        command
    }

    /// The same process without a PTY (stdin closed, output captured): for the version check.
    pub fn command(&self) -> Command {
        let mut command = Command::new(&self.program);
        command
            .args(&self.args)
            .current_dir(&self.cwd)
            .env_clear()
            .envs(&self.env)
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());
        command
    }

    /// `python -m tau_core tui`, for messages.
    pub fn display(&self) -> String {
        let mut parts = vec![self.program.display().to_string()];
        parts.extend(self.args.iter().cloned());
        parts.join(" ")
    }
}

/// The TUI's environment. `inherited` looks up the app's own environment (tests pass a closure).
pub fn build_env(
    home: &Path,
    inherited: impl Fn(&str) -> Option<String>,
) -> BTreeMap<String, String> {
    let mut env = BTreeMap::new();
    for name in INHERITED {
        if let Some(value) = inherited(name) {
            env.insert(name.to_string(), value);
        }
    }
    for name in LOCALE_OVERRIDES {
        if let Some(value) = inherited(name).filter(|v| is_utf8_locale(v)) {
            env.insert(name.to_string(), value);
        }
    }
    env.insert("PATH".into(), DEFAULT_PATH.into());
    env.insert("TAU_HOME".into(), home.display().to_string());
    for (key, value) in TERMINAL_ENV {
        env.insert(key.to_string(), value.to_string());
    }
    env
}

/// `en_US.UTF-8`, `tr_TR.utf8`, `UTF-8` (macOS's bare `LC_CTYPE`): yes. `C`, `POSIX`, `tr_TR`: no.
fn is_utf8_locale(value: &str) -> bool {
    let lower = value.to_ascii_lowercase();
    lower.contains("utf-8") || lower.contains("utf8")
}

#[cfg(test)]
mod tests {
    use super::*;

    fn inherit(name: &str) -> Option<String> {
        match name {
            "HOME" => Some("/example/home".into()),
            "SHELL" => Some("/bin/zsh".into()),
            "TERM" => Some("dumb".into()),
            "PATH" => Some("/usr/bin".into()),
            "TAU_LANG" => Some("tr".into()),
            "OPENAI_API_KEY" => Some("sk-example".into()),
            "LANG" => Some("C".into()),
            _ => None,
        }
    }

    #[test]
    fn runs_the_checkout_python_m_tau_core_tui_in_tau_home() {
        let launch = Launch::tui(Path::new("/path/to/tau"), inherit);
        assert_eq!(
            launch.program,
            PathBuf::from("/path/to/tau/.venv/bin/python")
        );
        assert_eq!(launch.args, ["-m", "tau_core", "tui"]);
        assert_eq!(launch.cwd, PathBuf::from("/path/to/tau"));
        assert_eq!(
            launch.display(),
            "/path/to/tau/.venv/bin/python -m tau_core tui"
        );
        let check = Launch::version_check(Path::new("/path/to/tau"), inherit);
        assert_eq!(check.args, ["-m", "tau_core", "version"]);
        assert_eq!(check.program, launch.program);
        assert_eq!(check.env, launch.env);
    }

    #[test]
    fn builds_a_small_explicit_environment() {
        let env = build_env(Path::new("/path/to/tau"), inherit);
        assert_eq!(env["TAU_HOME"], "/path/to/tau");
        assert_eq!(env["TERM"], "xterm-256color");
        assert_eq!(env["COLORTERM"], "truecolor");
        assert_eq!(env["LANG"], "en_US.UTF-8");
        assert_eq!(env["PATH"], DEFAULT_PATH);
        assert_eq!(env["HOME"], "/example/home");
        assert_eq!(env["SHELL"], "/bin/zsh");
        // Not on the allowlist: never inherited, whatever the parent had. TERM, PATH and LANG
        // are set above, never taken from the parent.
        for name in ["TAU_LANG", "OPENAI_API_KEY"] {
            assert!(!env.contains_key(name), "{name} leaked into the TUI");
        }
        let keys: Vec<&str> = env.keys().map(String::as_str).collect();
        assert_eq!(
            keys,
            [
                "COLORTERM",
                "HOME",
                "LANG",
                "PATH",
                "SHELL",
                "TAU_HOME",
                "TERM"
            ]
        );
    }

    #[test]
    fn passes_the_whole_allowlist_through_when_present() {
        let env = build_env(Path::new("/path/to/tau"), |name| match name {
            "HOME" => Some("/example/home".into()),
            "USER" => Some("example".into()),
            "LOGNAME" => Some("example".into()),
            "TMPDIR" => Some("/example/tmp/".into()),
            "SHELL" => Some("/bin/zsh".into()),
            "__CF_USER_TEXT_ENCODING" => Some("0x1F5:0x0:0x0".into()),
            "TAU_LANG" => Some("tr".into()),
            _ => None,
        });
        for name in INHERITED {
            assert!(env.contains_key(*name), "{name} was not passed on");
        }
        assert_eq!(env["USER"], "example");
        assert_eq!(env["TMPDIR"], "/example/tmp/");
        assert!(!env.contains_key("TAU_LANG"));
        assert_eq!(env.len(), INHERITED.len() + 1 + 1 + TERMINAL_ENV.len()); // + PATH, TAU_HOME
    }

    #[test]
    fn keeps_locale_overrides_only_when_they_are_utf8() {
        let env = build_env(Path::new("/path/to/tau"), |name| match name {
            "LC_ALL" => Some("tr_TR.UTF-8".into()),
            "LC_CTYPE" => Some("C".into()),
            _ => None,
        });
        assert_eq!(env["LC_ALL"], "tr_TR.UTF-8");
        assert!(!env.contains_key("LC_CTYPE"));
        assert!(is_utf8_locale("UTF-8"));
        assert!(is_utf8_locale("tr_TR.utf8"));
        assert!(!is_utf8_locale("POSIX"));
        assert!(!is_utf8_locale("tr_TR"));
    }

    #[test]
    fn the_pty_command_starts_from_an_empty_environment() {
        let launch = Launch::tui(Path::new("/path/to/tau"), inherit);
        let command = launch.pty_command();
        let env: BTreeMap<&str, &str> = command.iter_full_env_as_str().collect();
        let expected: BTreeMap<&str, &str> = launch
            .env
            .iter()
            .map(|(k, v)| (k.as_str(), v.as_str()))
            .collect();
        assert_eq!(env, expected);
        assert_eq!(
            command.get_cwd().map(|c| c.to_string_lossy().into_owned()),
            Some("/path/to/tau".into())
        );
        assert_eq!(
            command.get_argv(),
            &["/path/to/tau/.venv/bin/python", "-m", "tau_core", "tui"]
                .map(std::ffi::OsString::from)
                .to_vec()
        );
    }
}
