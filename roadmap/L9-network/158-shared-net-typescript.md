# 158 · The protocol's TypeScript half in `cloud/shared/net`

Status: done
Type: AFK
Layer: L9 · Cloud mode and the tau network
Packages: cloud/shared
Blocked by: –

## What to build

[ADR 0013](../../docs/adr/0013-hosted-taus-handles-and-public-pages.md) §4. Plain TypeScript modules under `cloud/shared/net/`, imported by relative path from Workers (no package, no build of its own): b64u, address parsing (both forms of §3), card shape, envelope build/sign/verify (Ed25519, WebCrypto), seal/open (X25519 via WebCrypto or `@noble/curves`, HKDF-SHA256, ChaCha20-Poly1305 via `@noble/ciphers`), the universe request signer (`tau-universe/1\n`). Byte-compatible with tau-net: a script under `packages/tau-net/scripts/` (or a test helper) writes `cloud/shared/net/vectors.json` from tau-net itself, and vitest in `cloud/shared` checks sign, verify, seal and open against it, both directions.

## Acceptance criteria

- [x] `cloud/shared/net/*.ts` with no Node-only APIs (runs in workerd); dependencies only `@noble/ciphers` (and `@noble/curves` if needed), pinned
- [x] vectors generated from tau-net; vitest (workers pool or node) passes both directions; a Python test fails if the vectors go stale
- [x] A short `cloud/shared/README.md`: what lives here and how the Workers import it

## Blocked by

None.

## Comments

- 2026-09-30: filed with ADR 0013.
- 2026-09-30: done.
  - Modules in `cloud/shared/net/`: `b64u`, `address` (both forms, the scheme rule, `cardUrl`/`inboxUrl`, `parseAddress`/`parseTarget`, reserved sub names), `card` (`makeCard`, `parseCard`, `fetchCard` with the §4 limits), `identity` (`Identity`, compatible with `identity.json` and `TAU_NET_IDENTITY`; seeds in private fields), `seal`, `envelope` (kinds `contact_request`, `contact_accept`, `message`, `visit`), `universe` (`join`, `report` with the ADR 0013 `web`/`starters` sub fields, `leave`, `claim`; `claimLink`), `errors` and the `index.ts` barrel. They use Web APIs only.
  - Crypto: Ed25519, X25519 and HKDF-SHA256 all run on WebCrypto in both workerd and Node (seeds imported through their PKCS#8 header, public keys from a JWK export), so `@noble/curves` is not needed. The only dependency is `@noble/ciphers` 2.4.0, pinned exactly, for ChaCha20-Poly1305.
  - Consumers: run `pnpm install` in `cloud/shared` (esbuild, Vite and tsc resolve `@noble/ciphers` from the importing file, so the Worker's own `node_modules` does not help; a `postinstall` of `pnpm --dir ../shared install --frozen-lockfile` does it), and set `allowImportingTsExtensions` in the Worker's tsconfig. A Worker outside `cloud/shared` was bundled with `wrangler deploy --dry-run` and type-checked this way. `pnpm run bundle-check` keeps an in-tree check.
  - Vectors: `packages/tau-net/scripts/make_ts_vectors.py` writes `net/vectors.json` from tau-net itself, with `build_envelope` under pinned randomness. `visit` and `claim` are built from tau-net's primitives until tau-net knows them (156, 157), and only plain addresses are used (155). vitest verifies and opens every envelope, refuses the tampered ones, and rebuilds every envelope and universe request byte for byte. `pnpm run vectors` writes `net/ts-vectors.json` from fresh TypeScript keys (with `host/@handle` addresses, `visit` and `claim`). `packages/tau-net/tests/test_ts_vectors.py` checks that `vectors.json` is fresh, and that tau-net verifies and opens the TypeScript vectors and signs and seals the same bytes. Its full parsers run as soon as tau-net knows the kind and the address form.
  - The tests run every file in both workerd and Node (442 tests). CI runs them in `.github/workflows/cloud-shared.yml` (typecheck, vitest, bundle check).
  - For 159/160/162/163: the claim `nonce` is 16–64 base64url characters (the id pattern); 157 should use the same rule. `visit` text is capped at 8 000 characters like `message`, and the page's 2 000-character limit belongs to the universe API. The claim window is `abs(now - ts) <= 3600` (`isFresh`).
