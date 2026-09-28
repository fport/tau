# 024 · TauBar v0: tray app with sleep modes

Status: ready-for-agent
Type: AFK
Layer: L4 · Interface
Packages: apps/taubar
Blocked by: none

## What to build

A Tauri v2 + React/TS tray-only app (no Dock icon) whose menu offers three sleep modes: Normal; Keep awake on AC (default — an IOKit PreventSystemSleep assertion from Rust, no root); Keep awake even with the lid closed (through a sudoers rule limited to `pmset disablesleep 0|1`). The chosen mode persists across restarts. Once installed, TauBar replaces the `com.tau.keepawake` agent from `infra/remote`.

## Acceptance criteria

- [ ] Mode changes are visible in `pmset -g assertions` / `pmset -g`
- [ ] Lid-closed mode installs only the narrow sudoers rule and has an uninstall path
- [ ] Starts at login; no Dock icon
- [ ] Quitting or uninstalling TauBar restores normal sleep
- [ ] `infra/remote` updated: keepawake agent removed when TauBar is present; `doctor.sh` accepts either
- [ ] The .app build and signing steps are documented

## Blocked by

None - can start immediately

## Comments
