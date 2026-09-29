# 052 · Keep-awake agent is loaded but never runs, and `doctor.sh` calls it running

Status: ready-for-agent
Type: AFK
Layer: L0 · Remote access
Packages: infra/remote
Blocked by: none

## What to build

On AC power the Mac must stay awake so the phone can reach it. `setup.sh` bootstraps `com.tau.keepawake` (`caffeinate -s`, `RunAtLoad`, `KeepAlive`, `ProcessType Background`), but the job never started, so nothing prevents sleep. `doctor.sh` only checks that the job is loaded, so it still reported the job as running. Make the agent actually run after `setup.sh` and after a reboot, and make `doctor.sh` check what matters: a running process and the sleep assertion.

## Acceptance criteria

- [ ] After `setup.sh` on AC power, a `caffeinate -s` process owned by the job is running and `pmset -g assertions` shows `PreventSystemSleep 1`
- [ ] The same holds after logging out and in, and after a reboot
- [ ] `doctor.sh` reports a problem when the job is loaded but not running, and names the fix
- [ ] `doctor.sh` still passes on battery (where `-s` has no effect) without a false alarm
- [ ] `infra/remote/README.md` explains how to check it by hand

## Blocked by

None - can start immediately

## Notes

Found 2026-09-28 while closing #001, on AC power: `launchctl print gui/<uid>/com.tau.keepawake` shows `state = not running`, `runs = 0`, `pended nondemand spawn = speculative`, `spawn type = background (5)`; no `caffeinate -s` process; `PreventSystemSleep 0`. Likely causes to test: `ProcessType Background` lets launchd defer the `RunAtLoad` spawn indefinitely; `launchctl kickstart` right after `bootstrap` may be needed. Confirm the cause before fixing.

## Comments

- 2026-09-29: triaged → ready-for-agent. Real bug (on AC the Mac can sleep and the phone loses the hub). Confirm the cause from the Notes first; keep the fix minimal because TauBar (024) replaces this agent later. The launchd behaviour is verified by asking the user to run `launchctl print gui/<uid>/com.tau.keepawake` afterwards.
- 2026-09-30: probed while working on 057. `ProcessType Background` is not the cause: plain `/bin/sleep` agents without it are pended the same way in this login session (`RunAtLoad` speculative, `KeepAlive` inefficient, `StartInterval` interval), and `launchctl kickstart` runs them. So `setup.sh` needs a `kickstart` after `bootstrap`; whether launchd resumes automatic spawns after a fresh login is still to be checked (see 057).
