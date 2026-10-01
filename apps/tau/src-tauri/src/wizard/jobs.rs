//! The commands the wizard runs, built in Rust from what discovery found: the page names a job
//! (`install` these features, `run` this feature, pair Telegram, deploy the spine), never a
//! program, a Python or an environment.
//!
//! - `tau` jobs are `<python> -m tau_core --lang <en|tr> <words…>` with the tau that discovery
//!   found, in `TAU_HOME`. Feature ids are checked against the catalog's id pattern and the
//!   spine folder must be an absolute path, so nothing the page sends turns into an option.
//! - uv jobs are the one-line installer's logic (`cloud/universe/public/install.sh`) without a
//!   shell pipe: Astral's installer is downloaded to a private temporary folder with `curl` and
//!   run with `/bin/sh`, then `uv tool install tau-core --with tau-tui`.
//! - The environment is an allowlist, as for the hub and the chat windows: the user's basics, a
//!   UTF-8 locale, uv's own variables (`UV_*`, `XDG_*`: a throwaway `UV_TOOL_DIR` reaches uv), a
//!   `PATH` with uv's bin dir on it, `TAU_HOME`, and `TAU_DATA_DIR` when the hub settings set
//!   one. Nothing secret: keys and tokens go on stdin.

use super::discover::Found;
use super::runner::{Job, STOP_GRACE};
use crate::chat::launch::{build_env, DEFAULT_PATH};
use serde::Deserialize;
use serde_json::Value;
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};
use std::time::Duration;

/// Astral's official uv installer (what `install.sh` runs).
pub const UV_INSTALLER_URL: &str = "https://astral.sh/uv/install.sh";
/// The input object `tau setup run` reads: at most 64 KiB.
pub const STDIN_LIMIT: usize = 64 * 1024;

/// How long each kind of job may take.
pub const STATUS_TIMEOUT: Duration = Duration::from_secs(60);
pub const INSTALL_TIMEOUT: Duration = Duration::from_secs(30 * 60);
pub const RUN_TIMEOUT: Duration = Duration::from_secs(30 * 60);
/// `tau telegram pair` waits up to 10 minutes for the code.
pub const PAIR_TIMEOUT: Duration = Duration::from_secs(12 * 60);
pub const DEPLOY_TIMEOUT: Duration = Duration::from_secs(15 * 60);
pub const UV_TIMEOUT: Duration = Duration::from_secs(10 * 60);

/// The UI language of every `tau` call (`tau --lang`).
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Lang {
    #[default]
    En,
    Tr,
}

impl Lang {
    pub fn code(self) -> &'static str {
        match self {
            Lang::En => "en",
            Lang::Tr => "tr",
        }
    }
}

/// A `tau` job the page may ask for.
#[derive(Clone, Debug, PartialEq, Eq, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum Spec {
    /// `tau setup install --features a,b --json`.
    Install { features: Vec<String> },
    /// `tau setup run <target> --json`: a feature, or `init`, `about`, `doctor`.
    Run { target: String },
    /// `tau telegram pair --json` (issue 172).
    TelegramPair,
    /// `tau net spine deploy <dir> --json` (issue 174).
    SpineDeploy { dir: String },
}

impl Spec {
    /// The words after `tau`, checked.
    pub fn words(&self) -> Result<Vec<String>, String> {
        Ok(match self {
            Spec::Install { features } => {
                if features.is_empty() || features.len() > 32 {
                    return Err("Choose between 1 and 32 features to install.".into());
                }
                for id in features {
                    check_id(id)?;
                }
                vec![
                    "setup".into(),
                    "install".into(),
                    "--features".into(),
                    features.join(","),
                    "--json".into(),
                ]
            }
            Spec::Run { target } => {
                check_id(target)?;
                vec![
                    "setup".into(),
                    "run".into(),
                    target.clone(),
                    "--json".into(),
                ]
            }
            Spec::TelegramPair => vec!["telegram".into(), "pair".into(), "--json".into()],
            Spec::SpineDeploy { dir } => vec![
                "net".into(),
                "spine".into(),
                "deploy".into(),
                spine_dir(dir)?,
                "--json".into(),
            ],
        })
    }

    pub fn timeout(&self) -> Duration {
        match self {
            Spec::Install { .. } => INSTALL_TIMEOUT,
            Spec::Run { .. } => RUN_TIMEOUT,
            Spec::TelegramPair => PAIR_TIMEOUT,
            Spec::SpineDeploy { .. } => DEPLOY_TIMEOUT,
        }
    }
}

/// A feature id or core step: the catalog's pattern, `[a-z][a-z0-9-]{0,31}`.
pub fn check_id(id: &str) -> Result<(), String> {
    let mut chars = id.chars();
    let ok = id.len() <= 32
        && chars.next().is_some_and(|c| c.is_ascii_lowercase())
        && chars.all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '-');
    if ok {
        Ok(())
    } else {
        Err(format!("{id:?} is not a feature id."))
    }
}

/// The spine project folder: an absolute path (the engine expands `~` before it names it).
fn spine_dir(dir: &str) -> Result<String, String> {
    let ok = dir.starts_with('/') && dir.len() <= 1024 && !dir.contains('\0') && dir != "/";
    if ok {
        Ok(dir.to_string())
    } else {
        Err(format!("{dir:?} is not a folder for the spine."))
    }
}

/// The words of a command the wizard's terminal runs after `tau`: the `command` of a
/// `needs_ui` event (`["guard", "setup"]`). The first is a subcommand; none is empty, holds a
/// NUL or a newline, and there are at most 16.
pub fn terminal_words(command: &[String]) -> Result<Vec<String>, String> {
    let first = command.first().ok_or("No command to run.")?;
    check_id(first).map_err(|_| format!("{first:?} is not a tau command."))?;
    if command.len() > 16 {
        return Err("That command is too long.".into());
    }
    for word in command {
        if word.is_empty() || word.len() > 1024 || word.contains(['\0', '\n', '\r']) {
            return Err(format!("{word:?} cannot be part of a tau command."));
        }
    }
    Ok(command.to_vec())
}

/// The job's input as the one line `tau` reads: a JSON object, at most [`STDIN_LIMIT`].
pub fn stdin_line(input: Option<&Value>) -> Result<Option<Vec<u8>>, String> {
    let Some(input) = input else {
        return Ok(None);
    };
    if !input.is_object() {
        return Err("The input must be a JSON object.".into());
    }
    let mut line = serde_json::to_vec(input).map_err(|err| err.to_string())?;
    if line.len() > STDIN_LIMIT {
        return Err("The input is larger than 64 KiB.".into());
    }
    line.push(b'\n');
    Ok(Some(line))
}

/// Where the wizard's jobs run and what they inherit.
pub struct Context<'a> {
    pub user_home: &'a Path,
    pub inherited: &'a dyn Fn(&str) -> Option<String>,
    /// All of the app's environment variable names (for the `UV_*` and `XDG_*` passthrough).
    pub names: &'a [String],
    /// The hub settings' `TAU_DATA_DIR`, if any.
    pub data_dir: Option<&'a Path>,
    /// The hub settings' `PATH`, if any.
    pub hub_path: Option<&'a str>,
    /// uv, when discovery found it.
    pub uv: Option<&'a Path>,
}

/// The basics every job inherits.
const INHERITED: &[&str] = &[
    "HOME",
    "USER",
    "LOGNAME",
    "TMPDIR",
    "SHELL",
    "__CF_USER_TEXT_ENCODING",
];

impl Context<'_> {
    /// `PATH`: uv's dir and `~/.local/bin` first, then the hub's `PATH` (or the default).
    pub fn path(&self) -> String {
        let mut dirs: Vec<String> = Vec::new();
        if let Some(dir) = self.uv.and_then(Path::parent) {
            dirs.push(dir.display().to_string());
        }
        dirs.push(self.user_home.join(".local/bin").display().to_string());
        let rest = self
            .hub_path
            .filter(|p| !p.is_empty())
            .unwrap_or(DEFAULT_PATH);
        dirs.extend(rest.split(':').map(str::to_string));
        let mut seen = std::collections::HashSet::new();
        dirs.retain(|d| !d.is_empty() && seen.insert(d.clone()));
        dirs.join(":")
    }

    /// The environment of a non-interactive job (no terminal).
    pub fn env(&self, home: Option<&Path>) -> BTreeMap<String, String> {
        let mut env = BTreeMap::new();
        for name in INHERITED {
            if let Some(value) = (self.inherited)(name) {
                env.insert(name.to_string(), value);
            }
        }
        for name in self.names {
            let passed = name.starts_with("UV_") || name.starts_with("XDG_");
            if passed {
                if let Some(value) = (self.inherited)(name) {
                    env.insert(name.clone(), value);
                }
            }
        }
        for name in ["LC_ALL", "LC_CTYPE"] {
            if let Some(value) = (self.inherited)(name).filter(|v| {
                let lower = v.to_ascii_lowercase();
                lower.contains("utf-8") || lower.contains("utf8")
            }) {
                env.insert(name.into(), value);
            }
        }
        env.insert("LANG".into(), "en_US.UTF-8".into());
        env.insert("PATH".into(), self.path());
        env.insert("NO_COLOR".into(), "1".into());
        env.insert("PYTHONUNBUFFERED".into(), "1".into());
        if let Some(home) = home {
            env.insert("TAU_HOME".into(), home.display().to_string());
            if let Some(dir) = self.data_dir.filter(|d| !d.as_os_str().is_empty()) {
                env.insert("TAU_DATA_DIR".into(), dir.display().to_string());
            }
        }
        env
    }

    /// Where a job runs: `TAU_HOME` once it exists, else the user's home.
    fn cwd(&self, home: &Path) -> PathBuf {
        if home.is_dir() {
            home.to_path_buf()
        } else {
            self.user_home.to_path_buf()
        }
    }

    /// `python -m tau_core --lang <lang> <words…>` for the tau discovery found.
    pub fn tau(
        &self,
        tau: &Found,
        lang: Lang,
        words: Vec<String>,
        stdin: Option<Vec<u8>>,
        timeout: Duration,
    ) -> Job {
        let mut args = vec![
            "-m".to_string(),
            "tau_core".into(),
            "--lang".into(),
            lang.code().into(),
        ];
        args.extend(words);
        Job {
            program: tau.python.clone(),
            args,
            cwd: self.cwd(&tau.home),
            env: self.env(Some(&tau.home)),
            stdin,
            timeout,
            stop_grace: STOP_GRACE,
        }
    }

    /// The same for the wizard's terminal: a PTY gets the chat windows' terminal environment.
    pub fn terminal(
        &self,
        tau: &Found,
        lang: Lang,
        words: Vec<String>,
    ) -> crate::chat::launch::Launch {
        let mut env = build_env(&tau.home, self.inherited);
        if let Some(dir) = self.data_dir.filter(|d| !d.as_os_str().is_empty()) {
            env.insert("TAU_DATA_DIR".into(), dir.display().to_string());
        }
        env.insert("PATH".into(), self.path());
        let mut args = vec![
            "-m".to_string(),
            "tau_core".into(),
            "--lang".into(),
            lang.code().into(),
        ];
        args.extend(words);
        crate::chat::launch::Launch {
            program: tau.python.clone(),
            args,
            cwd: self.cwd(&tau.home),
            env,
        }
    }

    /// `curl` downloads Astral's installer into `file` (never piped into a shell).
    pub fn download_uv_installer(&self, file: &Path) -> Job {
        Job {
            program: "/usr/bin/curl".into(),
            args: vec![
                "--proto".into(),
                "=https".into(),
                "--tlsv1.2".into(),
                "-fsSL".into(),
                "-o".into(),
                file.display().to_string(),
                UV_INSTALLER_URL.into(),
            ],
            cwd: self.user_home.to_path_buf(),
            env: self.env(None),
            stdin: None,
            timeout: UV_TIMEOUT,
            stop_grace: STOP_GRACE,
        }
    }

    /// `/bin/sh <file>`: Astral's installer, as `install.sh` runs it (no sudo; it installs
    /// into `UV_INSTALL_DIR` or `~/.local/bin`).
    pub fn run_uv_installer(&self, file: &Path) -> Job {
        Job {
            program: "/bin/sh".into(),
            args: vec![file.display().to_string()],
            cwd: self.user_home.to_path_buf(),
            env: self.env(None),
            stdin: None,
            timeout: UV_TIMEOUT,
            stop_grace: STOP_GRACE,
        }
    }

    /// `uv tool install tau-core --with tau-tui` (`TAU_INSTALL_VERSION` pins both, as in
    /// `install.sh`).
    pub fn install_tau(&self, uv: &Path, version: Option<&str>) -> Job {
        let (core, tui) = match version {
            Some(v) => (format!("tau-core=={v}"), format!("tau-tui=={v}")),
            None => ("tau-core".to_string(), "tau-tui".to_string()),
        };
        self.uv_job(
            uv,
            vec!["tool".into(), "install".into(), core, "--with".into(), tui],
        )
    }

    /// `uv tool upgrade tau-core`: a tau-core without `tau setup` (older than 0.5).
    pub fn upgrade_tau(&self, uv: &Path) -> Job {
        self.uv_job(uv, vec!["tool".into(), "upgrade".into(), "tau-core".into()])
    }

    /// `uv tool dir`: where uv keeps its tools (discovery).
    pub fn uv_tool_dir(&self, uv: &Path) -> Job {
        let mut job = self.uv_job(uv, vec!["tool".into(), "dir".into()]);
        job.timeout = Duration::from_secs(15);
        job
    }

    fn uv_job(&self, uv: &Path, args: Vec<String>) -> Job {
        Job {
            program: uv.to_path_buf(),
            args,
            cwd: self.user_home.to_path_buf(),
            env: self.env(None),
            stdin: None,
            timeout: INSTALL_TIMEOUT,
            stop_grace: STOP_GRACE,
        }
    }
}

/// `TAU_INSTALL_VERSION`, when it is a version like `0.5.0` (the rule of `install.sh`).
pub fn install_version(value: Option<String>) -> Option<String> {
    let value = value?.trim().to_string();
    let ok = value.chars().next().is_some_and(|c| c.is_ascii_digit())
        && value
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || matches!(c, '.' | '+' | '-'));
    ok.then_some(value)
}

#[cfg(test)]
mod tests {
    use super::super::discover::Kind;
    use super::*;
    use serde_json::json;

    fn found() -> Found {
        Found {
            python: "/example/home/.local/share/uv/tools/tau-core/bin/python".into(),
            home: "/example/home/.tau".into(),
            kind: Kind::UvTool,
            via: "/example/home/.local/share/uv/tools/tau-core".into(),
            version: "tau-core 0.5.0".into(),
            uv_tool: true,
        }
    }

    fn inherit(name: &str) -> Option<String> {
        match name {
            "HOME" => Some("/example/home".into()),
            "USER" => Some("example".into()),
            "UV_TOOL_DIR" => Some("/example/scratch/tools".into()),
            "XDG_DATA_HOME" => Some("/example/data".into()),
            "OPENAI_API_KEY" => Some("sk-example".into()),
            "TAU_LANG" => Some("tr".into()),
            "LC_ALL" => Some("C".into()),
            "PATH" => Some("/usr/bin".into()),
            _ => None,
        }
    }

    fn names() -> Vec<String> {
        [
            "HOME",
            "USER",
            "UV_TOOL_DIR",
            "XDG_DATA_HOME",
            "OPENAI_API_KEY",
            "TAU_LANG",
            "PATH",
        ]
        .map(String::from)
        .to_vec()
    }

    fn with_context<T>(f: impl FnOnce(&Context) -> T) -> T {
        let names = names();
        f(&Context {
            user_home: Path::new("/example/home"),
            inherited: &inherit,
            names: &names,
            data_dir: Some(Path::new("/example/data/tau")),
            hub_path: None,
            uv: Some(Path::new("/example/home/.local/bin/uv")),
        })
    }

    #[test]
    fn a_setup_run_is_python_m_tau_core_with_the_language() {
        let spec: Spec = serde_json::from_value(json!({"kind": "run", "target": "guard"})).unwrap();
        let job = with_context(|cx| {
            cx.tau(
                &found(),
                Lang::Tr,
                spec.words().unwrap(),
                None,
                spec.timeout(),
            )
        });
        assert_eq!(job.program, found().python);
        assert_eq!(
            job.args,
            ["-m", "tau_core", "--lang", "tr", "setup", "run", "guard", "--json"]
        );
        // ~/.tau does not exist yet: the job runs in the user's home.
        assert_eq!(job.cwd, PathBuf::from("/example/home"));
        assert_eq!(job.timeout, RUN_TIMEOUT);
    }

    #[test]
    fn every_job_kind_names_fixed_words() {
        let words = |value: Value| serde_json::from_value::<Spec>(value).unwrap().words();
        assert_eq!(
            words(json!({"kind": "install", "features": ["net", "cloud"]})).unwrap(),
            ["setup", "install", "--features", "net,cloud", "--json"]
        );
        assert_eq!(
            words(json!({"kind": "telegram_pair"})).unwrap(),
            ["telegram", "pair", "--json"]
        );
        assert_eq!(
            words(json!({"kind": "spine_deploy", "dir": "/example/home/tau-spine"})).unwrap(),
            [
                "net",
                "spine",
                "deploy",
                "/example/home/tau-spine",
                "--json"
            ]
        );
        for bad in [
            json!({"kind": "install", "features": []}),
            json!({"kind": "install", "features": ["--upgrade"]}),
            json!({"kind": "install", "features": ["net,guard"]}),
            json!({"kind": "run", "target": "-h"}),
            json!({"kind": "run", "target": "Guard"}),
            json!({"kind": "run", "target": ""}),
            json!({"kind": "spine_deploy", "dir": "--wrangler"}),
            json!({"kind": "spine_deploy", "dir": "relative/dir"}),
            json!({"kind": "spine_deploy", "dir": "/"}),
        ] {
            assert!(words(bad.clone()).is_err(), "{bad}");
        }
        // No job takes a program.
        assert!(
            serde_json::from_value::<Spec>(json!({"kind": "exec", "program": "/bin/sh"})).is_err()
        );
    }

    #[test]
    fn the_environment_is_an_allowlist_with_uv_and_tau_home() {
        let env = with_context(|cx| cx.env(Some(Path::new("/example/home/.tau"))));
        assert_eq!(env["TAU_HOME"], "/example/home/.tau");
        assert_eq!(env["TAU_DATA_DIR"], "/example/data/tau");
        assert_eq!(env["UV_TOOL_DIR"], "/example/scratch/tools");
        assert_eq!(env["XDG_DATA_HOME"], "/example/data");
        assert_eq!(env["LANG"], "en_US.UTF-8");
        assert_eq!(env["NO_COLOR"], "1");
        assert_eq!(
            env["PATH"],
            format!("/example/home/.local/bin:{DEFAULT_PATH}"),
            "uv's dir once, then the default"
        );
        for name in ["OPENAI_API_KEY", "TAU_LANG", "LC_ALL"] {
            assert!(!env.contains_key(name), "{name} leaked");
        }
        // uv jobs get no TAU_HOME.
        let uv = with_context(|cx| cx.install_tau(Path::new("/example/home/.local/bin/uv"), None));
        assert!(!uv.env.contains_key("TAU_HOME"));
        assert_eq!(
            uv.args,
            ["tool", "install", "tau-core", "--with", "tau-tui"]
        );
        let pinned = with_context(|cx| {
            cx.install_tau(Path::new("/example/home/.local/bin/uv"), Some("0.5.0"))
        });
        assert_eq!(
            pinned.args,
            [
                "tool",
                "install",
                "tau-core==0.5.0",
                "--with",
                "tau-tui==0.5.0"
            ]
        );
    }

    #[test]
    fn the_uv_installer_is_downloaded_then_run_never_piped() {
        let file = Path::new("/example/tmp/tau-uv/install.sh");
        let (download, install) =
            with_context(|cx| (cx.download_uv_installer(file), cx.run_uv_installer(file)));
        assert_eq!(download.program, PathBuf::from("/usr/bin/curl"));
        assert_eq!(download.args.last().unwrap(), UV_INSTALLER_URL);
        assert!(download.args.contains(&"=https".to_string()));
        assert!(download.stdin.is_none());
        assert_eq!(install.program, PathBuf::from("/bin/sh"));
        assert_eq!(install.args, [file.display().to_string()]);
    }

    #[test]
    fn the_terminal_runs_only_tau_subcommands() {
        let words =
            |w: &[&str]| terminal_words(&w.iter().map(|s| s.to_string()).collect::<Vec<_>>());
        assert_eq!(words(&["guard", "setup"]).unwrap(), ["guard", "setup"]);
        assert_eq!(
            words(&["net", "spine", "deploy", "/example/home/tau-spine"])
                .unwrap()
                .len(),
            4
        );
        assert!(words(&[]).is_err());
        assert!(words(&["/bin/sh"]).is_err());
        assert!(words(&["--help"]).is_err());
        assert!(words(&["guard", "set\nup"]).is_err());
        assert!(words(&["guard", ""]).is_err());
        let launch = with_context(|cx| {
            cx.terminal(&found(), Lang::En, vec!["guard".into(), "setup".into()])
        });
        assert_eq!(launch.program, found().python);
        assert_eq!(
            launch.args,
            ["-m", "tau_core", "--lang", "en", "guard", "setup"]
        );
        assert_eq!(launch.env["TERM"], "xterm-256color");
        assert_eq!(launch.env["TAU_HOME"], "/example/home/.tau");
        assert_eq!(launch.env["TAU_DATA_DIR"], "/example/data/tau");
        assert!(!launch.env.contains_key("OPENAI_API_KEY"));
    }

    #[test]
    fn the_input_is_one_json_line_and_only_an_object() {
        let line = stdin_line(Some(&json!({"inputs": {"key": "sk-example"}})))
            .unwrap()
            .unwrap();
        assert_eq!(line.last(), Some(&b'\n'));
        assert_eq!(line.iter().filter(|&&b| b == b'\n').count(), 1);
        assert_eq!(stdin_line(None).unwrap(), None);
        assert!(stdin_line(Some(&json!(["a"]))).is_err());
        let big = json!({"inputs": {"about": "x".repeat(STDIN_LIMIT)}});
        assert!(stdin_line(Some(&big)).is_err());
    }

    #[test]
    fn only_a_version_like_number_pins_the_install() {
        assert_eq!(
            install_version(Some("0.5.0".into())).as_deref(),
            Some("0.5.0")
        );
        assert_eq!(
            install_version(Some(" 0.5.0rc1 ".into())).as_deref(),
            Some("0.5.0rc1")
        );
        for bad in ["", "latest", "0.5.0; rm -rf ~", "--upgrade"] {
            assert_eq!(install_version(Some(bad.into())), None, "{bad}");
        }
        assert_eq!(install_version(None), None);
    }
}
