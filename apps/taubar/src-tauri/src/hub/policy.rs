//! When TauBar restarts the hub, as pure functions.
//!
//! The hub's contract (`tau hub run`): exit 0 after a clean stop (SIGTERM, `tau hub stop`),
//! non-zero after a crash. TauBar mirrors launchd's `KeepAlive = {SuccessfulExit = false}`:
//!
//! - an exit TauBar asked for (switch off, quit) is final;
//! - exit 0 without TauBar asking (`tau hub stop`) leaves the hub stopped;
//! - anything else (a crash, `kill -9`, a failed start) is restarted after a backoff: 1 s, 2 s,
//!   4 s … up to 60 s, back to 1 s once a run lasted a minute.

use std::time::Duration;

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ExitKind {
    /// TauBar asked it to stop (switch off, quit).
    Requested,
    /// Exit code 0 without TauBar asking: `tau hub stop` or a SIGTERM from someone else.
    Clean,
    /// Anything else, with a short reason (`exit code 1`, `killed by SIGKILL`).
    Crash(String),
}

impl ExitKind {
    pub fn restarts(&self) -> bool {
        matches!(self, ExitKind::Crash(_))
    }
}

/// Classify an exit from the exit code (`None` when a signal ended the process) and the signal.
pub fn classify(code: Option<i32>, signal: Option<i32>, stop_requested: bool) -> ExitKind {
    if stop_requested {
        return ExitKind::Requested;
    }
    match (code, signal) {
        (Some(0), _) => ExitKind::Clean,
        (Some(code), _) => ExitKind::Crash(format!("exit code {code}")),
        (None, Some(signal)) => ExitKind::Crash(format!("killed by {}", signal_name(signal))),
        (None, None) => ExitKind::Crash("exit status unknown".into()),
    }
}

pub fn signal_name(signal: i32) -> String {
    let name = match signal {
        1 => "SIGHUP",
        2 => "SIGINT",
        3 => "SIGQUIT",
        6 => "SIGABRT",
        9 => "SIGKILL",
        10 => "SIGBUS",
        11 => "SIGSEGV",
        13 => "SIGPIPE",
        15 => "SIGTERM",
        _ => return format!("signal {signal}"),
    };
    name.to_string()
}

#[derive(Clone, Debug)]
pub struct RestartPolicy {
    pub first_delay: Duration,
    pub max_delay: Duration,
    /// A run at least this long resets the backoff.
    pub stable_after: Duration,
    failures: u32,
}

impl Default for RestartPolicy {
    fn default() -> Self {
        Self {
            first_delay: Duration::from_secs(1),
            max_delay: Duration::from_secs(60),
            stable_after: Duration::from_secs(60),
            failures: 0,
        }
    }
}

impl RestartPolicy {
    /// How long to wait before restarting a hub that crashed after running for `uptime`.
    pub fn next_delay(&mut self, uptime: Duration) -> Duration {
        if uptime >= self.stable_after {
            self.failures = 0;
        }
        let factor = 1u32.checked_shl(self.failures.min(20)).unwrap_or(u32::MAX);
        let delay = self.first_delay.saturating_mul(factor).min(self.max_delay);
        self.failures = self.failures.saturating_add(1);
        delay
    }

    /// Crashes in a row since the last stable run or reset.
    pub fn failures(&self) -> u32 {
        self.failures
    }

    /// Forget earlier crashes (the switch was turned on again, or a clean stop).
    pub fn reset(&mut self) {
        self.failures = 0;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const SHORT: Duration = Duration::from_secs(2);

    #[test]
    fn requested_stops_are_final_whatever_the_code() {
        assert_eq!(classify(Some(0), None, true), ExitKind::Requested);
        assert_eq!(classify(None, Some(9), true), ExitKind::Requested);
        assert!(!ExitKind::Requested.restarts());
    }

    #[test]
    fn a_clean_exit_is_not_restarted() {
        assert_eq!(classify(Some(0), None, false), ExitKind::Clean);
        assert!(!ExitKind::Clean.restarts());
    }

    #[test]
    fn crashes_and_kills_are_restarted() {
        assert_eq!(
            classify(Some(1), None, false),
            ExitKind::Crash("exit code 1".into())
        );
        assert_eq!(
            classify(None, Some(9), false),
            ExitKind::Crash("killed by SIGKILL".into())
        );
        assert_eq!(
            classify(None, Some(64), false),
            ExitKind::Crash("killed by signal 64".into())
        );
        assert!(classify(Some(2), None, false).restarts());
    }

    #[test]
    fn backoff_doubles_up_to_the_cap() {
        let mut policy = RestartPolicy::default();
        let delays: Vec<u64> = (0..9).map(|_| policy.next_delay(SHORT).as_secs()).collect();
        assert_eq!(delays, [1, 2, 4, 8, 16, 32, 60, 60, 60]);
        assert_eq!(policy.failures(), 9);
    }

    #[test]
    fn a_stable_run_resets_the_backoff() {
        let mut policy = RestartPolicy::default();
        for _ in 0..4 {
            policy.next_delay(SHORT);
        }
        assert_eq!(
            policy.next_delay(Duration::from_secs(60)),
            Duration::from_secs(1)
        );
        assert_eq!(policy.next_delay(SHORT), Duration::from_secs(2));
    }

    #[test]
    fn reset_forgets_earlier_crashes() {
        let mut policy = RestartPolicy::default();
        policy.next_delay(SHORT);
        policy.next_delay(SHORT);
        policy.reset();
        assert_eq!(policy.next_delay(SHORT), Duration::from_secs(1));
    }

    #[test]
    fn the_first_restart_after_a_kill_comes_within_the_5_s_the_issue_asks_for() {
        let mut policy = RestartPolicy::default();
        assert!(policy.next_delay(Duration::from_secs(3600)) <= Duration::from_secs(1));
    }
}
