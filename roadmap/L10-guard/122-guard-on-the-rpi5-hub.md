# 122 · Guard on the RPi5 hub: the Mac as a camera node sending signed attestations

Status: needs-hardware
Type: needs-hardware
Layer: L10 · Guard
Packages: tau-guard, tau-mesh
Blocked by: 048

## What to build

When the hub moves to the RPi5 (048), the guard's state machine, reflex locks, cooldown, audit and routes move with it, but the owner still sits at the Mac. The Mac becomes a camera node. It runs the same worker (camera, YuNet + SFace, head-turn challenge, template and Keychain key all stay on the Mac) and sends the hub a **signed attestation** of each result. The rule comes from [ADR 0008](../../docs/adr/0008-owner-guard.md) (decision 21): no route or mesh message ever carries a bare verdict.

- **Pairing.** The Mac node gets an Ed25519 key when it is paired with the hub. The hub pins the public key. A key change is refused, never followed silently.
- **The hub starts every check.**
  1. The hub creates an attempt with a random nonce and a short expiry (for example 30 s) and asks the node to look.
  2. The node answers `{attempt, nonce, kind, ok, reason, method, liveness, issued_at}`, signed with its key, over the authenticated tailnet mesh.
  3. The hub accepts the answer only for its own open attempt, with its nonce, before the expiry and with a valid signature. It rejects anything else as `error` and records it in the audit.
- **Presence.** Presence signals (HID idle, screen lock) come from the Mac node the same way: signed, tied to the hub's poll, and treated as unknown when they are missing or late. That caps the unlock at `idle_lock_minutes`, as for an unknown screen state.
- **Local reflexes on the Pi.** Max age, sleep drift (for the Pi itself), cooldown and the admission heartbeat still run on the hub with no LLM, no cloud and no dependency on a node for locking. A node that goes away means locked, never unlocked.
- **Key storage on Linux.** The Pi holds no template, so it needs no Secret Service. If a Linux hub ever enrolls locally (a USB camera on the Pi), the key goes into `systemd-creds` or a 0400 file outside `TAU_DATA_DIR`. The docs then say plainly that without a TPM this protects copies and backups, not root on the box.
- **Platform.** v1 is macOS-only (decision 22). This issue lifts that only for the attestation path.

## Acceptance criteria

- [ ] The hub accepts an attestation only for its own open attempt, with the right nonce, before the expiry and signed by the pinned node key; a replayed, late, unsigned or wrongly signed attestation is rejected and audited (tests with a fake mesh)
- [ ] A lost node, or late or missing presence signals, lock the guard or cap the unlock, never extend it
- [ ] No route and no mesh topic accepts an unsigned verdict (test enumerating routes and subscriptions)
- [ ] The template, the key and every frame stay on the Mac node; nothing biometric reaches the Pi (test over the Pi's data dir)
- [ ] (user) On the RPi5 hub with the Mac as the camera node, the owner unlocks `tau tui` and passes a tier-2 step-up

## Blocked by

- [048 · Move the hub to the RPi5 with self-replication](../backlog/048-rpi5-hub-migration.md)

## Comments

- 2026-09-30: filed with ADR 0008.
