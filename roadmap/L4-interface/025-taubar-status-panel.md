# 025 · TauBar status panel: hub, nodes, spend, approvals

Status: ready-for-agent
Type: AFK
Layer: L4 · Interface
Packages: apps/taubar
Blocked by: 009, 011, 024

## What to build

The TauBar popover shows hub connection, live nodes, today's spend against budget per role, and pending approvals that can be approved or rejected right there — all through the hub's local control API.

## Acceptance criteria

- [ ] Hub up/down is reflected within 5 seconds
- [ ] Spend numbers match the proxy
- [ ] Pending tier-2 approvals can be resolved from TauBar
- [ ] Degrades gracefully when the hub is offline

## Blocked by

- [009 · `tau hub` daemon with launchd service and self-heal](../L1-agent/009-hub-daemon.md)
- [011 · Hard budgets per role with graceful degradation](../L2-models/011-hard-budgets.md)
- [024 · TauBar v0: tray app with sleep modes](024-taubar-sleep-modes.md)

## Comments
