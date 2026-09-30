# cloud/shared

TypeScript shared by tau's Workers ([ADR 0013](../../docs/adr/0013-hosted-taus-handles-and-public-pages.md) §4 and §8). It is not a published package and has no build step: `package.json` only pins the dependencies and the test tools. A Worker imports the files by relative path, and wrangler's esbuild bundles them into the Worker.

| Path | What it is |
|---|---|
| `net/` | The tau network protocol's TypeScript half ([tau-network.md](../../docs/reference/tau-network.md), [tau-universe.md](../../docs/reference/tau-universe.md) §1), byte-compatible with tau-net |

## `net/`: the protocol

Web APIs only (WebCrypto, `TextEncoder`, `atob`/`btoa`, `fetch`), so the modules run in workerd, in browsers and in Node. Ed25519, X25519 and HKDF-SHA256 use WebCrypto. ChaCha20-Poly1305 comes from [`@noble/ciphers`](https://github.com/paulmillr/noble-ciphers), pinned to an exact version, because WebCrypto has no ChaCha20. It is the only dependency.

| Module | Contents |
|---|---|
| `b64u.ts` | base64url (`b64uEncode`, `b64uDecode`, `b64uKey`), UTF-8 and compact JSON that matches tau-net byte for byte |
| `address.ts` | both address forms, `host[:port]` and `host[:port]/@handle` (`isAddress`, `addressParts`), the scheme rule (`baseUrl`), `cardUrl`, `inboxUrl`, and person-typed addresses and sub-tau targets (`parseAddress`, `parseTarget`) |
| `card.ts` | the card: `makeCard`, `parseCard`, and `fetchCard` with the limits of §4 |
| `identity.ts` | `Identity`: `generate`, `fromJson` and `fromEnvValue` (tau-net's `identity.json` and `TAU_NET_IDENTITY`), `signKey`, `boxKey` and `sign`; the seeds stay in private fields |
| `seal.ts` | the box: `seal`, `openBox`, `aadFor` |
| `envelope.ts` | `buildEnvelope`, `openVerified`, `openEnvelope`, `parsePayload`, `parseContent` and `peekSender`; the kinds `contact_request`, `contact_accept`, `message` and `visit` |
| `universe.ts` | signed universe requests: `makeRequestPayload`, `signRequest`, `parseRequest` and `verifyRequest` for `join`, `report`, `leave` and `claim`, plus `claimLink` |
| `errors.ts` | `EnvelopeError` and its subclasses, each with a fixed English `reason` |
| `index.ts` | all of the above |

Failures throw typed errors (`MalformedEnvelope`, `BadSignature`, `BoxError`, `EnvelopeTooLarge`, `MalformedRequest`, `IdentityError`, `AddressError`). The predicates return booleans, and parsers of untrusted text return `null`.

## Using it from a Worker

```ts
import { buildEnvelope, Identity, openEnvelope } from "../../shared/net/index.ts";
```

1. **Install the dependencies here.** esbuild, Vite and TypeScript resolve `@noble/ciphers` from the importing file, which lives in `cloud/shared/net/`. So `cloud/shared/node_modules` must exist, and the Worker's own `node_modules` does not help. Run `pnpm install` in `cloud/shared` before building or testing a Worker that imports it, for example from the Worker's `package.json`:

   ```json
   "scripts": { "postinstall": "pnpm --dir ../shared install --frozen-lockfile" }
   ```

   In CI, add `cloud/shared/pnpm-lock.yaml` to the cache dependency paths.
2. **TypeScript:** the shared files import each other with `.ts` extensions (so Node can run them for the vectors), so the Worker's `tsconfig.json` needs `"allowImportingTsExtensions": true`, which works together with its `"noEmit": true`.
3. **Types:** the modules are written against `@cloudflare/workers-types`, which every Worker here already uses.

`pnpm run bundle-check` bundles the tiny Worker in `net/test/bundle/` with `wrangler deploy --dry-run`, which proves that the imports resolve in a real bundle. Nothing is deployed.

## Test vectors

The two halves check each other in both directions:

- **Python → TypeScript**: `net/vectors.json` is written by tau-net itself:

  ```sh
  uv run python packages/tau-net/scripts/make_ts_vectors.py
  ```

  It holds identities, base64url and address verdicts, envelopes built by `build_envelope`, tampered envelopes and universe requests. The script pins the ephemeral key and nonce, so the output is deterministic. `net/test/vectors.test.ts` verifies and opens every envelope, and rebuilds each one byte for byte. `packages/tau-net/tests/test_ts_vectors.py` fails when the file is stale.
- **TypeScript → Python**: `net/ts-vectors.json` is written by `pnpm run vectors` from fresh random keys, with `host/@handle` addresses, `visit` envelopes and `claim` requests. tau-net's test verifies and opens them, and signs and seals the same bytes from the recorded inputs. `net/test/ts-vectors.test.ts` rebuilds the file from its inputs and fails when the TypeScript output has changed. When it does, run `pnpm run vectors` and commit the file.

Every key in both files is a test-only key.

## Commands

```sh
pnpm install          # once, and after a change to package.json
pnpm test             # vitest, every test in workerd and in Node
pnpm run typecheck    # tsc
pnpm run vectors      # rewrite net/ts-vectors.json
pnpm run bundle-check # bundle net/test/bundle/ with wrangler (dry run)
```

CI runs the same commands in `.github/workflows/cloud-shared.yml`.
