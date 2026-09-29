# 024 · TauBar v0: tray app with sleep modes

Status: in-progress
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
- [x] Quitting or uninstalling TauBar restores normal sleep
- [ ] `infra/remote` updated: keepawake agent removed when TauBar is present; `doctor.sh` accepts either
- [x] The .app build and signing steps are documented

## Blocked by

None - can start immediately

## Comments

- 2026-09-30: built by an agent (commits 4cfa59e, 69fd0b7, eb0ca12, 6afe2bb). `apps/taubar/` is a Tauri v2 app (Rust core, React/TS window): tray only (`LSUIElement` + `ActivationPolicy::Accessory`), a native menu with the three modes as radio-like check items, "Launch at login" through `SMAppService.mainApp` (not a LaunchAgent, because of 057/052), a window with the same switches and TauBar's log, and `apps/taubar/sudoers/` (rule, install and uninstall scripts). Settings in `~/Library/Application Support/com.tau.taubar/settings.json`, log in `~/Library/Logs/com.tau.taubar/taubar.log`; `TAUBAR_HOME` isolates both (all tests used it). Tests: `cargo test` (20: sleep controller against a fake `Power`, settings, log, menu labels) and `pnpm test` (vitest).
  Verified on this Mac (macOS 26.3.1, AC power), driving the window through System Events: the default mode showed `PreventSystemSleep 1` with `pid …(taubar): … named: "TauBar keeps the Mac awake for tau"`; Normal → `PreventSystemSleep 0`; back to AC → 1; the mode survived a restart (started again in Normal); the Quit button, the Quit path on SIGTERM and a LaunchServices start all ended with `PreventSystemSleep 0` and "TauBar quit; normal sleep restored" in the log. `lsappinfo` reports `ApplicationType = UIElement` (no Dock icon). The lid-closed item stays disabled ("needs setup") without `/etc/sudoers.d/tau-taubar`, and TauBar never called sudo. Ticking "Launch at login" registered the app (`Enabled`), unticking removed it (`NotRegistered`); it was left unregistered. `doctor.sh` was run in every branch (agent only → ok; TauBar installed but not running → problem; TauBar in Normal → warning; TauBar in AC → ok, plus a warning that the agent is still loaded).
  Not verified, needs the user: (1) the lid-closed mode: `apps/taubar/sudoers/install-sudoers.sh` was only run with `--print` (the rendered rule passes `visudo -c`); after installing, pick the mode and check `pmset -g` shows `SleepDisabled 1`, then quit TauBar and check it is gone; (2) `infra/remote/setup.sh` removing `com.tau.keepawake` once TauBar.app is in `/Applications` (the agent may not run setup.sh); (3) TauBar actually starting at the next login. The quit path of the lid-closed mode is covered by unit tests only.
  Found: on this MacBook the menu bar is full, so macOS placed TauBar's status item off screen (x = -2582 on an 1800 px display), where neither a user nor a test can click it. TauBar therefore opens its window on the first run and whenever TauBar.app is opened again, and the window has a Quit button; the README explains System Settings → Menu Bar. The tray menu itself could not be clicked in tests; its actions call the same `Core` methods the window does.
