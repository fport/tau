# 157 · Handle claims: `tau net universe claim` and the `claim` request

Status: ready-for-agent
Type: AFK
Layer: L9 · Cloud mode and the tau network
Packages: tau-net, cloud/universe
Blocked by: 155

## What to build

[ADR 0013](../../docs/adr/0013-hosted-taus-handles-and-public-pages.md) §6. A new signed universe request kind `claim` (same wire format as `join`, prefix `tau-universe/1\n`, fields `v, kind, universe, address, ts, nonce`, valid 3 600 s instead of 300). `tau net universe claim` builds one and prints `https://<universe>/claim#<b64u(wire JSON)>`. The universe side (`/claim` page, `POST /api/claim`, GitHub session check through `HOST`) is built in 160; this issue owns the CLI, the request format in `docs/reference/tau-universe.md` §1, and tests that pin the wire bytes the Worker verifies.

## Acceptance criteria

- [ ] `tau net universe claim` prints the link; `tau net universe status` shows the handle once the universe reports it
- [ ] Reference updated; a test vector for a `claim` request in the reference

## Blocked by

- [155 · Handle-based addresses](155-handle-addresses.md)

## Comments

- 2026-09-30: filed with ADR 0013.
