# 125 · Lock the Mac session on a non-matching face (optional strong mode)

Status: needs-triage
Type: AFK
Layer: L10 · Guard
Packages: tau-guard
Blocked by: 112

## What to build

The guard protects tau's own surfaces. The Mac's screen lock is the real boundary for the account ([ADR 0008](../../docs/adr/0008-owner-guard.md), threat model). When the owner walks away without locking the screen, the person who sits down can still open Terminal, Finder or any other app. This optional strong mode closes that gap: when the guard sees a stranger, it locks the whole macOS session, not just tau.

- **Setting.** `[component.guard] lock_mac_on_reject = false` by default. It is a strengthening knob, so it takes effect at once; turning it off again needs a verification, like any weakening.
- **Trigger.** A verification, recheck or step-up that ends with `no_match` or `multiple_faces` after at least one quality frame, or any cooldown start. `no_face`, `too_dark`, `timeout` and `cancelled` never trigger it, so a dark room or a covered camera does not lock the owner's Mac.
- **Action.** The hub locks the macOS session immediately. The hub's own guard locks too, with a new lock trigger `mac_locked`, added to tau-core's `LOCK_TRIGGERS` with its messages. An audit event records it, and the owner gets a notice once 123 lands.
- **No LLM, no cloud, no mesh.** It runs in the reflex path, in the hub. The worker's verdict is enough; nothing waits for a model.
- **Rate limit.** At most one Mac lock per 2 minutes, so a flapping detector cannot make the Mac unusable.

### To settle in triage

**Which mechanism locks the session.** macOS has no documented public API for it. The candidates:
- `SACLockScreenImmediate()` from the private `login.framework` (what the menu's "Lock Screen" uses; it may break with an OS update);
- `pmset displaysleepnow` (locks only when "require password immediately" is set);
- a System Events keystroke (needs the Accessibility permission for the hub's responsible process).

The owner decides whether a private framework call is acceptable. The choice then needs a spike on this Mac, with its result under Comments, before the issue becomes `ready-for-agent`.

## Acceptance criteria

- [ ] With `lock_mac_on_reject = true`, a `no_match` or `multiple_faces` verdict after a quality frame, or a cooldown start, calls the session-lock action once (fake action); `no_face`, `too_dark`, `timeout` and `cancelled` never call it
- [ ] The action is rate-limited to once per 2 minutes and recorded in the audit
- [ ] Turning the setting off needs a verification; turning it on does not
- [ ] The chosen mechanism is documented with its caveats in the guard guide
- [ ] (user) Live: with the setting on, a second person in front of the camera triggers a Mac lock; the owner's own face in bad light does not

## Blocked by

- [112 · Face verification](112-face-verification.md)

## Comments

- 2026-09-30: filed with ADR 0008. needs-triage: the session-lock mechanism (private `login.framework` call or a public workaround) needs the owner's decision and a spike.
