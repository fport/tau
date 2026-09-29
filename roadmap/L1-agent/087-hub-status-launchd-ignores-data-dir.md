# 087 · `tau hub status` reports the launchd agent for every data dir

Status: needs-triage
Type: AFK
Layer: L1 · Agent
Packages: tau-core
Blocked by: none

## What to build

`tau hub status` prints `launchd: installed and loaded (com.tau.hub)` whenever that label is loaded, whatever `TAU_DATA_DIR` the command runs with. For a second hub (a test hub, or TauBar pointed at another data dir) the line is wrong: the agent runs the hub of another data dir. Compare the agent's `TAU_DATA_DIR` (from its plist) with the configuration's and say which hub launchd runs, the way TauBar's launchd check does (084, `apps/taubar/src-tauri/src/hub/probe.rs`).

## Acceptance criteria

- [ ] With the agent loaded for data dir A, `tau hub status` for data dir B does not claim launchd runs B's hub
- [ ] `--json` tells the two cases apart
- [ ] Covered by FakeLaunchctl tests

## Blocked by

None - can start immediately.

## Comments

- 2026-09-30: found while testing 084 with an isolated test hub next to the live launchd hub.
