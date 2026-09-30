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

- [x] Turning "Run the hub" on starts the hub; `/health` answers within a few seconds and the menu shows it as up
- [x] `pkill -9 -f "tau_core hub run"` → TauBar restarts the hub within about 5 s; the new hub reports the crash (`unexpected exit (no clean shutdown)`)
- [x] `tau hub stop` or turning the switch off leaves the hub stopped; quitting TauBar stops a hub it started
- [x] A hub started elsewhere is detected and never duplicated
- [ ] "Launch at login" is a checkbox that survives restarts and actually starts TauBar at the next login
- [x] The switches' state persists across TauBar restarts
- [x] `infra/services/README.md` and the docs explain TauBar as the macOS default and launchd as the alternative

## Blocked by

- [024 · TauBar v0: tray app with sleep modes](024-taubar-sleep-modes.md)

## Comments

- 2026-09-30: opened at the user's request after 057 found launchd pending every automatic spawn on this Mac; the user wants background jobs switchable from TauBar ("Launch at login" style checkboxes).
- 2026-09-30: built by an agent right after 024 (024 stays in-progress only for checks that need the user). Commits b7cc689 (`tau hub status --json` adds `control_port`, `data_dir`, `hub_dir`, `lock`), b596628 (the supervisor: `apps/taubar/src-tauri/src/hub/`, wired into the menu, the window and a 1 s supervisor thread), 297b0bc (the doctor test no longer probes the live hub's port; see 082), 4596768 (docs). TauBar starts `<python> -m tau_core hub run` as its direct child in `TAU_HOME` with an explicit environment; restart after an unclean exit after 1 s, doubling to 60 s, reset after a minute-long run; a clean exit it did not ask for turns the switch off for the session (the saved switch still starts the hub at the next TauBar start, like launchd's `RunAtLoad`); switch off and quit send SIGTERM. Before every start it runs `tau hub status --json` and probes that data dir's hub lock; a loaded `com.tau.hub` agent whose plist has the same `TAU_DATA_DIR` keeps the hub. An orphaned hub of a crashed TauBar is adopted through `hub_pid` in `state.json` plus the lock. First start imports Python/`TAU_HOME`/`TAU_DATA_DIR`/`PATH` from an installed `com.tau.hub.plist`. `cargo test`: 59 (13 supervisor tests run real `/bin/sh` children: crash backoff, kill -9, clean exit, switch off, SIGTERM-deaf hub, foreign lock holder, launchd-owned data dir, adoption, shutdown); vitest: 9.
  Verified live with an isolated hub (fake provider, own `TAU_HOME`/`TAU_DATA_DIR`, port 7897, `TELEGRAM_BOT_TOKEN=` empty), driving TauBar's window through System Events; the live launchd hub (port 7877) was only read (`/health`) and kept its pid throughout. (1) Switch on → "hub: pid … is up (/health answered after 1.0 s)"; the window (same strings as the menu) showed `Hub: up 15 s · pid …`, `Telegram: off (TELEGRAM_BOT_TOKEN is not set)`, `Last crash: none`. (2) `kill -9 <pid>` (not `pkill -f`, which would also have killed the live hub) → restarted within 1.3 s, and the new hub's `/status` had `last_crash.reason = "unexpected exit (no clean shutdown)"`. (3) `tau hub stop` → "exited cleanly without TauBar asking … leaving it stopped", no restart; switch off → SIGTERM, stopped in about 1 s, no restart; SIGTERM to TauBar and the window's Quit button each stopped the hub first. (4) A hub started by hand showed as `started outside TauBar`; switching on logged "not starting a second one" (still one test hub); switching off left it running and showed how to stop it; after `tau hub stop` on it TauBar started its own. With the real setup (fresh TauBar home, switch off) TauBar imported the plist and showed the live hub as `up 1 h 5 min · pid … · run by launchd` with the Telegram poller line, without touching it. (5) `kill -9` of TauBar itself: its hub kept running; the next TauBar logged "took over the hub an earlier TauBar started" and restarted it after a `kill -9`. (6) With the switch on, a TauBar restart logged "run the hub: on (saved setting)" and started the hub; the login item stayed registered across a TauBar restart (then unregistered again).
  Not verified: that TauBar (and with it the hub) actually starts at the next login; nobody logged out. The tray menu could not be clicked in tests because macOS hid TauBar's icon (full menu bar, see 024); menu and window call the same code. Follow-ups: 085 (start/restart TauBar's hub from the phone), 086 (TauBar UI language), 087 (`tau hub status`'s launchd line ignores the data dir). Once TauBar runs the hub on this Mac, 057 and 052 matter only for the launchd alternative.
- 2026-09-30: live on the user's Mac. TauBar installed in `/Applications`, "Launch at login" ticked (SMAppService), "Run the hub" ticked; `tau hub uninstall` removed the launchd agent and TauBar started the hub itself (new pid, parent `taubar`, Telegram polling with the new code). `kill -9 <hub pid>` → TauBar had a new hub up in 1.8 s, and it reported `unexpected exit (no clean shutdown)` for the killed pid. The Telegram poller then took 32 s to poll again (090). Still open: a start at a real login.
- 2026-09-30: a second TauBar (the release build in the checkout) had been started beside the `/Applications` copy and was the one supervising the hub and registered for login; quitting it left the hub down until the `/Applications` copy was restarted (091). Now one TauBar runs from `/Applications`, it started the hub 2 s after launch, and the login item points at `/Applications/TauBar.app`. The start at a real login is still unverified: the Mac has not been restarted or logged out (uptime 118 days).

