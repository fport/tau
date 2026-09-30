# 121 · Guard state on the mesh for owner-arrived routines

Status: needs-triage
Type: AFK
Layer: L10 · Guard
Packages: tau-guard, tau-mesh
Blocked by: 032, 037, 111

## What to build

"Once it sees me, tau starts": the second reading of the owner's wish. In v1 the guard is only a gate ([ADR 0008](../../docs/adr/0008-owner-guard.md), decision 1). This issue lets routines react to the owner arriving and leaving, without an LLM and without the cloud. An example routine: unlock → turn on the desk light and show the morning summary.

- **Publishing.** `GuardService` publishes state changes on Zenoh as `tau/guard/state`, with payload `{state, method, trigger}`: `unlocked` with method `face` or `touch_id`, `locked` with its lock trigger. The payload holds no score, no client id, no enrollment id and no timestamps beyond the event time. It uses `GuardService.subscribe` (111), and the publisher is a small hub-side bridge in tau-guard, loaded only when tau-mesh is installed.
- **Routines.** The reflex engine (037) can match `tau/guard/state` like any event. A routine firing on `unlocked` runs its action as a routine does. Its tier-2 actions follow the routine rules (one approval at registration, none per firing). The guard event itself grants nothing: it cannot unlock, approve or step up.
- **Presence.** 036's `tau/desk/presence` (screen lock and unlock from TauBar) and the guard's own screen-lock reading must agree. The guard keeps reading the screen-lock state itself, because reflex locks cannot depend on the mesh. 036 may reuse the guard's reading instead of a second listener.
- **Mesh scope.** The mesh stays tailnet-only (ADR 0006 §6). Nothing on the mesh can change guard state (no subscriber in tau-guard), which 122's signed attestations would change later, under their own rules.

### To settle in triage

- The exact topic and payload once 032 fixes the event naming.
- Whether a "while you were away" digest (Telegram) belongs here or in 123.
- Whether the routine engine needs a debounce for quick lock/unlock flaps.

## Acceptance criteria

- [ ] An unlock and a lock publish `tau/guard/state` with the documented payload (fake Zenoh session); nothing else about the guard is published
- [ ] A registered routine matching `unlocked` fires without an LLM and without the network (reflex-engine test)
- [ ] No mesh message can change guard state: tau-guard subscribes to no topic (test)
- [ ] The docs list the topic and an example routine

## Blocked by

- [032 · zenohd on the hub, node liveliness and `tau nodes`](../L5-mesh/032-zenoh-router-and-liveliness.md)
- [037 · Reflex engine for user-registered routines](../L5-mesh/037-reflex-routine-engine.md)
- [111 · `tau-guard` service](111-tau-guard-service.md)

## Comments

- 2026-09-30: filed with ADR 0008. needs-triage until the mesh (032) and the reflex engine (037) exist.
