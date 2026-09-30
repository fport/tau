# 158 · The protocol's TypeScript half in `cloud/shared/net`

Status: ready-for-agent
Type: AFK
Layer: L9 · Cloud mode and the tau network
Packages: cloud/shared
Blocked by: –

## What to build

[ADR 0013](../../docs/adr/0013-hosted-taus-handles-and-public-pages.md) §4. Plain TypeScript modules under `cloud/shared/net/`, imported by relative path from Workers (no package, no build of its own): b64u, address parsing (both forms of §3), card shape, envelope build/sign/verify (Ed25519, WebCrypto), seal/open (X25519 via WebCrypto or `@noble/curves`, HKDF-SHA256, ChaCha20-Poly1305 via `@noble/ciphers`), the universe request signer (`tau-universe/1\n`). Byte-compatible with tau-net: a script under `packages/tau-net/scripts/` (or a test helper) writes `cloud/shared/net/vectors.json` from tau-net itself, and vitest in `cloud/shared` checks sign, verify, seal and open against it, both directions.

## Acceptance criteria

- [ ] `cloud/shared/net/*.ts` with no Node-only APIs (runs in workerd); dependencies only `@noble/ciphers` (and `@noble/curves` if needed), pinned
- [ ] vectors generated from tau-net; vitest (workers pool or node) passes both directions; a Python test fails if the vectors go stale
- [ ] A short `cloud/shared/README.md`: what lives here and how the Workers import it

## Blocked by

None.

## Comments

- 2026-09-30: filed with ADR 0013.
