//! TauBar's hub supervisor.
//!
//! With the switch on, TauBar starts `tau hub run` as its child and keeps it running: a crash
//! or `kill -9` is restarted after a short backoff ([`RestartPolicy`]), a clean exit
//! (`tau hub stop`) leaves the hub stopped and the switch off, and turning the switch off or
//! quitting TauBar stops it with SIGTERM (SIGKILL after a timeout).
//!
//! TauBar never runs a second hub: before every start it probes the hub lock of the data dir
//! the configuration resolves to, and it leaves a data dir alone while a loaded `com.tau.hub`
//! launchd agent owns it. A hub it did not start is shown, never stopped.
//!
//! [`Supervisor::tick`] does all the work; the app calls it every second from a background
//! thread. Everything it cannot do itself (resolving the config, probing the lock and the
//! control API, launchd) goes through [`Probe`], so the tests run real child processes
//! against a fake environment.

use super::guard::{self, GuardStatus};
use super::launch::{HubCommands, Launch};
use super::policy::{classify, ExitKind, RestartPolicy};
use super::probe::{self, LockProbe, Resolved};
use crate::eventlog::{local_timestamp, EventLog};
use serde::Serialize;
use serde_json::Value;
use std::fs::OpenOptions;
use std::os::unix::process::{CommandExt, ExitStatusExt};
use std::path::{Path, PathBuf};
use std::process::{Child, Stdio};
use std::sync::Arc;
use std::time::{Duration, Instant};

/// Everything the supervisor looks at besides its own child.
pub trait Probe: Send {
    /// `tau hub status --json` for these commands' configuration.
    fn resolve(&mut self, status: &Launch) -> Result<Resolved, String>;
    fn lock(&self, path: &Path) -> LockProbe;
    /// `GET <path>` on the control API; `None` when it does not answer.
    fn get_json(&self, port: u16, path: &str) -> Option<Value>;
    /// A loaded `com.tau.hub` launchd agent runs the hub of `data_dir`.
    fn launchd_manages(&self, data_dir: &Path) -> bool;
    /// An adopted hub wrote `stopped_at` for `pid` on its way out.
    fn stopped_cleanly(&self, hub_dir: &Path, pid: u32) -> bool;
}

/// The real machine.
pub struct SystemProbe {
    pub user_home: PathBuf,
}

impl Probe for SystemProbe {
    fn resolve(&mut self, status: &Launch) -> Result<Resolved, String> {
        probe::resolve(status, Duration::from_secs(20))
    }
    fn lock(&self, path: &Path) -> LockProbe {
        probe::probe_lock(path)
    }
    fn get_json(&self, port: u16, path: &str) -> Option<Value> {
        // Loopback: a live control API answers in milliseconds (it runs in its own thread).
        probe::get_json(port, path, Duration::from_millis(800))
    }
    fn launchd_manages(&self, data_dir: &Path) -> bool {
        probe::launchd_manages(&self.user_home, data_dir)
    }
    fn stopped_cleanly(&self, hub_dir: &Path, pid: u32) -> bool {
        probe::stopped_cleanly(hub_dir, pid)
    }
}

/// Timings; the tests shorten them.
#[derive(Clone, Debug)]
pub struct Timings {
    pub health_every: Duration,
    pub stop_timeout: Duration,
    pub resolve_retry: Duration,
    pub launchd_cache: Duration,
}

impl Default for Timings {
    fn default() -> Self {
        Self {
            health_every: Duration::from_secs(2),
            stop_timeout: Duration::from_secs(15),
            resolve_retry: Duration::from_secs(15),
            launchd_cache: Duration::from_secs(30),
        }
    }
}

enum Handle {
    /// Started by this TauBar: exit status known.
    Child(Child),
    /// Started by an earlier TauBar that died; watched through the hub lock.
    Adopted,
}

struct OwnHub {
    handle: Handle,
    pid: u32,
    started: Instant,
    stop_sent: Option<Instant>,
    up_logged: bool,
}

/// An unexpected exit TauBar saw (TauBar's own record, local time).
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct ExitRecord {
    pub at: String,
    pub pid: u32,
    pub reason: String,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum HubState {
    /// No Python / TAU_HOME, or they do not exist.
    NotConfigured,
    Off,
    /// TauBar's hub is running, `/health` has not answered yet.
    Starting,
    /// TauBar's hub answers `/health`.
    Up,
    Stopping,
    /// Waiting out the backoff after a crash.
    Restarting,
    /// TauBar's hub exited cleanly by itself (`tau hub stop`).
    Stopped,
    /// A hub TauBar did not start holds the lock or answers on the port.
    Elsewhere,
    /// The switch is on, but a loaded launchd agent owns this data dir and its hub is down.
    LaunchdIdle,
    /// The configuration could not be resolved.
    Error,
}

/// What the menu and the window show about the hub.
#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct HubView {
    pub switch_on: bool,
    pub state: HubState,
    pub pid: Option<u32>,
    /// The hub was started by TauBar (now or by an earlier TauBar that it adopted).
    pub by_taubar: bool,
    /// A loaded launchd agent owns this data dir.
    pub launchd: bool,
    pub uptime_s: Option<f64>,
    pub restart_in_s: Option<u64>,
    /// Unexpected exits TauBar saw since it started.
    pub restarts: u32,
    pub last_exit: Option<ExitRecord>,
    /// The hub's own `last_crash` from `/status`.
    pub last_crash: Option<Value>,
    /// `telegram` from `/status`.
    pub telegram: Option<Value>,
    /// The owner guard's block of `/status` (none without a guard service).
    pub guard: Option<GuardStatus>,
    pub control_url: Option<String>,
    pub hub_log: Option<String>,
    pub command: Option<String>,
    pub problem: Option<String>,
}

pub struct Supervisor<P: Probe> {
    probe: P,
    log: Arc<EventLog>,
    pub policy: RestartPolicy,
    pub timings: Timings,
    commands: Option<HubCommands>,
    config_error: Option<String>,
    resolved: Option<Resolved>,
    resolve_error: Option<String>,
    resolve_after: Option<Instant>,
    desired: bool,
    own: Option<OwnHub>,
    restart_at: Option<Instant>,
    stopped_clean: bool,
    /// `Some(pid)` while a hub TauBar did not start holds the lock.
    external: Option<Option<u32>>,
    launchd: Option<(Instant, bool)>,
    launchd_idle: bool,
    last_exit: Option<ExitRecord>,
    restarts: u32,
    spawn_error: Option<String>,
    health: Option<Value>,
    status: Option<Value>,
    next_poll: Option<Instant>,
}

impl<P: Probe> Supervisor<P> {
    pub fn new(probe: P, log: Arc<EventLog>) -> Self {
        Self {
            probe,
            log,
            policy: RestartPolicy::default(),
            timings: Timings::default(),
            commands: None,
            config_error: Some("the hub is not set up".into()),
            resolved: None,
            resolve_error: None,
            resolve_after: None,
            desired: false,
            own: None,
            restart_at: None,
            stopped_clean: false,
            external: None,
            launchd: None,
            launchd_idle: false,
            last_exit: None,
            restarts: 0,
            spawn_error: None,
            health: None,
            status: None,
            next_poll: None,
        }
    }

    /// New hub settings (at start and whenever the window saves them). A hub that is running
    /// keeps running; the new settings apply to the next start.
    pub fn configure(&mut self, commands: Result<HubCommands, String>) {
        match commands.and_then(|c| c.check_paths().map(|()| c)) {
            Ok(commands) => {
                self.commands = Some(commands);
                self.config_error = None;
            }
            Err(err) => {
                self.commands = None;
                self.config_error = Some(err);
            }
        }
        self.resolved = None;
        self.resolve_error = None;
        self.resolve_after = None;
        self.launchd = None;
        self.next_poll = None;
    }

    /// The switch as it stands (a clean exit turns it off for this session).
    pub fn desired(&self) -> bool {
        self.desired
    }

    /// The pid of the hub TauBar started (or adopted) while it runs.
    pub fn own_pid(&self) -> Option<u32> {
        self.own.as_ref().map(|own| own.pid)
    }

    pub fn resolved(&self) -> Option<&Resolved> {
        self.resolved.as_ref()
    }

    /// Poll `/health` and `/status` at the next tick instead of waiting out the interval
    /// (after "Lock now", so the guard line follows at once).
    pub fn poll_soon(&mut self) {
        self.next_poll = None;
    }

    /// Turn the switch on or off. Returns a message for the user when the switch cannot do
    /// what it says: turning it off with a hub TauBar did not start.
    pub fn set_desired(&mut self, on: bool, now: Instant) -> Option<String> {
        if on {
            self.desired = true;
            self.stopped_clean = false;
            self.restart_at = None;
            self.spawn_error = None;
            self.policy.reset();
            self.tick(now);
            return None;
        }
        self.desired = false;
        self.restart_at = None;
        self.launchd_idle = false;
        if self.own.is_some() {
            self.stop_own(now);
            return None;
        }
        let pid = self.external.flatten().or_else(|| self.health_pid());
        pid.map(|pid| self.not_ours_message(pid))
    }

    /// Take over the hub an earlier TauBar started (pid from its state file), if that hub
    /// still holds the lock. Returns whether it did.
    pub fn adopt(&mut self, pid: u32, now: Instant) -> bool {
        if self.own.is_some() {
            return false;
        }
        let Some(resolved) = self.ensure_resolved(now) else {
            return false;
        };
        let lock = self.probe.lock(&resolved.lock);
        if !(lock.held && lock.pid == Some(pid)) {
            return false;
        }
        self.own = Some(OwnHub {
            handle: Handle::Adopted,
            pid,
            started: now,
            stop_sent: None,
            up_logged: true,
        });
        self.log.write(format!(
            "hub: took over the hub an earlier TauBar started (pid {pid})"
        ));
        true
    }

    /// One step: reap, enforce stop timeouts, (re)start when due, poll the control API.
    pub fn tick(&mut self, now: Instant) {
        self.reap(now);
        self.enforce_stop_timeout(now);
        let due = self.restart_at.is_none_or(|at| now >= at);
        if self.desired && self.own.is_none() && due {
            self.restart_at = None;
            self.try_start(now);
        }
        self.poll(now);
    }

    /// Stop the hub TauBar started and wait for it (quit). SIGKILL after `timeout`.
    pub fn shutdown(&mut self, timeout: Duration) {
        self.desired = false;
        self.restart_at = None;
        if self.own.is_none() {
            return;
        }
        let start = Instant::now();
        self.stop_own(start);
        loop {
            self.reap(Instant::now());
            if self.own.is_none() {
                return;
            }
            if start.elapsed() >= timeout {
                self.kill_own("it did not stop in time while TauBar quit");
                std::thread::sleep(Duration::from_millis(100));
                self.reap(Instant::now());
                return;
            }
            std::thread::sleep(Duration::from_millis(50));
        }
    }

    pub fn view(&self, now: Instant) -> HubView {
        let health_pid = self.health_pid();
        let own_pid = self.own_pid();
        let state = if self.config_error.is_some() {
            HubState::NotConfigured
        } else if let Some(own) = &self.own {
            if own.stop_sent.is_some() {
                HubState::Stopping
            } else if health_pid == Some(own.pid) {
                HubState::Up
            } else {
                HubState::Starting
            }
        } else if self.external.is_some() || health_pid.is_some() {
            HubState::Elsewhere
        } else if self.desired && self.restart_at.is_some() {
            HubState::Restarting
        } else if self.desired && self.launchd_idle {
            HubState::LaunchdIdle
        } else if self.desired && self.resolve_error.is_some() {
            HubState::Error
        } else if self.stopped_clean {
            HubState::Stopped
        } else {
            HubState::Off
        };
        let answering = matches!(state, HubState::Up | HubState::Elsewhere);
        let uptime = |v: &Value| v.get("uptime_s").and_then(Value::as_f64);
        HubView {
            switch_on: self.desired,
            state,
            pid: own_pid.or(health_pid).or(self.external.flatten()),
            by_taubar: own_pid.is_some(),
            launchd: self.launchd.is_some_and(|(_, managed)| managed),
            uptime_s: answering
                .then(|| {
                    self.status
                        .as_ref()
                        .and_then(uptime)
                        .or(self.health.as_ref().and_then(uptime))
                })
                .flatten(),
            restart_in_s: self
                .restart_at
                .map(|at| at.saturating_duration_since(now).as_secs_f64().ceil() as u64),
            restarts: self.restarts,
            last_exit: self.last_exit.clone(),
            last_crash: self
                .status
                .as_ref()
                .and_then(|s| s.get("last_crash"))
                .filter(|v| !v.is_null())
                .cloned(),
            telegram: self
                .status
                .as_ref()
                .and_then(|s| s.get("telegram"))
                .cloned(),
            guard: self.status.as_ref().and_then(guard::parse),
            control_url: self.resolved.as_ref().map(Resolved::control_url),
            hub_log: self
                .resolved
                .as_ref()
                .map(|r| r.hub_log().display().to_string()),
            command: self.commands.as_ref().map(|c| c.run.display()),
            problem: self
                .config_error
                .clone()
                .or_else(|| self.resolve_error.clone())
                .or_else(|| self.spawn_error.clone()),
        }
    }

    // -- internals -----------------------------------------------------------------------

    fn health_pid(&self) -> Option<u32> {
        self.health
            .as_ref()
            .and_then(|h| h.get("pid"))
            .and_then(Value::as_u64)
            .and_then(|pid| u32::try_from(pid).ok())
    }

    fn not_ours_message(&self, pid: u32) -> String {
        let launchd = self.launchd.is_some_and(|(_, managed)| managed);
        let mut message = format!(
            "The running hub (pid {pid}) was not started by TauBar, so TauBar leaves it \
             alone. To stop it, run `uv run tau hub stop` in the tau checkout."
        );
        if launchd {
            message.push_str(
                " It runs under launchd (com.tau.hub): `uv run tau hub uninstall` stops it and \
                 removes the agent, after which TauBar can run the hub.",
            );
        }
        message
    }

    fn ensure_resolved(&mut self, now: Instant) -> Option<Resolved> {
        if let Some(resolved) = &self.resolved {
            return Some(resolved.clone());
        }
        let commands = self.commands.as_ref()?;
        if self.resolve_after.is_some_and(|after| now < after) {
            return None;
        }
        match self.probe.resolve(&commands.status) {
            Ok(resolved) => {
                if self.resolve_error.take().is_some() {
                    self.log.write("hub: configuration resolved again");
                }
                self.resolved = Some(resolved.clone());
                Some(resolved)
            }
            Err(err) => {
                if self.resolve_error.as_deref() != Some(err.as_str()) {
                    self.log.write(format!("hub: {err}"));
                }
                self.resolve_error = Some(err);
                self.resolve_after = Some(now + self.timings.resolve_retry);
                None
            }
        }
    }

    fn launchd_cached(&mut self, data_dir: &Path, now: Instant) -> bool {
        if let Some((at, managed)) = self.launchd {
            if now.saturating_duration_since(at) < self.timings.launchd_cache {
                return managed;
            }
        }
        let managed = self.probe.launchd_manages(data_dir);
        self.launchd = Some((now, managed));
        managed
    }

    fn try_start(&mut self, now: Instant) {
        let Some(commands) = self.commands.clone() else {
            return;
        };
        let Some(resolved) = self.ensure_resolved(now) else {
            return;
        };
        let lock = self.probe.lock(&resolved.lock);
        if lock.held {
            if self.external != Some(lock.pid) {
                let by = if self.launchd_cached(&resolved.data_dir, now) {
                    ", run by launchd"
                } else {
                    ""
                };
                let pid = lock.pid.map_or("?".to_string(), |p| p.to_string());
                self.log.write(format!(
                    "hub: a hub TauBar did not start is running (pid {pid}{by}); \
                     not starting a second one"
                ));
            }
            self.external = Some(lock.pid);
            self.launchd_idle = false;
            return;
        }
        if self.external.take().is_some() {
            self.log.write("hub: the hub started elsewhere has stopped");
        }
        if self.launchd_cached(&resolved.data_dir, now) {
            if !self.launchd_idle {
                self.log.write(
                    "hub: the launchd agent com.tau.hub is loaded for this data dir; TauBar \
                     leaves the hub to launchd (`uv run tau hub uninstall` hands it to TauBar)",
                );
            }
            self.launchd_idle = true;
            return;
        }
        self.launchd_idle = false;
        self.spawn(&commands.run, &resolved, now);
    }

    fn spawn(&mut self, run: &Launch, resolved: &Resolved, now: Instant) {
        let mut command = run.command();
        let (out, err) = resolved.output_logs();
        match (append(&out), append(&err)) {
            (Ok(out), Ok(err)) => {
                command.stdout(out).stderr(err);
            }
            _ => {
                command.stdout(Stdio::null()).stderr(Stdio::null());
            }
        }
        // Its own process group: a Ctrl-C meant for TauBar in a terminal does not hit the hub;
        // TauBar stops it with SIGTERM itself.
        command.process_group(0);
        match command.spawn() {
            Ok(child) => {
                let pid = child.id();
                self.own = Some(OwnHub {
                    handle: Handle::Child(child),
                    pid,
                    started: now,
                    stop_sent: None,
                    up_logged: false,
                });
                self.spawn_error = None;
                self.next_poll = Some(now + Duration::from_millis(500));
                self.log
                    .write(format!("hub: started pid {pid}: {}", run.display()));
            }
            Err(err) => {
                let reason = format!("could not start the hub: {err}");
                self.restarts += 1;
                self.last_exit = Some(ExitRecord {
                    at: local_timestamp(),
                    pid: 0,
                    reason: reason.clone(),
                });
                let delay = self.policy.next_delay(Duration::ZERO);
                self.restart_at = Some(now + delay);
                self.log
                    .write(format!("hub: {reason}; trying again in {}", secs(delay)));
                self.spawn_error = Some(reason);
            }
        }
    }

    fn reap(&mut self, now: Instant) {
        let Some(own) = self.own.as_mut() else {
            return;
        };
        let stop_requested = own.stop_sent.is_some();
        let exit = match &mut own.handle {
            Handle::Child(child) => match child.try_wait() {
                Ok(Some(status)) => Some(classify(status.code(), status.signal(), stop_requested)),
                Ok(None) => None,
                Err(err) => Some(ExitKind::Crash(format!("wait failed: {err}"))),
            },
            Handle::Adopted => {
                let pid = own.pid;
                let alive = self.resolved.as_ref().is_some_and(|r| {
                    let lock = self.probe.lock(&r.lock);
                    lock.held && lock.pid == Some(pid)
                });
                if alive {
                    None
                } else if stop_requested {
                    Some(ExitKind::Requested)
                } else if self
                    .resolved
                    .as_ref()
                    .is_some_and(|r| self.probe.stopped_cleanly(&r.hub_dir, pid))
                {
                    Some(ExitKind::Clean)
                } else {
                    Some(ExitKind::Crash("exited without a clean stop".into()))
                }
            }
        };
        if let Some(kind) = exit {
            if let Some(own) = self.own.take() {
                self.on_exit(kind, own, now);
            }
        }
    }

    fn on_exit(&mut self, kind: ExitKind, own: OwnHub, now: Instant) {
        let pid = own.pid;
        let uptime = now.saturating_duration_since(own.started);
        self.health = None;
        self.status = None;
        match kind {
            ExitKind::Requested => {
                self.policy.reset();
                self.log.write(format!("hub: pid {pid} stopped"));
            }
            ExitKind::Clean => {
                self.policy.reset();
                self.desired = false;
                self.stopped_clean = true;
                self.log.write(format!(
                    "hub: pid {pid} exited cleanly without TauBar asking (tau hub stop?); \
                     leaving it stopped and the switch off"
                ));
            }
            ExitKind::Crash(reason) => {
                self.restarts += 1;
                self.last_exit = Some(ExitRecord {
                    at: local_timestamp(),
                    pid,
                    reason: reason.clone(),
                });
                if self.desired {
                    let delay = self.policy.next_delay(uptime);
                    self.restart_at = Some(now + delay);
                    self.log.write(format!(
                        "hub: pid {pid} exited unexpectedly ({reason}) after {}; restarting in {}",
                        secs(uptime),
                        secs(delay)
                    ));
                } else {
                    self.log.write(format!(
                        "hub: pid {pid} exited unexpectedly ({reason}) with the switch off"
                    ));
                }
            }
        }
    }

    fn stop_own(&mut self, now: Instant) {
        let Some(own) = self.own.as_mut() else {
            return;
        };
        if own.stop_sent.is_some() {
            return;
        }
        own.stop_sent = Some(now);
        let pid = own.pid;
        // SAFETY: signalling a pid TauBar started (or adopted after checking the hub lock).
        unsafe { libc::kill(pid as libc::pid_t, libc::SIGTERM) };
        self.log.write(format!("hub: stopping pid {pid} (SIGTERM)"));
    }

    fn enforce_stop_timeout(&mut self, now: Instant) {
        let overdue = self.own.as_ref().is_some_and(|own| {
            own.stop_sent
                .is_some_and(|at| now.saturating_duration_since(at) >= self.timings.stop_timeout)
        });
        if overdue {
            self.kill_own("it did not stop within the timeout");
        }
    }

    fn kill_own(&mut self, why: &str) {
        let Some(own) = self.own.as_mut() else {
            return;
        };
        let pid = own.pid;
        match &mut own.handle {
            Handle::Child(child) => {
                let _ = child.kill();
            }
            // SAFETY: as in stop_own.
            Handle::Adopted => unsafe {
                libc::kill(pid as libc::pid_t, libc::SIGKILL);
            },
        }
        self.log
            .write(format!("hub: killed pid {pid} (SIGKILL): {why}"));
    }

    fn poll(&mut self, now: Instant) {
        if self.next_poll.is_some_and(|at| now < at) {
            return;
        }
        self.next_poll = Some(now + self.timings.health_every);
        let Some(resolved) = self.ensure_resolved(now) else {
            self.health = None;
            self.status = None;
            return;
        };
        let port = resolved.control_port;
        self.health = self.probe.get_json(port, "/health");
        self.status = if self.health.is_some() {
            self.probe.get_json(port, "/status")
        } else {
            None
        };
        let health_pid = self.health_pid();
        if let Some(own) = self.own.as_mut() {
            if !own.up_logged && health_pid == Some(own.pid) {
                own.up_logged = true;
                let after = now.saturating_duration_since(own.started);
                self.log.write(format!(
                    "hub: pid {} is up (/health answered after {})",
                    own.pid,
                    secs(after)
                ));
            }
        } else if health_pid.is_some() {
            // Someone else's hub answers: learn whether launchd runs it (for the menu).
            self.launchd_cached(&resolved.data_dir, now);
        }
    }
}

fn append(path: &Path) -> std::io::Result<std::fs::File> {
    if let Some(dir) = path.parent() {
        std::fs::create_dir_all(dir)?;
    }
    OpenOptions::new().create(true).append(true).open(path)
}

fn secs(duration: Duration) -> String {
    let s = duration.as_secs_f64();
    if s < 10.0 {
        format!("{s:.1} s")
    } else {
        format!("{} s", s.round() as u64)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::{BTreeMap, HashMap};
    use std::fs::File;
    use std::io::Write as _;
    use std::os::fd::AsRawFd;
    use std::sync::Mutex;

    /// A fake environment: a fixed resolved config in a temp dir, the real lock probe, a
    /// scripted control API and a launchd switch.
    #[derive(Clone)]
    struct FakeProbe {
        resolved: Resolved,
        answers: Arc<Mutex<HashMap<String, Value>>>,
        launchd: Arc<Mutex<bool>>,
    }

    impl Probe for FakeProbe {
        fn resolve(&mut self, _status: &Launch) -> Result<Resolved, String> {
            Ok(self.resolved.clone())
        }
        fn lock(&self, path: &Path) -> LockProbe {
            probe::probe_lock(path)
        }
        fn get_json(&self, _port: u16, path: &str) -> Option<Value> {
            self.answers.lock().unwrap().get(path).cloned()
        }
        fn launchd_manages(&self, _data_dir: &Path) -> bool {
            *self.launchd.lock().unwrap()
        }
        fn stopped_cleanly(&self, hub_dir: &Path, pid: u32) -> bool {
            probe::stopped_cleanly(hub_dir, pid)
        }
    }

    struct Rig {
        dir: PathBuf,
        probe: FakeProbe,
        sup: Supervisor<FakeProbe>,
        log: Arc<EventLog>,
    }

    impl Rig {
        fn new(name: &str, script: &str) -> Self {
            let dir =
                std::env::temp_dir().join(format!("taubar-sup-{name}-{}", std::process::id()));
            let _ = std::fs::remove_dir_all(&dir);
            std::fs::create_dir_all(dir.join("data/hub")).unwrap();
            let resolved = Resolved {
                control_port: 1,
                data_dir: dir.join("data"),
                hub_dir: dir.join("data/hub"),
                lock: dir.join("data/hub/hub.lock"),
            };
            let probe = FakeProbe {
                resolved,
                answers: Arc::new(Mutex::new(HashMap::new())),
                launchd: Arc::new(Mutex::new(false)),
            };
            let log = Arc::new(EventLog::new(&dir.join("logs")));
            let mut sup = Supervisor::new(probe.clone(), log.clone());
            sup.policy.first_delay = Duration::from_millis(150);
            sup.policy.max_delay = Duration::from_millis(600);
            sup.timings.health_every = Duration::from_millis(50);
            sup.timings.stop_timeout = Duration::from_secs(5);
            let launch = |args: &[&str]| Launch {
                program: "/bin/sh".into(),
                args: args.iter().map(|s| s.to_string()).collect(),
                cwd: dir.clone(),
                env: BTreeMap::new(),
            };
            sup.configure(Ok(HubCommands {
                run: launch(&["-c", script]),
                status: launch(&["-c", "true"]),
            }));
            Self {
                dir,
                probe,
                sup,
                log,
            }
        }

        /// Tick until `done` holds or `timeout` passes.
        fn run_until(&mut self, timeout: Duration, done: impl Fn(&Supervisor<FakeProbe>) -> bool) {
            let deadline = Instant::now() + timeout;
            while Instant::now() < deadline {
                self.sup.tick(Instant::now());
                if done(&self.sup) {
                    return;
                }
                std::thread::sleep(Duration::from_millis(20));
            }
        }

        fn state(&self) -> HubState {
            self.sup.view(Instant::now()).state
        }

        fn answer_health(&self, pid: u32) {
            let mut answers = self.probe.answers.lock().unwrap();
            answers.insert(
                "/health".into(),
                serde_json::json!({"ok": true, "pid": pid, "uptime_s": 1.0}),
            );
            answers.insert(
                "/status".into(),
                serde_json::json!({"pid": pid, "uptime_s": 1.0, "last_crash": null,
                    "telegram": {"configured": false, "reason": "TELEGRAM_BOT_TOKEN is not set"}}),
            );
        }

        fn hold_lock(&self, pid: u32) -> File {
            let path = &self.probe.resolved.lock;
            let mut file = File::create(path).unwrap();
            assert_eq!(unsafe { libc::flock(file.as_raw_fd(), libc::LOCK_EX) }, 0);
            writeln!(file, "{pid}").unwrap();
            file
        }

        fn log_text(&self) -> String {
            self.log.tail(200).join("\n")
        }
    }

    impl Drop for Rig {
        fn drop(&mut self) {
            self.sup.shutdown(Duration::from_secs(2));
            let _ = std::fs::remove_dir_all(&self.dir);
        }
    }

    fn alive(pid: u32) -> bool {
        unsafe { libc::kill(pid as libc::pid_t, 0) == 0 }
    }

    /// Let a fake hub reach its `trap` before it is signalled (like a real hub installing its
    /// SIGTERM handler).
    fn settle() {
        std::thread::sleep(Duration::from_millis(250));
    }

    const LONG: &str = "trap 'exit 0' TERM; while :; do sleep 0.05; done";

    #[test]
    fn switch_on_starts_the_hub_and_health_marks_it_up() {
        let mut rig = Rig::new("up", LONG);
        assert_eq!(rig.state(), HubState::Off);
        rig.sup.set_desired(true, Instant::now());
        let pid = rig.sup.own_pid().expect("started");
        assert!(alive(pid));
        assert_eq!(rig.state(), HubState::Starting);
        rig.answer_health(pid);
        rig.run_until(Duration::from_secs(2), |s| {
            s.view(Instant::now()).state == HubState::Up
        });
        let view = rig.sup.view(Instant::now());
        assert_eq!(view.state, HubState::Up);
        assert_eq!(view.pid, Some(pid));
        assert!(view.by_taubar);
        assert!(view.telegram.is_some());
        assert_eq!(view.guard, None, "no guard block, no guard");
        assert!(rig.log_text().contains(&format!("pid {pid} is up")));
    }

    #[test]
    fn the_guard_block_of_status_reaches_the_view() {
        let mut rig = Rig::new("guard", LONG);
        rig.sup.set_desired(true, Instant::now());
        let pid = rig.sup.own_pid().unwrap();
        rig.answer_health(pid);
        rig.probe.answers.lock().unwrap().insert(
            "/status".into(),
            serde_json::json!({"pid": pid, "uptime_s": 1.0, "guard": {"state": "unavailable",
                "enrolled": true, "available": false, "reason": "camera_denied"}}),
        );
        rig.run_until(Duration::from_secs(2), |s| {
            s.view(Instant::now()).guard.is_some()
        });
        let guard = rig.sup.view(Instant::now()).guard.expect("guard block");
        assert_eq!(guard.state, "unavailable");
        assert_eq!(guard.reason.as_deref(), Some("camera_denied"));
        // The hub goes away: the guard block goes with its /status.
        rig.probe.answers.lock().unwrap().clear();
        rig.sup.poll_soon();
        rig.sup.tick(Instant::now());
        assert_eq!(rig.sup.view(Instant::now()).guard, None);
    }

    #[test]
    fn a_crash_is_restarted_with_backoff() {
        let mut rig = Rig::new("crash", "exit 3");
        rig.sup.set_desired(true, Instant::now());
        rig.run_until(Duration::from_secs(5), |s| s.restarts >= 3);
        assert!(rig.sup.restarts >= 3, "restarts: {}", rig.sup.restarts);
        let view = rig.sup.view(Instant::now());
        assert_eq!(view.last_exit.unwrap().reason, "exit code 3");
        assert!(view.switch_on);
        let log = rig.log_text();
        assert!(log.contains("exited unexpectedly (exit code 3)"));
        assert!(log.contains("restarting in"));
    }

    #[test]
    fn kill_9_is_restarted_quickly() {
        let mut rig = Rig::new("kill9", LONG);
        rig.sup.set_desired(true, Instant::now());
        let first = rig.sup.own_pid().unwrap();
        unsafe { libc::kill(first as libc::pid_t, libc::SIGKILL) };
        let killed_at = Instant::now();
        rig.run_until(Duration::from_secs(3), |s| {
            s.own_pid().is_some_and(|pid| pid != first)
        });
        let second = rig.sup.own_pid().expect("restarted");
        assert_ne!(first, second);
        assert!(killed_at.elapsed() < Duration::from_secs(2));
        assert_eq!(
            rig.sup.view(Instant::now()).last_exit.unwrap().reason,
            "killed by SIGKILL"
        );
    }

    #[test]
    fn a_clean_exit_leaves_the_hub_stopped_and_the_switch_off() {
        let mut rig = Rig::new("clean", LONG);
        rig.sup.set_desired(true, Instant::now());
        let pid = rig.sup.own_pid().unwrap();
        settle();
        // What `tau hub stop` does: SIGTERM from outside; the hub exits 0.
        unsafe { libc::kill(pid as libc::pid_t, libc::SIGTERM) };
        rig.run_until(Duration::from_secs(3), |s| s.own_pid().is_none());
        rig.run_until(Duration::from_millis(500), |_| false);
        assert_eq!(rig.sup.own_pid(), None, "no restart after a clean exit");
        assert_eq!(rig.state(), HubState::Stopped);
        assert!(!rig.sup.desired());
        assert_eq!(rig.sup.restarts, 0);
        assert!(rig
            .log_text()
            .contains("exited cleanly without TauBar asking"));
    }

    #[test]
    fn switch_off_stops_the_hub_and_does_not_restart_it() {
        let mut rig = Rig::new("off", LONG);
        rig.sup.set_desired(true, Instant::now());
        let pid = rig.sup.own_pid().unwrap();
        assert!(rig.sup.set_desired(false, Instant::now()).is_none());
        assert_eq!(rig.state(), HubState::Stopping);
        rig.run_until(Duration::from_secs(3), |s| s.own_pid().is_none());
        rig.run_until(Duration::from_millis(400), |_| false);
        assert!(!alive(pid));
        assert_eq!(rig.sup.own_pid(), None);
        assert_eq!(rig.state(), HubState::Off);
        assert_eq!(rig.sup.restarts, 0);
    }

    #[test]
    fn a_hub_that_ignores_sigterm_is_killed_after_the_timeout() {
        let mut rig = Rig::new("stubborn", "trap '' TERM; while :; do sleep 0.05; done");
        rig.sup.timings.stop_timeout = Duration::from_millis(300);
        rig.sup.set_desired(true, Instant::now());
        let pid = rig.sup.own_pid().unwrap();
        settle();
        rig.sup.set_desired(false, Instant::now());
        rig.run_until(Duration::from_secs(3), |s| s.own_pid().is_none());
        assert!(!alive(pid));
        assert!(rig.log_text().contains("SIGKILL"));
    }

    #[test]
    fn a_hub_started_elsewhere_is_never_duplicated() {
        let mut rig = Rig::new("elsewhere", LONG);
        let holder = rig.hold_lock(4242);
        rig.sup.set_desired(true, Instant::now());
        rig.run_until(Duration::from_millis(300), |_| false);
        assert_eq!(rig.sup.own_pid(), None);
        let view = rig.sup.view(Instant::now());
        assert_eq!(view.state, HubState::Elsewhere);
        assert_eq!(view.pid, Some(4242));
        assert!(!view.by_taubar);
        // Switching off does not touch it; the user is told how to stop it.
        let message = rig.sup.set_desired(false, Instant::now()).unwrap();
        assert!(message.contains("pid 4242") && message.contains("tau hub stop"));
        // With the switch on again, TauBar starts its own once the other one is gone.
        rig.sup.set_desired(true, Instant::now());
        assert_eq!(rig.sup.own_pid(), None);
        drop(holder);
        rig.run_until(Duration::from_secs(2), |s| s.own_pid().is_some());
        assert!(rig.sup.own_pid().is_some());
        assert!(rig
            .log_text()
            .contains("the hub started elsewhere has stopped"));
    }

    #[test]
    fn a_hub_answering_on_the_port_counts_as_elsewhere_with_the_switch_off() {
        let mut rig = Rig::new("answer", LONG);
        rig.answer_health(777);
        rig.run_until(Duration::from_millis(200), |_| false);
        let view = rig.sup.view(Instant::now());
        assert_eq!(view.state, HubState::Elsewhere);
        assert_eq!(view.pid, Some(777));
        assert!(rig
            .sup
            .set_desired(false, Instant::now())
            .unwrap()
            .contains("pid 777"));
    }

    #[test]
    fn a_launchd_owned_data_dir_is_left_to_launchd() {
        let mut rig = Rig::new("launchd", LONG);
        *rig.probe.launchd.lock().unwrap() = true;
        rig.sup.set_desired(true, Instant::now());
        rig.run_until(Duration::from_millis(200), |_| false);
        assert_eq!(rig.sup.own_pid(), None);
        assert_eq!(rig.state(), HubState::LaunchdIdle);
        assert!(rig.log_text().contains("leaves the hub to launchd"));
    }

    #[test]
    fn an_orphaned_hub_from_an_earlier_taubar_is_adopted_and_supervised() {
        let mut rig = Rig::new("adopt", LONG);
        // The orphan: a process whose pid sits in the hub lock, as `tau hub run` writes it.
        let mut orphan = std::process::Command::new("/bin/sh")
            .args(["-c", LONG])
            .spawn()
            .unwrap();
        let holder = rig.hold_lock(orphan.id());
        assert!(!rig.sup.adopt(orphan.id() + 1, Instant::now()), "wrong pid");
        assert!(rig.sup.adopt(orphan.id(), Instant::now()));
        rig.sup.set_desired(true, Instant::now());
        assert_eq!(rig.sup.own_pid(), Some(orphan.id()));
        assert!(rig.sup.view(Instant::now()).by_taubar);
        // It dies without a clean stop (no state.json): TauBar restarts a hub of its own.
        let _ = orphan.kill();
        let _ = orphan.wait();
        drop(holder);
        rig.run_until(Duration::from_secs(2), |s| {
            s.own_pid().is_some_and(|pid| pid != orphan.id())
        });
        assert!(rig.sup.own_pid().is_some_and(|pid| pid != orphan.id()));
        assert_eq!(
            rig.sup.view(Instant::now()).last_exit.unwrap().reason,
            "exited without a clean stop"
        );
    }

    #[test]
    fn shutdown_stops_the_hub() {
        let mut rig = Rig::new("shutdown", LONG);
        rig.sup.set_desired(true, Instant::now());
        let pid = rig.sup.own_pid().unwrap();
        rig.sup.shutdown(Duration::from_secs(3));
        assert_eq!(rig.sup.own_pid(), None);
        assert!(!alive(pid));
        assert!(!rig.sup.desired());
    }

    #[test]
    fn missing_settings_mean_not_configured_and_no_start() {
        let mut rig = Rig::new("unset", LONG);
        rig.sup.configure(Err("the hub's Python is not set".into()));
        rig.sup.set_desired(true, Instant::now());
        assert_eq!(rig.sup.own_pid(), None);
        let view = rig.sup.view(Instant::now());
        assert_eq!(view.state, HubState::NotConfigured);
        assert!(view.problem.unwrap().contains("Python"));
    }

    #[test]
    fn a_missing_python_is_reported_by_configure() {
        let mut rig = Rig::new("nopython", LONG);
        let launch = Launch {
            program: rig.dir.join("no-such-python"),
            args: vec![],
            cwd: rig.dir.clone(),
            env: BTreeMap::new(),
        };
        rig.sup.configure(Ok(HubCommands {
            run: launch.clone(),
            status: launch,
        }));
        assert_eq!(rig.state(), HubState::NotConfigured);
    }
}
