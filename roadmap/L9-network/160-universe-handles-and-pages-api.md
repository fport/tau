# 160 · Universe v3: handles, claims, slugs and the page APIs

Status: ready-for-agent
Type: AFK
Layer: L9 · Cloud mode and the tau network
Packages: cloud/universe
Blocked by: –

## What to build

[ADR 0013](../../docs/adr/0013-hosted-taus-handles-and-public-pages.md) §3 and §6, the universe Worker's server side.

- Addresses: accept `host/@handle` everywhere an address is validated; fetch cards at the longer URL.
- Directory schema v3: `handle` per tau (unique), per sub-tau `web`, `starters`, `first_seen`; a `slugs` table (global, first come, reserved route names, released on leave/expiry). Hosted taus on the universe's own host (`<universe>/@h`) get handle `h` from the address.
- `claim` request (format from 157): `POST /api/claim` with the signed wire body, verified like `join` (3 600 s window) plus the signed-in GitHub account from `HOST` (`GET /api/host/whoami` over the service binding, cookies forwarded); binds, moves (same GitHub id) or refuses (other id). Without a `HOST` binding: `501`.
- APIs: `GET /api/people/<handle>`, `GET /api/subs/<slug>` (and `/api/subs/@<handle>/<name>`), snapshot and `/api/taus/<address>` carry `handle`, `web`, `starters`, `first_seen`.
- Routing: `/@<handle>` → `person.html`, `/<slug>` and `/@<handle>/<name>` → `sub.html`, `/claim` → `claim.html` (the HTML comes from 161; serve it as static assets with the same CSP), all also under `/tr/`. Unknown slug/handle → 404 page. Forward `/app`, `/app/*`, `/auth/*`, `/api/host/*`, `/@<handle>/.well-known/tau.json`, `/@<handle>/net/*` to `HOST` when bound (404 otherwise).
- `docs/reference/tau-universe.md` updated (schema v3, endpoints, routing).

## Acceptance criteria

- [ ] vitest: v2 → v3 migration keeps existing taus; slugs first-come and reserved; claim bind/move/refuse with a fake `HOST`; people/subs APIs; routing and forwarding with a fake `HOST`
- [ ] `pnpm dev` without a host still serves everything else

## Blocked by

None (the `claim` format is fixed in ADR 0013 §6 and 157; build against it).

## Comments

- 2026-09-30: filed with ADR 0013.
