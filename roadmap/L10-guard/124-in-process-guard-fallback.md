# 124 · In-process guard fallback when no hub runs (worker subprocess, same state machine)

Status: ready-for-agent
Type: AFK
Layer: L10 · Guard
Packages: tau-core, tau-guard
Blocked by: 112, 113

## What to build

In v1, a guarded channel without a running hub stays locked, with a notice on how to start one ([ADR 0008](../../docs/adr/0008-owner-guard.md), decision 2). This issue adds an opt-in fallback: `tau tui` or `tau chat` run the guard themselves when no hub answers. The fallback must be exactly as strict as the hub: the same state machine, reflex loop, worker subprocess, cooldown and audit. It never opens a second, looser path.

### Shape

- **Opt-in.** `[component.guard] fallback = "locked" | "local"`, default `locked`. Like every weakening-sensitive knob, `local` takes effect only after a verification, and the doctor shows it.
- **`LocalGuard`** lives in tau-guard. It imports only tau-guard's pure state machine, the presence sources and the worker runner, never cv2 or pyobjc, so a channel process still never loads a camera library. Camera, model and Keychain work runs in the same `python -m tau_guard.worker` subprocess as in the hub, with stderr going to `TAU_DATA_DIR/guard/worker.log` and never to the TUI's terminal.
- **Discovery.** A `tau.guard` entry-point group returns a factory for `LocalGuard`, with exact selection rules:
  - The provider is pinned to the `tau-guard` distribution by default (`[component.guard] provider`).
  - With zero providers the fallback is `locked`.
  - With more than one provider, or one from another distribution, `resolve_guard` returns `LockedGuard` and the doctor reports an error.
  - The registry's in-process `register_*` override never applies to this group.
  - No test fixture distribution ships a `tau.guard` entry point; tests monkeypatch the registry's entry-point listing.

  The group needs an amendment to ADR 0008 and a row in ADR 0005's group table.
- **The source is chosen once per process.** At channel start, `resolve_guard` picks hub or local.
  - Every transition between the two (the hub comes up, the hub goes away) forces `locked` and needs a fresh verification. The channel header shows the source.
  - A 403, an `off` answer or a bad proof from a hub never switches to local; it stays locked, as in 110.
  - While a hub lock is held (`HubLock.probe`), the fallback is never used.
- **Reflexes in-process.** `LocalGuard` runs the same 2-second reflex loop in a daemon thread, with the same inline checks at admit: max age, sleep drift, idle, screen lock, recheck and the heartbeat. A local unlock is never persisted and never handed to a hub.
- **Camera permission.**
  - In `tau chat` and a terminal `tau tui`, the responsible process is the terminal app. The first local attempt may show its camera prompt, and the guide says so.
  - tau Desktop has no camera entitlement (116). There the fallback answers `camera_denied`, with the hint to start the hub, unless a later issue gives tau Desktop the entitlement.
- **Enrollment and forget** keep their LocalAuthentication rules. `forget` in the fallback removes the same files and key.

## Acceptance criteria

- [ ] With `fallback = "local"` and no hub, `tau tui` and `tau chat` unlock through `LocalGuard` (fake worker, fake presence), and neither `cv2` nor `objc` is in the channel process's `sys.modules`
- [ ] `LocalGuard` passes the same state-machine and reflex test suite as `GuardService` (shared parametrized tests)
- [ ] A hub appearing or disappearing mid-session forces `locked`; a hub answering 403, `off` or without a proof never switches the channel to local
- [ ] With zero `tau.guard` providers the fallback is `locked`; with two, or one from another distribution, `resolve_guard` returns `LockedGuard` and the doctor reports it (monkeypatched entry points; no fixture distribution)
- [ ] Worker stderr never reaches the TUI's terminal (snapshot test with a fake worker writing to stderr)
- [ ] ADR 0008 is amended for the `tau.guard` group and the fallback, and ADR 0005's group table lists the group
- [ ] (user) With TauBar's hub switched off and `fallback = "local"`, the owner unlocks `tau chat` in Terminal once; the result goes under Comments

## Blocked by

- [112 · Face verification](112-face-verification.md)
- [113 · Guarded channels](113-guarded-channels.md)

## Comments

- 2026-09-30: filed with ADR 0008.
