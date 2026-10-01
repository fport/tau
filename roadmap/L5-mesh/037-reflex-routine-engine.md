# 037 · Reflex engine for user-registered routines

Status: ready-for-agent
Type: AFK
Layer: L5 · Mesh
Packages: tau-core, tau-mesh
Blocked by: 006, 032, 181

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
- [181 · Routines on a clock](181-routines-on-a-clock.md)

## Comments
- 2026-10-01: [ADR 0015](../../docs/adr/0015-web-app-agentic-chat.md) §4 splits the engine. Clock triggers, registration with one approval, the exemption and the `tau-routines` package are 181. This issue adds event triggers from the mesh (Zenoh patterns, cooldown, time window) to that engine.
