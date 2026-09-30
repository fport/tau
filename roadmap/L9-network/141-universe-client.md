# 141 · tau-net universe client: join, leave, status and hourly reports

Status: done
Type: AFK
Layer: L9 · Cloud mode and the tau network
Packages: tau-net
Blocked by: none

## What to build

The hub side of `docs/reference/tau-universe.md` §1 and §3:

- Signed `join`, `report` and `leave` requests, sent by a `UniverseClient`.
- The `[component.net] universe*` settings.
- The `counts` document in the network store.
- Reports that list only accepted contacts that are themselves in the universe.
- `tau net universe join|leave|status`.
- The `net` service reporting every `universe_report_minutes` without ever crashing.
- `FakeUniverse` in `tau_net.testing`.

## Acceptance criteria

- [x] Unlisted contacts are never sent (asserted on the request bodies); `--no-links` sends none
- [x] Two taus over `FakeNetwork` + `FakeUniverse` join, talk and report; the snapshot shows one mutual link with the smaller count
- [x] Universe errors show in `/status` and never stop the poll loop
- [x] Workspace tests, ruff and `uv build --package tau-net` pass

## Blocked by

None - can start immediately.

## Comments

- 2026-09-30: opened with ADR 0010.
- 2026-09-30: done.
  - Commits: c40fd61..ac5375d; b1963b1 (the poll starts from `after=0`).
  - Name and membership live in the network store's `profile` document, never in `tau.toml`.
  - Tests: tau-net has 203.
  - Live: `tau net universe join --owner Furkan` listed the owner's tau at https://tau.getporti.com/universe#furkan.tau.getporti.com (1 of 1 tau, online), and `status` agrees with `/api/universe`.
