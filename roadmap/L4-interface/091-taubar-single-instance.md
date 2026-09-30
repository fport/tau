# 091 · Two TauBar copies can run at once

Status: needs-triage
Type: AFK
Layer: L4 · Interface
Packages: apps/taubar
Blocked by: none

## What to build

On the user's Mac two TauBar processes ran side by side: the copy in `/Applications` and the release build in `apps/taubar/src-tauri/target/release/bundle/macos/` (LaunchServices had registered both, and opening "TauBar" started the build copy). Both held the sleep assertion and showed a menu; the build copy supervised the hub, and "Launch at login" registered the build copy's path. When the build copy quit, it stopped its hub and the `/Applications` copy did not take over, because it had read `run_hub = false` at its own start and never saw the other copy tick the switch: the bot was down until TauBar was restarted.

Make TauBar single-instance (a second launch hands over to the running one, e.g. `tauri-plugin-single-instance`, and shows its window, which also covers 088), and let a running TauBar pick up `settings.json` changes or keep settings in one owner. The docs should tell developers to run the build copy only when the installed one is quit.

## Acceptance criteria

- [ ] Launching TauBar while it runs (Spotlight, Finder, `open -a`, the build copy) leaves one TauBar process and shows its window
- [ ] Two copies never supervise or stop each other's hub
- [ ] "Launch at login" always points at the copy that registered it, and the guide says to install in `/Applications` first

## Blocked by

None - can start immediately.

## Comments

- 2026-09-30: found after the TauBar handover. Fixed by hand: the build copies were unregistered from LaunchServices (`lsregister -u`), the build copy quit and the `/Applications` copy restarted; the login item then pointed at `/Applications/TauBar.app`.
