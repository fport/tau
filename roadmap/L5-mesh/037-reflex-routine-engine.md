# 037 · Reflex engine for user-registered routines

Status: ready-for-agent
Type: AFK
Layer: L5 · Mesh
Packages: tau-core, tau-mesh
Blocked by: 006, 032

## What to build

The user registers routines: an event pattern → an action with parameters, with optional conditions (time window, cooldown). The reflex engine runs them without an LLM. Registering a routine whose action is tier 2 needs one approval; after that, firings do not ask again. Routines are managed from Telegram and the TUI.

## Acceptance criteria

- [ ] A routine `desk.presence=present → notify "welcome"` fires on the event
- [ ] Registering a tier-2 routine requires exactly one approval; later firings do not
- [ ] Cooldown and time-window conditions work
- [ ] The engine keeps working with no internet (no LLM, no cloud)

## Blocked by

- [006 · Tool permission tiers with approval and a loop guard](../L1-agent/006-tool-permission-tiers.md)
- [032 · zenohd on the hub, node liveliness and `tau nodes`](032-zenoh-router-and-liveliness.md)

## Comments
