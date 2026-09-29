# 057 · Verify the `tau hub` launchd agent live (install, kill -9 relaunch, uninstall)

Status: in-progress
Type: HITL
Layer: L1 · Agent
Packages: tau-core, infra/services
Blocked by: none

## What to build

Issue #009 tested `tau hub install|uninstall` only with `FakeLaunchctl`, because the agent run must not load a real launch agent. The relaunch settings are in the plist (`KeepAlive` only on unsuccessful exit, `ThrottleInterval` 3), but nobody has watched launchd actually bring the hub back.

On the Mac, from a Terminal in the logged-in GUI session (the `gui/<uid>` domain is not available over SSH without one), follow the steps in `infra/services/README.md`.

## Acceptance criteria

- [ ] `uv run tau hub install` then `uv run tau hub status` shows launchd as installed and loaded and `curl 127.0.0.1:7877/health` answers
- [ ] After `pkill -9 -f "tau_core hub run"`, within about 3 s `tau hub status` shows a new pid and a last-crash line ending in `unexpected exit (no clean shutdown)`
- [ ] `tau hub stop` leaves it stopped (no relaunch after a clean exit)
- [ ] `tau hub uninstall` removes the plist
- [ ] Any surprise is recorded under `## Comments` of #009 or as a new issue

## Blocked by

None - needs the user's machine and GUI session.

## Comments

- 2026-09-29: proposed by the agent that closed #009; the criterion was ticked there on FakeLaunchctl tests and this live check.
- 2026-09-29: triaged → ready-for-human (HITL, needs the GUI session on the Mac; steps in `infra/services/README.md`). `tau hub status` lines are plain English from 062 on, so the criteria quote their meaning, not the exact text.
- 2026-09-30: first live run (macOS 26.3.1 (a), 117 days since the last login, from a GUI terminal: `launchctl managername` = Aqua). Surprises: `tau hub install` bootstrapped the agent (`launchd: installed and loaded`) but launchd never started it: `runs = 0`, `pended nondemand spawn = semaphore`; `launchctl kickstart` started it at once. After `pkill -9 -f "tau_core hub run"` nothing came back within 30 s (`last terminating signal = Killed: 9`, `pended nondemand spawn = semaphore`). The next start recorded the crash correctly (`unexpected exit (no clean shutdown)`). Throwaway `/bin/sleep` agents show it is not the hub's plist: in this `gui/501` domain launchd pends every non-demand spawn: `RunAtLoad` (speculative), `KeepAlive = true` after `kill -9` (inefficient), `SuccessfulExit = false` after `exit 1` (semaphore) and even `StartInterval` (interval); only `kickstart` (a demand spawn) runs. Background Task Management lists `com.tau.hub` as enabled and allowed; no low-power mode, thermal or memory pressure. Same symptom as 052. Open: does a fresh login restore launchd's automatic spawns? If not, the hub needs a restart path that does not depend on launchd `KeepAlive`.
