# 036 · Desk presence: screen unlock → `tau/desk/presence`

Status: ready-for-agent
Type: AFK
Layer: L5 · Mesh
Packages: apps/taubar, tau-mesh
Blocked by: 024, 032

## What to build

TauBar listens to macOS screen lock/unlock notifications and publishes `tau/desk/presence` (present / away) through the Mac node, debounced.

## Acceptance criteria

- [ ] Unlocking the Mac publishes `present` within 1 second; locking publishes `away`
- [ ] Debounce prevents flapping
- [ ] The event is visible in the TUI event pane

## Blocked by

- [024 · TauBar v0: tray app with sleep modes](../L4-interface/024-taubar-sleep-modes.md)
- [032 · zenohd on the hub, node liveliness and `tau nodes`](032-zenoh-router-and-liveliness.md)

## Comments
