//! TauBar's state and the actions the tray menu and the settings window share.

use crate::eventlog::EventLog;
use crate::hub::display;
use crate::hub::launch::{HubCommands, LaunchdAgent};
use crate::hub::supervisor::{HubView, Probe, Supervisor};
use crate::login::{self, LoginItemStatus};
use crate::settings::{
    HubSettings, JsonFile, RuntimeState, Settings, SleepMode, SETTINGS_FILE, STATE_FILE,
};
use crate::sleep::{Power, SleepController, SleepStatus};
use serde::Serialize;
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex, MutexGuard};
use std::time::{Duration, Instant};

/// How long quitting TauBar waits for its hub to stop before SIGKILL.
const HUB_STOP_ON_QUIT: Duration = Duration::from_secs(10);

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

#[derive(Clone, Debug, Serialize)]
pub struct HubSnapshot {
    #[serde(flatten)]
    pub view: HubView,
    /// The menu's three hub lines: status, Telegram (or a problem), last crash.
    pub lines: [String; 3],
    /// The same for the panel, without the labels.
    pub panel: display::HubPanel,
    /// The saved switch (what TauBar does at its next start).
    pub run_at_start: bool,
    pub settings: HubSettings,
}

/// Everything the menu and the settings window show.
#[derive(Clone, Debug, Serialize)]
pub struct Snapshot {
    pub version: &'static str,
    pub hub: HubSnapshot,
    pub sleep: SleepStatus,
    /// The menu's sleep header line.
    pub sleep_summary: String,
    pub login: LoginSnapshot,
    pub files: FilesSnapshot,
}

pub struct Core<P: Power, H: Probe> {
    pub dirs: Dirs,
    pub log: Arc<EventLog>,
    /// No settings file existed: TauBar opens its window once so a first-time user sees it
    /// even when macOS hides the menu bar icon (a notched display with a full menu bar).
    pub first_run: bool,
    settings_file: JsonFile,
    state_file: JsonFile,
    settings: Mutex<Settings>,
    runtime: Mutex<RuntimeState>,
    sleep: Mutex<SleepController<P>>,
    hub: Mutex<Supervisor<H>>,
    login: Mutex<LoginSnapshot>,
    shut_down: AtomicBool,
}

fn lock<T>(mutex: &Mutex<T>) -> MutexGuard<'_, T> {
    mutex.lock().unwrap_or_else(|e| e.into_inner())
}

/// The hub commands for `settings`, with TauBar's own environment to inherit from.
fn hub_commands(settings: &HubSettings) -> Result<HubCommands, String> {
    HubCommands::from_settings(settings, |name| std::env::var(name).ok())
}

impl<P: Power, H: Probe> Core<P, H> {
    /// Load the settings, put the saved sleep mode in force, read the login item state and
    /// start (or adopt) the hub when "Run the hub" is on. `user_home` is where an installed
    /// launchd agent is looked for.
    pub fn start(dirs: Dirs, power: P, hub_probe: H, user_home: PathBuf) -> Self {
        let log = Arc::new(EventLog::new(&dirs.logs));
        let settings_file = JsonFile::new(&dirs.config, SETTINGS_FILE);
        let state_file = JsonFile::new(&dirs.config, STATE_FILE);
        let first_run = !settings_file.path().exists();
        let (mut settings, settings_problem) = settings_file.load::<Settings>();
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

        let mut imported = false;
        if settings.hub.python.is_none() && settings.hub.tau_home.is_none() {
            let plist = LaunchdAgent::plist_path(&user_home);
            if let Some(agent) = LaunchdAgent::read(&plist) {
                settings.hub = agent.to_settings();
                imported = true;
                log.write(format!(
                    "hub settings imported from the launchd agent {}",
                    plist.display()
                ));
            }
        }

        let mut supervisor = Supervisor::new(hub_probe, log.clone());
        supervisor.configure(hub_commands(&settings.hub));

        let core = Self {
            login: Mutex::new(LoginSnapshot {
                status: login::status(),
                problem: None,
            }),
            sleep: Mutex::new(SleepController::new(power, state.lid_engaged)),
            hub: Mutex::new(supervisor),
            runtime: Mutex::new(state.clone()),
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
        if first_run || imported {
            core.save_settings(&lock(&core.settings));
        }

        let run_hub = lock(&core.settings).run_hub;
        {
            let mut hub = lock(&core.hub);
            let now = Instant::now();
            if run_hub {
                if let Some(pid) = state.hub_pid {
                    hub.adopt(pid, now);
                }
                core.log.write("run the hub: on (saved setting)");
                hub.set_desired(true, now);
            } else {
                hub.tick(now);
            }
        }
        core.save_hub_pid();
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

    fn save_state(&self) {
        let state = lock(&self.runtime).clone();
        if let Err(err) = self.state_file.save(&state) {
            self.log.write(format!(
                "{} could not be saved: {err}",
                self.state_file.path().display()
            ));
        }
    }

    pub fn settings(&self) -> Settings {
        lock(&self.settings).clone()
    }

    pub fn snapshot(&self) -> Snapshot {
        let sleep = lock(&self.sleep).status().clone();
        let view = lock(&self.hub).view(Instant::now());
        let settings = self.settings();
        Snapshot {
            version: env!("CARGO_PKG_VERSION"),
            hub: HubSnapshot {
                lines: [
                    display::status_line(&view),
                    display::detail_line(&view),
                    display::crash_line(&view),
                ],
                panel: display::panel(&view),
                view,
                run_at_start: settings.run_hub,
                settings: settings.hub,
            },
            sleep_summary: crate::tray::sleep_header(&sleep),
            sleep,
            login: lock(&self.login).clone(),
            files: FilesSnapshot {
                settings: self.settings_file.path().display().to_string(),
                log: self.log.path().display().to_string(),
            },
        }
    }

    // -- hub -------------------------------------------------------------------------------

    /// One supervisor step (every second from the hub thread).
    pub fn hub_tick(&self) {
        if self.shut_down.load(Ordering::SeqCst) {
            return;
        }
        lock(&self.hub).tick(Instant::now());
        self.save_hub_pid();
    }

    /// The switch as it stands now.
    pub fn hub_switch(&self) -> bool {
        lock(&self.hub).desired()
    }

    /// "Run the hub" on or off: remembered for the next start, applied now. Returns a message
    /// for the user when TauBar cannot do what the switch says (a hub it did not start).
    pub fn set_run_hub(&self, on: bool) -> Option<String> {
        {
            let mut settings = lock(&self.settings);
            if settings.run_hub != on {
                settings.run_hub = on;
                self.save_settings(&settings);
            }
        }
        self.log
            .write(format!("run the hub: {}", if on { "on" } else { "off" }));
        let message = lock(&self.hub).set_desired(on, Instant::now());
        self.save_hub_pid();
        message
    }

    /// New hub settings from the window. A running hub keeps running; they apply to the
    /// next start.
    pub fn save_hub_settings(&self, hub: HubSettings) -> Result<(), String> {
        let commands = hub_commands(&hub);
        {
            let mut settings = lock(&self.settings);
            settings.hub = hub;
            self.save_settings(&settings);
        }
        let error = commands
            .as_ref()
            .err()
            .cloned()
            .or_else(|| commands.as_ref().ok().and_then(|c| c.check_paths().err()));
        {
            let mut supervisor = lock(&self.hub);
            let running = supervisor.own_pid().is_some();
            supervisor.configure(commands);
            supervisor.tick(Instant::now());
            self.log.write(if running {
                "hub settings saved; the running hub keeps its settings until it restarts"
            } else {
                "hub settings saved"
            });
        }
        match error {
            Some(err) => Err(err),
            None => Ok(()),
        }
    }

    /// The hub's own log file, once the configuration is resolved.
    pub fn hub_log(&self) -> Option<PathBuf> {
        lock(&self.hub).resolved().map(|r| r.hub_log())
    }

    fn save_hub_pid(&self) {
        let pid = lock(&self.hub).own_pid();
        let changed = {
            let mut runtime = lock(&self.runtime);
            let changed = runtime.hub_pid != pid;
            runtime.hub_pid = pid;
            changed
        };
        if changed {
            self.save_state();
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
        lock(&self.runtime).lid_engaged = lid_engaged;
        self.save_state();
        status
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

    /// Undo everything TauBar holds: stop the hub it started, then restore normal sleep.
    /// Idempotent: the Quit item, a signal and the app's exit event may all call it.
    pub fn shutdown(&self) {
        if self.shut_down.swap(true, Ordering::SeqCst) {
            return;
        }
        lock(&self.hub).shutdown(HUB_STOP_ON_QUIT);
        lock(&self.runtime).hub_pid = None;
        let (problem, lid_engaged) = {
            let mut sleep = lock(&self.sleep);
            (sleep.restore(), sleep.lid_engaged())
        };
        lock(&self.runtime).lid_engaged = lid_engaged;
        self.save_state();
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
