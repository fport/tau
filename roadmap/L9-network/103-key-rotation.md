# 103 · Card key rotation and contact re-keying

Status: needs-triage
Type: AFK
Layer: L9 · Cloud mode and the tau network
Packages: tau-net, cloud/spine
Blocked by: 093

## What to build

v1 pins a contact's keys when the contact is accepted, and drops envelopes that do not verify ("key changed"). A tau that loses its identity, or rotates it, is therefore cut off until each contact removes it and adds it again.

Design a rotation envelope:

- The old key signs the new keys, so contacts can follow a rotation without the owner's intervention.
- A lost key still needs a fresh contact request.

## Acceptance criteria

- [ ] `tau net rotate` publishes new keys and notifies accepted contacts with an envelope signed by the old key
- [ ] Contacts accept the rotation automatically only when the old-key signature verifies; anything else stays a "key changed" refusal

## Blocked by

- [093 · tau-net](093-tau-net.md)

## Comments

- 2026-09-30: filed with ADR 0007.
