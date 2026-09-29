//! TauBar's state and the actions the tray menu and the settings window share.

use crate::eventlog::EventLog;
use crate::login::{self, LoginItemStatus};
use crate::settings::{JsonFile, RuntimeState, Settings, SleepMode, SETTINGS_FILE, STATE_FILE};
use crate::sleep::{Power, SleepController, SleepStatus};
use serde::Serialize;
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Mutex, MutexGuard};

/// Where TauBar keeps its files: `$TAUBAR_HOME` (settings and `logs/` inside it) when set,
/// else the app config dir (`~/Library/Application Support/com.tau.taubar`) and the app log
/// dir (`~/Library/Logs/com.tau.taubar`).
#[derive(Clone, Debug)]
pub struct Dirs {
    pub config: PathBuf,
    pub logs: PathBuf,
}

impl Dirs {
    pub fn from_home(home: PathBuf) -> Self {
        Self {
            logs: home.join("logs"),
            config: home,
        }
    }
}

#[derive(Clone, Debug, Serialize)]
pub struct LoginSnapshot {
    pub status: LoginItemStatus,
    pub problem: Option<String>,
}

#[derive(Clone, Debug, Serialize)]
pub struct FilesSnapshot {
    pub settings: String,
    pub log: String,
}

/// Everything the menu and the settings window show.
#[derive(Clone, Debug, Serialize)]
pub struct Snapshot {
    pub version: &'static str,
    pub sleep: SleepStatus,
    /// The menu's sleep header line.
    pub sleep_summary: String,
    pub login: LoginSnapshot,
    pub files: FilesSnapshot,
}

pub struct Core<P: Power> {
    pub dirs: Dirs,
    pub log: EventLog,
    /// No settings file existed: TauBar opens its window once so a first-time user sees it
    /// even when macOS hides the menu bar icon (a notched display with a full menu bar).
    pub first_run: bool,
    settings_file: JsonFile,
    state_file: JsonFile,
    settings: Mutex<Settings>,
    sleep: Mutex<SleepController<P>>,
    login: Mutex<LoginSnapshot>,
    shut_down: AtomicBool,
}

fn lock<T>(mutex: &Mutex<T>) -> MutexGuard<'_, T> {
    mutex.lock().unwrap_or_else(|e| e.into_inner())
}

impl<P: Power> Core<P> {
    /// Load the settings, put the saved sleep mode in force and read the login item state.
    pub fn start(dirs: Dirs, power: P) -> Self {
        let log = EventLog::new(&dirs.logs);
        let settings_file = JsonFile::new(&dirs.config, SETTINGS_FILE);
        let state_file = JsonFile::new(&dirs.config, STATE_FILE);
        let first_run = !settings_file.path().exists();
        let (settings, settings_problem) = settings_file.load::<Settings>();
        let (state, state_problem) = state_file.load::<RuntimeState>();
        log.write(format!(
            "TauBar {} started (pid {})",
            env!("CARGO_PKG_VERSION"),
            std::process::id()
        ));
        for problem in [settings_problem, state_problem].into_iter().flatten() {
            log.write(problem);
        }
        if state.lid_engaged {
            log.write("the previous run left sleep disabled (pmset disablesleep 1); resetting it");
        }
        let core = Self {
            login: Mutex::new(LoginSnapshot {
                status: login::status(),
                problem: None,
            }),
            sleep: Mutex::new(SleepController::new(power, state.lid_engaged)),
            settings: Mutex::new(settings),
            settings_file,
            state_file,
            log,
            dirs,
            first_run,
            shut_down: AtomicBool::new(false),
        };
        let mode = lock(&core.settings).sleep_mode;
        core.apply_sleep(mode);
        if first_run {
            // Write the defaults so the next start is not a first run.
            core.save_settings(&lock(&core.settings));
        }
        core
    }

    fn save_settings(&self, settings: &Settings) {
        if let Err(err) = self.settings_file.save(settings) {
            self.log.write(format!(
                "{} could not be saved: {err}",
                self.settings_file.path().display()
            ));
        }
    }

    pub fn settings(&self) -> Settings {
        lock(&self.settings).clone()
    }

    pub fn snapshot(&self) -> Snapshot {
        let sleep = lock(&self.sleep).status().clone();
        Snapshot {
            version: env!("CARGO_PKG_VERSION"),
            sleep_summary: crate::tray::sleep_header(&sleep),
            sleep,
            login: lock(&self.login).clone(),
            files: FilesSnapshot {
                settings: self.settings_file.path().display().to_string(),
                log: self.log.path().display().to_string(),
            },
        }
    }

    // -- sleep ---------------------------------------------------------------------------

    /// Pick a sleep mode: put it in force and remember it.
    pub fn set_sleep_mode(&self, mode: SleepMode) -> SleepStatus {
        let status = self.apply_sleep(mode);
        let mut settings = lock(&self.settings);
        if settings.sleep_mode != mode {
            settings.sleep_mode = mode;
            self.save_settings(&settings);
        }
        status
    }

    /// Re-check the sudoers rule; when it appeared or disappeared, apply the chosen mode
    /// again (so installing the rule makes the lid-closed mode available without a restart).
    /// Returns whether anything changed.
    pub fn recheck_sleep(&self) -> bool {
        let (installed, available) = {
            let sleep = lock(&self.sleep);
            (
                sleep.power().lid_rule_installed(),
                sleep.status().lid_available,
            )
        };
        if installed == available {
            return false;
        }
        self.log.write(if installed {
            "the lid-closed sudoers rule is installed"
        } else {
            "the lid-closed sudoers rule is gone"
        });
        let mode = lock(&self.settings).sleep_mode;
        self.apply_sleep(mode);
        true
    }

    fn apply_sleep(&self, mode: SleepMode) -> SleepStatus {
        let (status, lid_engaged) = {
            let mut sleep = lock(&self.sleep);
            let before = sleep.status().clone();
            let status = sleep.apply(mode).clone();
            if status.effective != before.effective || status.problem != before.problem {
                self.log
                    .write(format!("sleep mode: {}", status.effective.label()));
                if let Some(problem) = &status.problem {
                    self.log.write(format!("sleep: {problem}"));
                }
            }
            (status, sleep.lid_engaged())
        };
        self.save_state(lid_engaged);
        status
    }

    fn save_state(&self, lid_engaged: bool) {
        let state = RuntimeState { lid_engaged };
        if let Err(err) = self.state_file.save(&state) {
            self.log.write(format!(
                "{} could not be saved: {err}",
                self.state_file.path().display()
            ));
        }
    }

    // -- login item ------------------------------------------------------------------------

    pub fn login_status(&self) -> LoginItemStatus {
        lock(&self.login).status
    }

    /// Re-read the login item state (the user can change it in System Settings).
    /// Returns whether it changed.
    pub fn refresh_login(&self) -> bool {
        let status = login::status();
        let mut login = lock(&self.login);
        let changed = login.status != status;
        login.status = status;
        changed
    }

    pub fn set_launch_at_login(&self, enabled: bool) -> Result<LoginItemStatus, String> {
        let result = login::set(enabled);
        let mut login = lock(&self.login);
        match &result {
            Ok(status) => {
                login.status = *status;
                login.problem = None;
                self.log.write(format!(
                    "launch at login {} (login item: {status:?})",
                    if enabled { "on" } else { "off" }
                ));
            }
            Err(err) => {
                login.status = login::status();
                login.problem = Some(err.clone());
                self.log.write(format!(
                    "launch at login could not be turned {}: {err}",
                    if enabled { "on" } else { "off" }
                ));
            }
        }
        result
    }

    // -- quit ------------------------------------------------------------------------------

    /// Undo everything TauBar holds. Idempotent: the Quit item, a signal and the app's exit
    /// event may all call it.
    pub fn shutdown(&self) {
        if self.shut_down.swap(true, Ordering::SeqCst) {
            return;
        }
        let (problem, lid_engaged) = {
            let mut sleep = lock(&self.sleep);
            (sleep.restore(), sleep.lid_engaged())
        };
        self.save_state(lid_engaged);
        if let Some(problem) = problem {
            self.log.write(format!("sleep: {problem}"));
        }
        self.log.write("TauBar quit; normal sleep restored");
    }
}

impl SleepMode {
    pub fn label(self) -> &'static str {
        match self {
            SleepMode::Normal => "Normal",
            SleepMode::KeepAwakeOnAc => "Keep awake on AC power",
            SleepMode::KeepAwakeLidClosed => "Keep awake with the lid closed",
        }
    }
}
