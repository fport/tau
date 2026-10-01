//! Finding tau on this Mac (roadmap 171): the Python that runs tau-core and the folder that is
//! `TAU_HOME`, so the app can run `tau setup`, the hub and the chat windows without asking.
//!
//! The candidates, in order (the first that passes `python -m tau_core version` wins):
//!
//! 1. **the hub settings**: `hub.python` when it exists, with `hub.tau_home`;
//! 2. **a checkout**: `<dir>/.venv/bin/python` for `TAU_HOME` from the app's environment, the
//!    hub settings' `tau_home` and the chat windows' saved folder;
//! 3. **a `uv tool install tau-core`**: `<tool dir>/tau-core/bin/python`, where the tool dir is
//!    what `uv tool dir` printed, `UV_TOOL_DIR`, `$XDG_DATA_HOME/uv/tools` or
//!    `~/.local/share/uv/tools`;
//! 4. **a `tau` command**: in uv's tool bin dir (`UV_TOOL_BIN_DIR`, `XDG_BIN_HOME`,
//!    `~/.local/bin`) or on the hub's `PATH`; its Python is the one its first line names (the
//!    `#!` line uv writes), or the `python` next to it for a relocatable `#!/bin/sh` launcher.
//!
//! For 3 and 4, `TAU_HOME` is the app's `TAU_HOME`, else the hub settings' `tau_home`, else
//! `~/.tau`, tau's own default.
//!
//! A Python path is never canonicalized: a venv's `bin/python` is a symlink to the base
//! interpreter, which has no tau-core. Only a `tau` command's own symlink is followed.

use crate::settings::HubSettings;
use serde::Serialize;
use std::fs;
use std::io::Read;
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};

/// The distribution `uv tool install tau-core` names its environment after.
pub const TOOL: &str = "tau-core";

/// What pointed at a Python.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Kind {
    /// The hub settings (`hub.python`).
    Settings,
    /// A checkout's `.venv/bin/python`.
    Checkout,
    /// uv's tool environment for tau-core.
    UvTool,
    /// A `tau` command's `#!` line.
    Command,
}

/// A Python to try, and the `TAU_HOME` that goes with it.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct Candidate {
    pub python: PathBuf,
    pub home: PathBuf,
    pub kind: Kind,
    /// The file or setting that pointed at it.
    pub via: PathBuf,
}

/// The tau the app uses: a candidate that passed the check.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct Found {
    pub python: PathBuf,
    pub home: PathBuf,
    pub kind: Kind,
    pub via: PathBuf,
    /// `tau-core 0.5.0`, the first line of `tau version`.
    pub version: String,
    /// The Python belongs to a `uv tool` environment (`uv-receipt.toml` next to its `bin`), so
    /// `tau setup install` can add packages and uv can upgrade it.
    pub uv_tool: bool,
}

/// A candidate that did not pass, and why.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct Rejected {
    pub python: PathBuf,
    pub kind: Kind,
    pub problem: String,
}

/// Where to look: the user's home, the app's environment and the hub's `PATH`.
pub struct Places<'a> {
    pub user_home: &'a Path,
    pub var: &'a dyn Fn(&str) -> Option<String>,
    /// `PATH` as the hub gets it (the settings' `path`, else the default).
    pub path: &'a str,
}

impl Places<'_> {
    /// A non-empty variable as a path, with a leading `~/` expanded.
    fn var_path(&self, name: &str) -> Option<PathBuf> {
        let value = (self.var)(name).filter(|v| !v.trim().is_empty())?;
        Some(self.expand(value.trim()))
    }

    fn expand(&self, value: &str) -> PathBuf {
        match value.strip_prefix("~/") {
            Some(rest) => self.user_home.join(rest),
            None if value == "~" => self.user_home.to_path_buf(),
            None => PathBuf::from(value),
        }
    }

    fn path_dirs(&self) -> Vec<PathBuf> {
        self.path
            .split(':')
            .filter(|d| !d.is_empty())
            .map(|d| self.expand(d))
            .collect()
    }

    /// `TAU_HOME` for an installed tau: the app's `TAU_HOME`, else the hub settings', else
    /// `~/.tau`.
    pub fn install_home(&self, hub: &HubSettings) -> PathBuf {
        self.var_path("TAU_HOME")
            .or_else(|| hub.tau_home.clone().filter(|p| !p.as_os_str().is_empty()))
            .unwrap_or_else(|| self.user_home.join(".tau"))
    }

    /// Where uv may be: where Astral's installer puts it (`UV_INSTALL_DIR`, `XDG_BIN_HOME`,
    /// `~/.local/bin`, `~/.cargo/bin`), then the hub's `PATH` and Homebrew.
    pub fn uv_candidates(&self) -> Vec<PathBuf> {
        let mut dirs: Vec<PathBuf> = ["UV_INSTALL_DIR", "XDG_BIN_HOME"]
            .iter()
            .filter_map(|name| self.var_path(name))
            .collect();
        dirs.push(self.user_home.join(".local/bin"));
        dirs.push(self.user_home.join(".cargo/bin"));
        dirs.extend(self.path_dirs());
        dirs.push("/opt/homebrew/bin".into());
        dirs.push("/usr/local/bin".into());
        unique(dirs.into_iter().map(|d| d.join("uv")))
    }

    /// The first `uv` that is an executable file.
    pub fn find_uv(&self) -> Option<PathBuf> {
        self.uv_candidates().into_iter().find(|p| is_executable(p))
    }

    /// uv's tool directories: what `uv tool dir` printed, `UV_TOOL_DIR`,
    /// `$XDG_DATA_HOME/uv/tools`, `~/.local/share/uv/tools`.
    pub fn tool_dirs(&self, uv_said: Option<PathBuf>) -> Vec<PathBuf> {
        let mut dirs: Vec<PathBuf> = uv_said.into_iter().collect();
        dirs.extend(self.var_path("UV_TOOL_DIR"));
        dirs.extend(self.var_path("XDG_DATA_HOME").map(|d| d.join("uv/tools")));
        dirs.push(self.user_home.join(".local/share/uv/tools"));
        unique(dirs)
    }

    /// Where a `tau` command may be: uv's tool bin dirs, then the hub's `PATH`.
    pub fn bin_dirs(&self) -> Vec<PathBuf> {
        let mut dirs: Vec<PathBuf> = ["UV_TOOL_BIN_DIR", "XDG_BIN_HOME"]
            .iter()
            .filter_map(|name| self.var_path(name))
            .collect();
        dirs.extend(self.var_path("XDG_DATA_HOME").map(|d| d.join("../bin")));
        dirs.push(self.user_home.join(".local/bin"));
        dirs.extend(self.path_dirs());
        unique(dirs)
    }

    /// Every candidate, in the order of the module docs, without duplicates. `chat_home` is the
    /// chat windows' saved folder; `uv_tool_dir` what `uv tool dir` printed, if uv ran.
    pub fn candidates(
        &self,
        hub: &HubSettings,
        chat_home: Option<&Path>,
        uv_tool_dir: Option<PathBuf>,
    ) -> Vec<Candidate> {
        let mut found: Vec<Candidate> = Vec::new();
        let install_home = self.install_home(hub);
        let hub_home = hub.tau_home.clone().filter(|p| !p.as_os_str().is_empty());
        if let Some(python) = hub.python.clone().filter(|p| p.is_file()) {
            found.push(Candidate {
                via: python.clone(),
                python,
                home: hub_home.clone().unwrap_or_else(|| install_home.clone()),
                kind: Kind::Settings,
            });
        }
        let checkouts = [
            self.var_path("TAU_HOME"),
            hub_home,
            chat_home.map(Path::to_path_buf),
        ];
        for dir in checkouts.into_iter().flatten() {
            let python = dir.join(".venv/bin/python");
            if python.is_file() {
                found.push(Candidate {
                    via: dir.clone(),
                    python,
                    home: dir,
                    kind: Kind::Checkout,
                });
            }
        }
        for dir in self.tool_dirs(uv_tool_dir) {
            let python = dir.join(TOOL).join("bin/python");
            if python.is_file() {
                found.push(Candidate {
                    via: dir.join(TOOL),
                    python,
                    home: install_home.clone(),
                    kind: Kind::UvTool,
                });
            }
        }
        for dir in self.bin_dirs() {
            let script = dir.join("tau");
            if let Some(python) = python_of_command(&script) {
                found.push(Candidate {
                    via: script,
                    python,
                    home: install_home.clone(),
                    kind: Kind::Command,
                });
            }
        }
        let mut seen = std::collections::HashSet::new();
        found.retain(|c| seen.insert(c.python.clone()));
        found
    }
}

/// The Python a `tau` command runs: the interpreter its `#!` line names, or, for uv's
/// relocatable `#!/bin/sh` launcher, the `python` next to the command's real file.
pub fn python_of_command(script: &Path) -> Option<PathBuf> {
    if !script.is_file() {
        return None;
    }
    let real = script.canonicalize().ok()?;
    let mut head = [0u8; 512];
    let n = fs::File::open(&real).ok()?.read(&mut head).ok()?;
    let text = String::from_utf8_lossy(&head[..n]);
    let first = text.lines().next()?.strip_prefix("#!")?.trim();
    let interpreter = first.split_whitespace().next()?;
    let python = if interpreter == "/bin/sh" {
        real.parent()?.join("python")
    } else if interpreter.ends_with("/env") {
        // `#!/usr/bin/env python3`: which Python that is depends on PATH; not a tau install.
        return None;
    } else {
        PathBuf::from(interpreter)
    };
    python.is_file().then_some(python)
}

/// Whether `python` lives in a `uv tool` environment (`<env>/bin/python` with
/// `<env>/uv-receipt.toml`).
pub fn in_uv_tool(python: &Path) -> bool {
    python
        .parent()
        .and_then(Path::parent)
        .is_some_and(|env| env.join("uv-receipt.toml").is_file())
}

/// The first candidate that passes `check` (which returns `tau-core <version>`), and the ones
/// that did not, with why.
pub fn first_working(
    candidates: Vec<Candidate>,
    mut check: impl FnMut(&Candidate) -> Result<String, String>,
) -> (Option<Found>, Vec<Rejected>) {
    let mut rejected = Vec::new();
    for candidate in candidates {
        match check(&candidate) {
            Ok(version) => {
                let uv_tool = in_uv_tool(&candidate.python);
                return (
                    Some(Found {
                        python: candidate.python,
                        home: candidate.home,
                        kind: candidate.kind,
                        via: candidate.via,
                        version,
                        uv_tool,
                    }),
                    rejected,
                );
            }
            Err(problem) => rejected.push(Rejected {
                python: candidate.python,
                kind: candidate.kind,
                problem,
            }),
        }
    }
    (None, rejected)
}

fn is_executable(path: &Path) -> bool {
    fs::metadata(path).is_ok_and(|m| m.is_file() && m.permissions().mode() & 0o111 != 0)
}

fn unique(paths: impl IntoIterator<Item = PathBuf>) -> Vec<PathBuf> {
    let mut seen = std::collections::HashSet::new();
    paths
        .into_iter()
        .filter(|p| seen.insert(p.clone()))
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashMap;

    /// A fake user home in a temp dir, with an environment of our own.
    struct Mac {
        home: PathBuf,
        env: HashMap<&'static str, String>,
        path: String,
    }

    impl Mac {
        fn new(name: &str) -> Self {
            let root = std::env::temp_dir()
                .join(format!("tau-app-discover-{name}-{}", std::process::id()));
            let _ = fs::remove_dir_all(&root);
            fs::create_dir_all(&root).unwrap();
            let home = root.canonicalize().unwrap();
            Self {
                path: format!("{}:/usr/bin:/bin", home.join("brew/bin").display()),
                home,
                env: HashMap::new(),
            }
        }

        fn file(&self, rel: &str, text: &str) -> PathBuf {
            let path = self.home.join(rel);
            fs::create_dir_all(path.parent().unwrap()).unwrap();
            fs::write(&path, text).unwrap();
            fs::set_permissions(&path, fs::Permissions::from_mode(0o755)).unwrap();
            path
        }

        /// What `uv tool install tau-core` leaves: the tool env with its Python, the receipt,
        /// `bin/tau` with an absolute `#!` line, and a symlink in the tool bin dir.
        fn uv_tool(&self, tools: &str, bin: &str) -> PathBuf {
            let env = self.home.join(tools).join(TOOL);
            let python = self.file(&format!("{tools}/{TOOL}/bin/python"), "#!/bin/sh\n");
            self.file(&format!("{tools}/{TOOL}/uv-receipt.toml"), "[tool]\n");
            let script = self.file(
                &format!("{tools}/{TOOL}/bin/tau"),
                &format!("#!{}\nimport sys\n", python.display()),
            );
            let link = self.home.join(bin).join("tau");
            fs::create_dir_all(link.parent().unwrap()).unwrap();
            std::os::unix::fs::symlink(&script, &link).unwrap();
            assert!(env.is_dir());
            python
        }

        fn with_places<T>(&self, f: impl FnOnce(&Places) -> T) -> T {
            let var = |name: &str| self.env.get(name).cloned();
            f(&Places {
                user_home: &self.home,
                var: &var,
                path: &self.path,
            })
        }

        fn candidates(&self, hub: &HubSettings, chat: Option<&Path>) -> Vec<Candidate> {
            self.with_places(|places| places.candidates(hub, chat, None))
        }

        fn find_uv(&self) -> Option<PathBuf> {
            self.with_places(|places| places.find_uv())
        }
    }

    #[test]
    fn finds_a_uv_tool_install_and_uses_tau_s_default_home() {
        let mac = Mac::new("uv-tool");
        let python = mac.uv_tool(".local/share/uv/tools", ".local/bin");
        let found = mac.candidates(&HubSettings::default(), None);
        // The tool env first, then the same Python again through ~/.local/bin/tau (dropped).
        assert_eq!(found.len(), 1, "{found:?}");
        assert_eq!(found[0].python, python);
        assert_eq!(found[0].kind, Kind::UvTool);
        assert_eq!(found[0].home, mac.home.join(".tau"));
        assert!(in_uv_tool(&python));
    }

    #[test]
    fn honours_uv_tool_dir_and_the_dir_uv_reports() {
        let mut mac = Mac::new("uv-tool-dir");
        let python = mac.uv_tool("scratch/tools", "scratch/bin");
        // Nothing at the default places: only UV_TOOL_DIR (or `uv tool dir`) finds it.
        assert!(mac.candidates(&HubSettings::default(), None).is_empty());
        mac.env.insert(
            "UV_TOOL_DIR",
            mac.home.join("scratch/tools").display().to_string(),
        );
        let found = mac.candidates(&HubSettings::default(), None);
        assert_eq!(found[0].python, python);
        mac.env.clear();
        let found = mac.with_places(|places| {
            places.candidates(
                &HubSettings::default(),
                None,
                Some(mac.home.join("scratch/tools")),
            )
        });
        assert_eq!(found[0].python, python);
        assert_eq!(found[0].via, mac.home.join("scratch/tools").join(TOOL));
    }

    #[test]
    fn follows_a_tau_command_to_its_python() {
        let mut mac = Mac::new("command");
        // A tool env somewhere else, reached only through UV_TOOL_BIN_DIR's `tau`.
        let python = mac.uv_tool("elsewhere/tools", "scratch/bin");
        mac.env.insert(
            "UV_TOOL_BIN_DIR",
            mac.home.join("scratch/bin").display().to_string(),
        );
        let found = mac.candidates(&HubSettings::default(), None);
        assert_eq!(found.len(), 1, "{found:?}");
        assert_eq!(found[0].kind, Kind::Command);
        assert_eq!(found[0].python, python);
        assert_eq!(found[0].via, mac.home.join("scratch/bin/tau"));
    }

    #[test]
    fn reads_the_relocatable_launcher_and_skips_env_shebangs() {
        let mac = Mac::new("launchers");
        let python = mac.file("venv/bin/python", "#!/bin/sh\n");
        let launcher = mac.file(
            "venv/bin/tau",
            "#!/bin/sh\n'''exec' \"$(dirname -- \"$(realpath -- \"$0\")\")\"/'python' \"$0\" \"$@\"\n' '''\n",
        );
        assert_eq!(python_of_command(&launcher), Some(python));
        let env = mac.file("other/tau", "#!/usr/bin/env python3\n");
        assert_eq!(python_of_command(&env), None);
        let gone = mac.file("gone/tau", "#!/nowhere/python\n");
        assert_eq!(python_of_command(&gone), None);
        let binary = mac.file("bin/tau", "\u{7f}ELF");
        assert_eq!(python_of_command(&binary), None);
        assert_eq!(python_of_command(&mac.home.join("missing/tau")), None);
        // A `tau` on the hub's PATH (Homebrew, pipx) counts too.
        let brew_python = mac.file("brew/libexec/bin/python", "#!/bin/sh\n");
        mac.file("brew/bin/tau", &format!("#!{}\n", brew_python.display()));
        let found = mac.candidates(&HubSettings::default(), None);
        assert_eq!(found.last().unwrap().python, brew_python);
        assert_eq!(found.last().unwrap().kind, Kind::Command);
    }

    #[test]
    fn the_settings_and_checkouts_come_first() {
        let mut mac = Mac::new("order");
        let tool_python = mac.uv_tool(".local/share/uv/tools", ".local/bin");
        let checkout = mac.home.join("src/tau");
        let venv = mac.file("src/tau/.venv/bin/python", "#!/bin/sh\n");
        let chat = mac.home.join("chat/tau");
        let chat_venv = mac.file("chat/tau/.venv/bin/python", "#!/bin/sh\n");
        let hub = HubSettings {
            python: Some(venv.clone()),
            tau_home: Some(checkout.clone()),
            ..HubSettings::default()
        };
        let found = mac.candidates(&hub, Some(&chat));
        let order: Vec<(Kind, &Path)> =
            found.iter().map(|c| (c.kind, c.python.as_path())).collect();
        assert_eq!(
            order,
            [
                (Kind::Settings, venv.as_path()),
                (Kind::Checkout, chat_venv.as_path()),
                (Kind::UvTool, tool_python.as_path()),
            ],
            "the hub's checkout is the settings' candidate already"
        );
        // An installed tau goes with the hub's TAU_HOME, and TAU_HOME from the app wins.
        assert_eq!(found[2].home, checkout);
        mac.env.insert("TAU_HOME", "~/custom".into());
        let found = mac.candidates(&HubSettings::default(), None);
        assert_eq!(found[0].home, mac.home.join("custom"));
    }

    #[test]
    fn a_hub_python_that_is_gone_is_no_candidate() {
        let mac = Mac::new("gone");
        let hub = HubSettings {
            python: Some(mac.home.join("gone/python")),
            tau_home: Some(mac.home.join("gone")),
            ..HubSettings::default()
        };
        assert!(mac.candidates(&hub, None).is_empty());
    }

    #[test]
    fn finds_uv_where_its_installer_puts_it() {
        let mut mac = Mac::new("uv");
        // Nothing in the fake home yet (a uv of the machine running the test may still be found
        // in /opt/homebrew/bin, /usr/local/bin or /usr/bin).
        assert!(mac.find_uv().is_none_or(|p| !p.starts_with(&mac.home)));
        let cargo = mac.file(".cargo/bin/uv", "#!/bin/sh\n");
        assert_eq!(mac.find_uv(), Some(cargo.clone()));
        let local = mac.file(".local/bin/uv", "#!/bin/sh\n");
        assert_eq!(mac.find_uv(), Some(local));
        let own = mac.file("opt/uv/uv", "#!/bin/sh\n");
        mac.env.insert(
            "UV_INSTALL_DIR",
            mac.home.join("opt/uv").display().to_string(),
        );
        assert_eq!(mac.find_uv(), Some(own));
        // A file that is not executable is not uv.
        let plain = mac.home.join("opt/uv/uv");
        fs::set_permissions(&plain, fs::Permissions::from_mode(0o644)).unwrap();
        assert_ne!(mac.find_uv(), Some(plain));
        assert!(mac.with_places(|places| places.uv_candidates().contains(&cargo)));
    }

    #[test]
    fn the_first_candidate_that_passes_wins() {
        let mac = Mac::new("first");
        let a = Candidate {
            python: mac.home.join("a/bin/python"),
            home: mac.home.join(".tau"),
            kind: Kind::Command,
            via: mac.home.join("a/bin/tau"),
        };
        let b = Candidate {
            python: mac.uv_tool("tools", "bin"),
            ..a.clone()
        };
        let (found, rejected) = first_working(vec![a.clone(), b.clone()], |c| {
            if c.python == a.python {
                Err("No module named tau_core".into())
            } else {
                Ok("tau-core 0.5.0".into())
            }
        });
        let found = found.unwrap();
        assert_eq!(found.python, b.python);
        assert_eq!(found.version, "tau-core 0.5.0");
        assert!(found.uv_tool);
        assert_eq!(rejected.len(), 1);
        assert_eq!(rejected[0].problem, "No module named tau_core");
        let (none, rejected) = first_working(vec![a], |_| Err("broken".into()));
        assert!(none.is_none());
        assert_eq!(rejected.len(), 1);
    }
}
