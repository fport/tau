# 089 · A nicer TauBar menu and settings window

Status: needs-triage
Type: AFK
Layer: L4 · Interface
Packages: apps/taubar
Blocked by: none

## What to build

TauBar v0 works (024, 084), but the user finds the menu plain: status lines, switches and sleep modes are one long native list. Design a tidier menu and settings window with the brand palette and the tau mark from `docs/brand/`: a clear hub status (state, uptime, Telegram poller) at the top, grouped switches, and the sleep modes as one choice. Keep the native menu where macOS expects it and keep every action reachable without the window.

## Acceptance criteria

- [ ] A design the user approves before it is built (a quick prototype or mockup is fine)
- [ ] Menu and window follow the brand palette and stay readable in light and dark mode
- [ ] Nothing that works in v0 is lost (switches, sleep modes, logs, quit)

## Blocked by

None - can start immediately.

## Comments

- 2026-09-30: the user, on first sight of the TauBar menu: "it could have a nicer UI".
