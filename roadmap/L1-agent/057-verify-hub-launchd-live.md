# 057 · Verify the `tau hub` launchd agent live (install, kill -9 relaunch, uninstall)

Status: needs-triage
Type: HITL
Layer: L1 · Agent
Packages: tau-core, infra/services
Blocked by: none

## What to build

Issue #009 tested `tau hub install|uninstall` only with `FakeLaunchctl`, because the agent run must not load a real launch agent. The relaunch settings are in the plist (`KeepAlive` only on unsuccessful exit, `ThrottleInterval` 3), but nobody has watched launchd actually bring the hub back.

On the Mac, from a Terminal in the logged-in GUI session (the `gui/<uid>` domain is not available over SSH without one), follow the steps in `infra/services/README.md`.

## Acceptance criteria

- [ ] `uv run tau hub install` then `uv run tau hub status` shows `launchd: kurulu ve yüklü` and `curl 127.0.0.1:7877/health` answers
- [ ] After `pkill -9 -f "tau_core hub run"`, within about 3 s `tau hub status` shows a new pid and `Son çökme: … unexpected exit (no clean shutdown)`
- [ ] `tau hub stop` leaves it stopped (no relaunch after a clean exit)
- [ ] `tau hub uninstall` removes the plist
- [ ] Any surprise is recorded under `## Comments` of #009 or as a new issue

## Blocked by

None - needs the user's machine and GUI session.

## Comments

- 2026-09-29: proposed by the agent that closed #009; the criterion was ticked there on FakeLaunchctl tests and this live check.
