# 084 · TauBar runs the hub: on/off switch, restart after a crash, launch at login

Status: in-progress
Type: AFK
Layer: L4 · Interface
Packages: apps/taubar, tau-core
Blocked by: 024

## What to build

The background jobs of the Mac move under one app the user can see and switch. TauBar gets a "Run the hub" switch and a "Launch at login" switch (a native checkbox menu item), and when the hub switch is on it supervises `tau hub run` itself: it starts the hub as a child process, restarts it after an unclean exit (a crash or `kill -9`) with a short backoff, leaves it stopped after a clean exit (`tau hub stop`, exit 0) or when the user turns the switch off, and stops it when TauBar quits. The menu shows the hub's state from the control API (`GET /health`, `GET /status`: up/down, pid, uptime, last crash, the Telegram poller state).

Why: on the user's Mac (macOS 26.3.1) launchd pends every non-demand spawn of a user agent, so neither `RunAtLoad` nor `KeepAlive` in `com.tau.hub.plist` brings the hub up or back (see 057 and 052); only `launchctl kickstart` works. A supervisor inside TauBar does not depend on that, and it is the place where the user already expects to switch background jobs on and off.

- The hub command and the checkout come from TauBar's settings (default: the `tau` checkout's `uv run tau hub run`, or `<venv>/bin/python -m tau_core hub run` with `TAU_HOME`); nothing personal is hard-coded or committed.
- If a hub is already running (the hub lock, `tau hub status`, or a launchd-managed `com.tau.hub`), TauBar shows it and does not start a second one; turning the switch off stops only a hub TauBar started, or tells the user how to stop the other one.
- "Launch at login" registers TauBar itself as a login item (prefer `SMAppService`; verify it actually starts at login on this Mac, because launchd agents with `RunAtLoad` did not start mid-session here).
- Hub logs keep going to `TAU_DATA_DIR/logs/tau.log`; TauBar keeps its own short log of starts, exits and restarts.

## Acceptance criteria

- [ ] Turning "Run the hub" on starts the hub; `/health` answers within a few seconds and the menu shows it as up
- [ ] `pkill -9 -f "tau_core hub run"` → TauBar restarts the hub within about 5 s; the new hub reports the crash (`unexpected exit (no clean shutdown)`)
- [ ] `tau hub stop` or turning the switch off leaves the hub stopped; quitting TauBar stops a hub it started
- [ ] A hub started elsewhere is detected and never duplicated
- [ ] "Launch at login" is a checkbox that survives restarts and actually starts TauBar at the next login
- [ ] The switches' state persists across TauBar restarts
- [ ] `infra/services/README.md` and the docs explain TauBar as the macOS default and launchd as the alternative

## Blocked by

- [024 · TauBar v0: tray app with sleep modes](024-taubar-sleep-modes.md)

## Comments

- 2026-09-30: opened at the user's request after 057 found launchd pending every automatic spawn on this Mac; the user wants background jobs switchable from TauBar ("Launch at login" style checkboxes).
