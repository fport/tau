# 108 · Move sessions and network state between local and cloud mode

Status: needs-triage
Type: AFK
Layer: L9 · Cloud mode and the tau network
Packages: tau-cloud, tau-net
Blocked by: 094

## What to build

Switching modes keeps the address and the identity, but not the data:

- **Local → cloud:** local sessions (the file store) and the network state (`TAU_DATA_DIR/net/`) do not follow the hub into cloud mode.
- **Cloud → local:** a local-mode spine answers `404 cloud_mode_off` for the store routes, so the sessions, contacts and log kept in D1 are out of reach.

Add `tau cloud export` and `tau cloud import`:

- They copy sessions (every message and event, nothing rewritten, ADR 0003) and the `net.*` documents between the file store and the spine store.
- They are idempotent.
- Export must run while the spine is still in cloud mode.
- Import refuses to overwrite a session that already exists on the target.

## Acceptance criteria

- [ ] Local → cloud: after `tau cloud import`, the cloud tau lists the same sessions and contacts; resuming a moved session keeps its history
- [ ] Cloud → local: `tau cloud export` into an empty data dir reproduces the sessions and contacts; `tau doctor` and `/sessions` agree
- [ ] Running either twice changes nothing; nothing is ever deleted on either side

## Blocked by

- [094 · tau-cloud](094-tau-cloud.md)

## Comments

- 2026-09-30: filed while closing 094: the cloud-mode guide's "Going back to local mode" had no way to take the data along.
