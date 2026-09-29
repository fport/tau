# 071 · Decide `SessionRepository` vs Strands `Storage`/`SnapshotSessionManager` before the D1 backend

Status: needs-triage
Type: AFK
Layer: L3 · Cloud
Packages: tau-core, cloud/tau-cloud
Blocked by: none

## What to build

tau's `SessionStore` extends Strands' `SessionRepository` and is driven by `RepositorySessionManager` (ADR 0003): every message and agent event is written as it happens. Strands also offers a `Storage` abstraction used by `SnapshotSessionManager`, which persists the whole agent state as snapshots instead of per-message writes. Before the D1 backend (018) is built on the repository contract, decide which of the two tau commits to for remote stores: per-message writes over the Worker API (many small requests, exact event log, resumable mid-turn) or snapshots (fewer, larger writes, simpler backend, but the event log for the TUI replay has to be kept separately).

Compare both on: write volume over the relay, resume fidelity after a crash mid-turn, interrupt persistence (068), retention ("keep everything"), the event replay 055/063 depends on, and how much of `FileSessionStore` would change. Record the decision in ADR 0003 (amend) or a new ADR and adjust 018's spec.

## Acceptance criteria

- [ ] A written comparison of the two mechanisms as shipped in the pinned strands-agents version, on the criteria above
- [ ] Decision recorded in an ADR; 018's "What to build" updated to match
- [ ] If the decision changes the store contract, a migration note for existing file sessions is included (nothing is ever deleted)

## Blocked by

None - must be decided before 018 starts.

## Comments

- 2026-09-29: filed as a follow-up of the Strands-correctness pass (064) so 018 does not build on an undecided contract.
