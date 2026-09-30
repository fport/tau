# 163 · Visitors talk to web sub-taus through the universe

Status: ready-for-agent
Type: AFK
Layer: L9 · Cloud mode and the tau network
Packages: cloud/universe, cloud/shared
Blocked by: 156, 158, 159, 160

## What to build

[ADR 0013](../../docs/adr/0013-hosted-taus-handles-and-public-pages.md) §5. The universe's network identity (`UNIVERSE_IDENTITY` secret; card at `/.well-known/tau.json`; inbox `POST /net/inbox` with the spine's checks), a `Relay` Durable Object for visitor threads (24 h TTL, ≤ 50 messages per thread), `POST /api/chat/<target>` and `GET /api/chat/<target>/<thread>?after=<n>` (long poll ≤ 25 s), the `tau_visitor` cookie, 10 messages/min per IP (rate-limit binding), 2 000 chars. Hosted targets go to `HOST` (`POST /api/visit/...`); hub-run targets get a sealed `visit` envelope and the reply `message` lands in the inbox and the thread.

## Acceptance criteria

- [ ] vitest with a fake `HOST` and a fake hub spine: both paths, caps, TTL, bad targets, a non-web sub-tau refused
- [ ] End to end locally: `sub.html` → universe → kit spine → hub on the fake model → reply on the page

## Blocked by

- [156](156-visit-envelopes-and-web-sub-taus.md), [158](158-shared-net-typescript.md), [159](159-tau-host-core.md), [160](160-universe-handles-and-pages-api.md)

## Comments

- 2026-09-30: filed with ADR 0013.
