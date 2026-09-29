//! The three sleep modes.
//!
//! - **Normal**: TauBar holds nothing; the Mac sleeps as usual.
//! - **Keep awake on AC power** (default): an IOKit `PreventSystemSleep` assertion, the same
//!   thing `caffeinate -s` creates. No root needed. macOS honours it only on AC power, so on
//!   battery and with the lid closed the Mac still sleeps.
//! - **Keep awake with the lid closed**: the assertion plus `pmset -a disablesleep 1`, run as
//!   `sudo -n` through a sudoers rule that allows only `pmset -a disablesleep 0` and `… 1`
//!   (`apps/taubar/sudoers/`). Without the rule the mode is unavailable and TauBar never calls
//!   sudo.
//!
//! [`SleepController`] holds the mode logic; the system calls sit behind [`Power`] so tests
//! use a fake. Quitting TauBar calls [`SleepController::restore`]: the assertion is released
//! and `disablesleep` is reset if TauBar set it. (macOS also drops a process's assertions when
//! it dies; `disablesleep` survives a crash, so TauBar remembers it set it and resets it at the
//! next start.)

use crate::settings::SleepMode;
use serde::Serialize;

/// Installed by `apps/taubar/sudoers/install-sudoers.sh`; its presence is how TauBar knows
/// the lid-closed mode is available without ever running sudo to find out.
pub const SUDOERS_RULE_PATH: &str = "/etc/sudoers.d/tau-taubar";
pub const PMSET: &str = "/usr/bin/pmset";
pub const SUDO: &str = "/usr/bin/sudo";
/// The name `pmset -g assertions` shows next to TauBar's assertion (`doctor.sh` looks for it).
pub const ASSERTION_NAME: &str = "TauBar keeps the Mac awake for tau";

/// The system calls behind the sleep modes.
pub trait Power {
    /// Hold (`true`) or release (`false`) the `PreventSystemSleep` assertion. Idempotent.
    fn set_assertion(&mut self, held: bool) -> Result<(), String>;
    /// `sudo -n pmset -a disablesleep 1|0`.
    fn set_sleep_disabled(&mut self, disabled: bool) -> Result<(), String>;
    /// `SleepDisabled` from `pmset -g`; `None` when pmset could not be read.
    fn sleep_disabled(&self) -> Option<bool>;
    /// Whether the narrow sudoers rule is installed.
    fn lid_rule_installed(&self) -> bool;
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct SleepStatus {
    /// What the user picked.
    pub wanted: SleepMode,
    /// What is in force (differs from `wanted` when the lid mode had to fall back).
    pub effective: SleepMode,
    /// The sudoers rule is installed, so the lid-closed mode can be picked.
    pub lid_available: bool,
    /// Sleep is disabled system-wide (`pmset disablesleep 1`) although TauBar did not do it.
    pub disabled_elsewhere: bool,
    /// A problem worth showing (fallback, failed command).
    pub problem: Option<String>,
}

pub struct SleepController<P: Power> {
    power: P,
    lid_engaged: bool,
    status: SleepStatus,
}

impl<P: Power> SleepController<P> {
    /// `lid_engaged`: TauBar's previous run set `disablesleep 1` and never reset it (it was
    /// killed or crashed). The next [`apply`](Self::apply) resets it unless the lid mode is
    /// wanted again.
    pub fn new(power: P, lid_engaged: bool) -> Self {
        Self {
            power,
            lid_engaged,
            status: SleepStatus {
                wanted: SleepMode::Normal,
                effective: SleepMode::Normal,
                lid_available: false,
                disabled_elsewhere: false,
                problem: None,
            },
        }
    }

    pub fn status(&self) -> &SleepStatus {
        &self.status
    }

    /// TauBar set `disablesleep 1` and has not reset it; persisted so a crash can be undone.
    pub fn lid_engaged(&self) -> bool {
        self.lid_engaged
    }

    pub fn power(&self) -> &P {
        &self.power
    }

    /// Put `wanted` in force, falling back to "keep awake on AC" when the lid mode cannot be
    /// used.
    pub fn apply(&mut self, wanted: SleepMode) -> &SleepStatus {
        let lid_available = self.power.lid_rule_installed();
        let mut problem = None;
        let mut effective = wanted;

        if wanted == SleepMode::KeepAwakeLidClosed {
            if !lid_available {
                effective = SleepMode::KeepAwakeOnAc;
                problem = Some(
                    "the lid-closed mode needs the sudoers rule (apps/taubar/sudoers); \
                     keeping awake on AC power instead"
                        .to_string(),
                );
            } else {
                match self.power.set_sleep_disabled(true) {
                    Ok(()) => self.lid_engaged = true,
                    Err(err) => {
                        effective = SleepMode::KeepAwakeOnAc;
                        problem = Some(format!(
                            "pmset disablesleep 1 failed ({err}); keeping awake on AC power instead"
                        ));
                    }
                }
            }
        }

        if effective != SleepMode::KeepAwakeLidClosed && self.lid_engaged {
            if let Some(err) = self.release_lid() {
                problem = Some(err);
            }
        }

        if let Err(err) = self.power.set_assertion(effective != SleepMode::Normal) {
            problem = Some(format!("the keep-awake assertion failed: {err}"));
            if effective == SleepMode::KeepAwakeOnAc {
                effective = SleepMode::Normal;
            }
        }

        let disabled_elsewhere = !self.lid_engaged && self.power.sleep_disabled() == Some(true);
        self.status = SleepStatus {
            wanted,
            effective,
            lid_available,
            disabled_elsewhere,
            problem,
        };
        &self.status
    }

    /// Undo everything TauBar holds (quit): release the assertion, reset `disablesleep`.
    /// Returns a problem to log, if any.
    pub fn restore(&mut self) -> Option<String> {
        let mut problem = None;
        if self.lid_engaged {
            problem = self.release_lid();
        }
        if let Err(err) = self.power.set_assertion(false) {
            problem = Some(format!("could not release the keep-awake assertion: {err}"));
        }
        self.status.effective = SleepMode::Normal;
        problem
    }

    /// `disablesleep 0`. When sudo refuses (the rule was just removed) but pmset already shows
    /// sleep enabled (the uninstall script reset it), there is nothing left to undo.
    fn release_lid(&mut self) -> Option<String> {
        match self.power.set_sleep_disabled(false) {
            Ok(()) => {
                self.lid_engaged = false;
                None
            }
            Err(_) if self.power.sleep_disabled() == Some(false) => {
                self.lid_engaged = false;
                None
            }
            Err(err) => Some(format!(
                "could not re-enable sleep ({err}); run: sudo pmset -a disablesleep 0"
            )),
        }
    }
}

/// `SleepDisabled` from `pmset -g` output. macOS prints the line only when it is set, so a
/// missing line means sleep is not disabled.
pub fn parse_sleep_disabled(pmset_g: &str) -> bool {
    pmset_g.lines().any(|line| {
        let mut parts = line.split_whitespace();
        parts.next() == Some("SleepDisabled") && parts.next() == Some("1")
    })
}

/// The real system on macOS.
#[cfg(target_os = "macos")]
#[derive(Default)]
pub struct SystemPower {
    awake: Option<keepawake::KeepAwake>,
}

#[cfg(target_os = "macos")]
impl SystemPower {
    pub fn new() -> Self {
        Self::default()
    }
}

#[cfg(target_os = "macos")]
impl Power for SystemPower {
    fn set_assertion(&mut self, held: bool) -> Result<(), String> {
        if !held {
            self.awake = None; // dropping releases the assertion
            return Ok(());
        }
        if self.awake.is_none() {
            let awake = keepawake::Builder::default()
                .sleep(true)
                .reason(ASSERTION_NAME)
                .app_name("TauBar")
                .app_reverse_domain("com.tau.taubar")
                .create()
                .map_err(|e| e.to_string())?;
            self.awake = Some(awake);
        }
        Ok(())
    }

    fn set_sleep_disabled(&mut self, disabled: bool) -> Result<(), String> {
        let value = if disabled { "1" } else { "0" };
        // -n: never prompt. Without the sudoers rule sudo fails at once instead of waiting.
        let output = std::process::Command::new(SUDO)
            .args(["-n", PMSET, "-a", "disablesleep", value])
            .stdin(std::process::Stdio::null())
            .output()
            .map_err(|e| format!("sudo could not be run: {e}"))?;
        if output.status.success() {
            Ok(())
        } else {
            let stderr = String::from_utf8_lossy(&output.stderr);
            Err(stderr
                .lines()
                .next()
                .unwrap_or("sudo failed")
                .trim()
                .to_string())
        }
    }

    fn sleep_disabled(&self) -> Option<bool> {
        let output = std::process::Command::new(PMSET).arg("-g").output().ok()?;
        output
            .status
            .success()
            .then(|| parse_sleep_disabled(&String::from_utf8_lossy(&output.stdout)))
    }

    fn lid_rule_installed(&self) -> bool {
        std::path::Path::new(SUDOERS_RULE_PATH).exists()
    }
}

/// Other platforms: every mode but Normal reports that it is macOS only.
#[cfg(not(target_os = "macos"))]
pub struct SystemPower;

#[cfg(not(target_os = "macos"))]
impl SystemPower {
    pub fn new() -> Self {
        Self
    }
}

#[cfg(not(target_os = "macos"))]
impl Power for SystemPower {
    fn set_assertion(&mut self, held: bool) -> Result<(), String> {
        if held {
            Err("sleep modes are only available on macOS".into())
        } else {
            Ok(())
        }
    }
    fn set_sleep_disabled(&mut self, _disabled: bool) -> Result<(), String> {
        Err("sleep modes are only available on macOS".into())
    }
    fn sleep_disabled(&self) -> Option<bool> {
        None
    }
    fn lid_rule_installed(&self) -> bool {
        false
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[derive(Default)]
    struct FakePower {
        rule: bool,
        pmset_fails: bool,
        assertion: bool,
        sleep_disabled: bool,
        calls: Vec<String>,
    }

    impl Power for FakePower {
        fn set_assertion(&mut self, held: bool) -> Result<(), String> {
            self.calls.push(format!("assertion {held}"));
            self.assertion = held;
            Ok(())
        }
        fn set_sleep_disabled(&mut self, disabled: bool) -> Result<(), String> {
            self.calls.push(format!("disablesleep {}", disabled as u8));
            if self.pmset_fails {
                return Err("sudo: a password is required".into());
            }
            self.sleep_disabled = disabled;
            Ok(())
        }
        fn sleep_disabled(&self) -> Option<bool> {
            Some(self.sleep_disabled)
        }
        fn lid_rule_installed(&self) -> bool {
            self.rule
        }
    }

    fn controller(power: FakePower) -> SleepController<FakePower> {
        SleepController::new(power, false)
    }

    #[test]
    fn keep_awake_on_ac_holds_only_the_assertion() {
        let mut c = controller(FakePower::default());
        let status = c.apply(SleepMode::KeepAwakeOnAc).clone();
        assert_eq!(status.effective, SleepMode::KeepAwakeOnAc);
        assert!(status.problem.is_none());
        assert!(c.power.assertion);
        assert_eq!(c.power.calls, ["assertion true"]);
    }

    #[test]
    fn normal_releases_the_assertion() {
        let mut c = controller(FakePower::default());
        c.apply(SleepMode::KeepAwakeOnAc);
        c.apply(SleepMode::Normal);
        assert!(!c.power.assertion);
        assert_eq!(c.status().effective, SleepMode::Normal);
    }

    #[test]
    fn lid_mode_without_the_rule_falls_back_and_never_calls_sudo() {
        let mut c = controller(FakePower::default());
        let status = c.apply(SleepMode::KeepAwakeLidClosed).clone();
        assert_eq!(status.wanted, SleepMode::KeepAwakeLidClosed);
        assert_eq!(status.effective, SleepMode::KeepAwakeOnAc);
        assert!(!status.lid_available);
        assert!(status.problem.unwrap().contains("sudoers rule"));
        assert!(!c
            .power
            .calls
            .iter()
            .any(|call| call.starts_with("disablesleep")));
        assert!(c.power.assertion);
    }

    #[test]
    fn lid_mode_with_the_rule_disables_sleep_and_restores_it() {
        let mut c = controller(FakePower {
            rule: true,
            ..Default::default()
        });
        let status = c.apply(SleepMode::KeepAwakeLidClosed).clone();
        assert_eq!(status.effective, SleepMode::KeepAwakeLidClosed);
        assert!(c.power.sleep_disabled && c.power.assertion && c.lid_engaged());

        c.apply(SleepMode::KeepAwakeOnAc);
        assert!(!c.power.sleep_disabled && c.power.assertion && !c.lid_engaged());

        c.apply(SleepMode::KeepAwakeLidClosed);
        assert!(c.restore().is_none());
        assert!(!c.power.sleep_disabled && !c.power.assertion && !c.lid_engaged());
    }

    #[test]
    fn lid_mode_falls_back_when_sudo_refuses() {
        let mut c = controller(FakePower {
            rule: true,
            pmset_fails: true,
            ..Default::default()
        });
        let status = c.apply(SleepMode::KeepAwakeLidClosed).clone();
        assert_eq!(status.effective, SleepMode::KeepAwakeOnAc);
        assert!(status.problem.unwrap().contains("password is required"));
        assert!(!c.lid_engaged());
    }

    #[test]
    fn a_crashed_run_is_undone_at_the_next_start() {
        let power = FakePower {
            rule: true,
            sleep_disabled: true,
            ..Default::default()
        };
        let mut c = SleepController::new(power, true);
        c.apply(SleepMode::KeepAwakeOnAc);
        assert!(!c.power.sleep_disabled);
        assert!(!c.lid_engaged());
        assert!(!c.status().disabled_elsewhere);
    }

    #[test]
    fn sleep_disabled_by_someone_else_is_reported_not_touched() {
        let mut c = controller(FakePower {
            rule: true,
            sleep_disabled: true,
            ..Default::default()
        });
        let status = c.apply(SleepMode::Normal).clone();
        assert!(status.disabled_elsewhere);
        assert!(c.power.sleep_disabled);
        assert!(!c
            .power
            .calls
            .iter()
            .any(|call| call.starts_with("disablesleep")));
    }

    #[test]
    fn a_removed_rule_after_the_uninstall_script_reset_sleep_is_not_a_problem() {
        let power = FakePower {
            rule: false,
            pmset_fails: true,
            sleep_disabled: false,
            ..Default::default()
        };
        let mut c = SleepController::new(power, true);
        let status = c.apply(SleepMode::KeepAwakeLidClosed).clone();
        assert_eq!(status.effective, SleepMode::KeepAwakeOnAc);
        assert!(!c.lid_engaged());
        assert!(status.problem.unwrap().contains("sudoers rule"));
    }

    #[test]
    fn a_failed_reset_is_reported_while_sleep_stays_disabled() {
        let power = FakePower {
            rule: true,
            pmset_fails: true,
            sleep_disabled: true,
            ..Default::default()
        };
        let mut c = SleepController::new(power, true);
        let problem = c.restore().unwrap();
        assert!(problem.contains("sudo pmset -a disablesleep 0"));
        assert!(c.lid_engaged());
        assert!(!c.power.assertion);
    }

    #[test]
    fn parses_pmset_g() {
        let off = " Sleep On Power Button 1\n sleep                1\n displaysleep         0\n";
        let on = " SleepDisabled\t\t1\n sleep                0\n";
        let zero = " SleepDisabled\t\t0\n";
        assert!(!parse_sleep_disabled(off));
        assert!(parse_sleep_disabled(on));
        assert!(!parse_sleep_disabled(zero));
    }
}
