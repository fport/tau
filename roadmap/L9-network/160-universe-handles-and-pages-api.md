# 160 · Universe v3: handles, claims, slugs and the page APIs

Status: done
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

- [x] vitest: v2 → v3 migration keeps existing taus; slugs first-come and reserved; claim bind/move/refuse with a fake `HOST`; people/subs APIs; routing and forwarding with a fake `HOST`
- [x] `pnpm dev` without a host still serves everything else

## Blocked by

None (the `claim` format is fixed in ADR 0013 §6 and 157; build against it).

## Comments

- 2026-09-30: filed with ADR 0013.
- 2026-09-30: done.
  - Addresses: `host[:port]/@handle` everywhere (`src/address.ts`); a card of `<universe>/@h` comes through `HOST` (a Worker cannot fetch its own host), and without `HOST` such a tau cannot join.
  - Schema v3, migrated in place (v1 and v2 databases keep every tau): `taus.handle` (unique) with `taus.github_id` (never shown), each stored sub-tau's `web`, `starters` and `first_seen`, and `slugs(name, address, claimed_at)`. The upgrade hands out slugs in `joined_at` order. Reserved sub-tau names (`net app api auth claim hub`) are dropped from reports.
  - Slugs: first report that lists a free, unreserved name; kept while the tau is listed (even when it stops listing that sub-tau), released on leave and expiry. The reserved list is `RESERVED_NAMES` in `src/routes.ts`; a test checks it covers every top-level entry of `public/`.
  - `POST /api/claim`: `501 claims_unavailable` without `HOST`, `403 bad_origin` unless `Origin` is the universe's own origin (the claim page), then the join checks with a 3 600 s window and the usual "newer than the last accepted `ts`" (the contract of cloud/shared and tau-net; nonce 16–64 base64url), then `GET /api/host/whoami` through `HOST` with the request's `Cookie` (`401 not_signed_in`, `502 host_unavailable`), then joined, rate limit and the handle rules (`409 handle_taken`, `409 handle_mismatch`). Answer: `{ok, handle, url, moved_from}`. Hosted taus at `<universe>/@h` get `h` on join/report and take it from any claimed tau.
  - APIs: `GET /api/people/<handle>`, `/api/subs/<slug>`, `/api/subs/@<handle>/<name>` (CORS, `max-age=30`); the snapshot and `/api/taus` carry `handle` and per sub-tau `web`, `starters`, `first_seen`, `slug`. Shapes in the reference §2.
  - Routing: `/@<handle>` → `person`, `/<slug>` and `/@<handle>/<name>` → `sub`, `/claim` → `claim` templates (and `/tr/`), after a directory lookup; `/@Alice` → 301; bare `/person`, `/sub` are 404. Forwarding to `HOST`: `/app`, `/app/*`, `/auth/*`, `/api/host/*`, `/@<h>/.well-known/tau.json`, `/@<h>/net/*`, unchanged both ways. `pnpm run configure --host-service NAME` (and `--no-host-service`).
  - Checked with `wrangler dev` without a host (pages, API, 404s, `claims_unavailable`), with `dev-taus.mjs` (slugs in the snapshot, `/coach` served from a temporary template through the real asset routing), and `wrangler deploy --dry-run` with the `HOST` binding.
  - Open: the universe's `build.mjs` writes its bundle and fonts to `public/app/`, which shadows tau-host's `/app/*` for those files; the site's assets should move to a path of their own (161). A claim link goes stale when the hub reports after the link was made (the `ts` rule); the claim page should say to run the command again.
