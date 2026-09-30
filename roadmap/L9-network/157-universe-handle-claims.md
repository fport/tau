# 157 · Handle claims: `tau net universe claim` and the `claim` request

Status: done
Type: AFK
Layer: L9 · Cloud mode and the tau network
Packages: tau-net, cloud/universe
Blocked by: 155

## What to build

[ADR 0013](../../docs/adr/0013-hosted-taus-handles-and-public-pages.md) §6. A new signed universe request kind `claim` (same wire format as `join`, prefix `tau-universe/1\n`, fields `v, kind, universe, address, ts, nonce`, valid 3 600 s instead of 300). `tau net universe claim` builds one and prints `https://<universe>/claim#<b64u(wire JSON)>`. The universe side (`/claim` page, `POST /api/claim`, GitHub session check through `HOST`) is built in 160; this issue owns the CLI, the request format in `docs/reference/tau-universe.md` §1, and tests that pin the wire bytes the Worker verifies.

## Acceptance criteria

- [x] `tau net universe claim` prints the link; `tau net universe status` shows the handle once the universe reports it
- [x] Reference updated; a test vector for a `claim` request in the reference

## Blocked by

- [155 · Handle-based addresses](155-handle-addresses.md)

## Comments

- 2026-09-30: filed with ADR 0013.
- 2026-09-30: done. As built:
  - Payload (compact JSON, this order): `{"v":1,"kind":"claim","universe":<host>,"address":<address>,"ts":<int>,"nonce":<b64u>}`; `nonce` matches `^[A-Za-z0-9_-]{16,64}$` (the client sends 18 random bytes, 24 characters). Signed like every universe request (Ed25519 over `b"tau-universe/1\n" + payload`), wire body `{"payload": b64u, "sig": b64u}`.
  - Link: `https://<universe>/claim#<b64u(compact wire JSON)>` (`tau_net.universe.claim_link`, `UniverseClient.claim_link`). The client takes `ts` from its monotonic clock; a universe checks `abs(now - ts) ≤ 3600` and the per-address `ts` order (so a report sent after the link was made spoils it; a new `claim` fixes that).
  - `tau net universe claim` publishes the card when needed, prints the link and a "do not share it" note, sends nothing, and says so when the tau is not joined. `universe status` shows `handle: @<handle>  https://<universe>/@<handle>` when `GET /api/taus/<address>` carries a valid `handle`, else a hint to claim one.
  - Test vector in `docs/reference/tau-universe.md` §1, pinned by `packages/tau-net/tests/test_claim.py`; `cloud/shared/net` vectors pass too.
