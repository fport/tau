# 009 · `tau hub` daemon with launchd service and self-heal

Status: done
Type: AFK
Layer: L1 · Agent
Packages: tau-core
Blocked by: 004

## What to build

`tau hub` runs tau as a long-lived process in the hub role (`TAU_ROLE=hub`), installed as a launchd user agent on macOS, with a systemd unit template for the future RPi5 hub. It restarts on crash and on the next start knows why it died. It exposes a local-only control API (health, status) for TauBar, hooks and other local processes.

## Acceptance criteria

- [x] `tau hub install|uninstall|status` manages the launchd agent
- [x] Killing the process relaunches it within seconds; the crash reason shows on the next `status`
- [x] The control API listens on 127.0.0.1 only and has a health endpoint
- [x] Only one hub instance can run per machine
- [x] A systemd unit template exists
- [x] Tests cover crash-report persistence and the single-instance lock

## Blocked by

- [004 · Tracer bullet: `tau chat` answers in the Jarvis persona](004-tau-chat-tracer-bullet.md)

## Comments

### 2026-09-29 · done (agent)

Built the hub daemon in `tau_core.hub`: `Hub` (lock → crash check → services in order → heartbeat
`state.json` → SIGTERM/SIGINT → services in reverse → `stopped_at`), `HubLock` (`flock` on
`<TAU_DATA_DIR>/hub/hub.lock`, pid inside, `AlreadyRunning` → exit 1 with the Turkish message),
`HubFiles`/`HubState`/`CrashReport` (`crash.json` marker, `crash_reports.jsonl`,
`last_crash.json`), `ControlApi` (`/health`, `/status` on 127.0.0.1, non-loopback `Host` → 403),
the `Launchctl` protocol with `SystemLaunchctl` and `FakeLaunchctl`, and package templates for
the launchd plist and systemd unit. `tau hub run|status|stop|install|uninstall|systemd-unit`
replace the placeholders; `infra/services/` has the templates rendered with placeholder paths
(a test keeps them in sync) and the install notes. `uv run ruff check . && uv run ruff format
--check . && uv run pytest -q` is green (125 tests, offline; 55 new in `tests/test_hub_*.py`).

Verified by hand in a scratch data dir: `tau hub run` answers `curl 127.0.0.1:<port>/health`,
refuses a second instance (exit 1), stops on SIGTERM and SIGINT with exit 0 and `stopped_at`
written; after `kill -9` the next start records `unexpected exit (no clean shutdown)` and both
`tau hub status` and `/status` show it. Not exercised live: `tau hub install` against the real
launchd (the agent run must not load a launch agent), so launchd's relaunch after a kill is
configured (`KeepAlive = {SuccessfulExit: false}`, `ThrottleInterval 3`) but not observed yet;
install/uninstall are tested with `FakeLaunchctl`. One manual check for the user: `uv run tau hub
install`, `pkill -9 -f "tau_core hub run"`, a few seconds later `uv run tau hub status` shows a
new pid and the crash (steps in `infra/services/README.md`).

Commits:
- `docs(roadmap): start 009`
- `feat(core): add the hub daemon, crash reports, lock and control API`
- `feat(core): add tau hub commands and the launchd/systemd service files`
- `docs: document the hub daemon and its service files`
- `fix(core): keep tau hub command listings on one line`
- `docs(roadmap): close 009`

Deviations from the shared brief: `crash.json` is written by `Hub.run()`'s own exception handler
instead of a global `sys.excepthook` (same effect for everything the hub runs, no global state in
tests); `tau hub stop` signals the lock holder's pid first and falls back to `state.json` (during
a start, `state.json` can still be the dead previous run's for a moment); `CrashReport` has an
extra `detected_at`; `/status` also carries `pid` and `uptime_s`; extra options `status --json`,
`stop --timeout`, `systemd-unit --python`; `tests/test_cli.py` no longer lists `hub status`/`hub
run` in `test_placeholders` (they are real commands now).

For the next issues:
- Services: a `HubService` has `name`, `async start(hub)`, `async stop()`; `tau hub run` wires
  `Hub(config)` + `ControlApi` + a banner in `hub/cli.py:run_command`. Hub-hosted channels (L3,
  `tau.channels`) get loaded there. The hub does not build an agent yet.
- 011 (spend) and others extend `/status` with `hub.add_status_source(lambda: {...})` from a
  service's `start`; base keys stay (`approvals_pending` is 0, `nodes` is null until filled).
- 025 (TauBar approvals): `ControlApi.add_route(method, path, handler)` matches exact paths (no
  patterns yet); handlers run in the HTTP server thread, so reach the loop with
  `asyncio.run_coroutine_threadsafe(coro, hub.loop)`. Keep the loopback `Host` check for POSTs.
- The Telegram status report can use `hub.crash_report` (what this start found) and
  `hub.state.last_crash`.
