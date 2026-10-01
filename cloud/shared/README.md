# cloud/shared

TypeScript shared by tau's Workers ([ADR 0013](../../docs/adr/0013-hosted-taus-handles-and-public-pages.md) §4 and §8). It is not a published package and has no build step: `package.json` only pins the dependencies and the test tools. A Worker imports the files by relative path, and wrangler's esbuild bundles them into the Worker.

| Path | What it is |
|---|---|
| `turn/` | The turn protocol's TypeScript half ([turn-protocol.md](../../docs/reference/turn-protocol.md), ADR 0015): types, `parseEvent`, `parseBlock`, `readEvents` and `LineSplitter`, checked against `turn/vectors.json`, which tau-core writes |
| `net/` | The tau network protocol's TypeScript half ([tau-network.md](../../docs/reference/tau-network.md), [tau-universe.md](../../docs/reference/tau-universe.md) §1), byte-compatible with tau-net |
| `character.ts` | `character(seed, {size, animated, label, kind})`: the ember sigil of a tau (seed: its address) or a sub-tau (`<address>/<name>`, in its tau's hue): a neon triangle with a flame inside and HUD accents, fewer details at small sizes. `kind` is `"tau"` or `"sub"`, from the seed unless given. Pure and deterministic, no ids, no inline styles; `traits`, `describe`, `kindOf` and `ownerOf` are exported too. The golden and coverage tests are in `cloud/universe/test/character.test.ts`, the gallery is `cloud/universe/scripts/gallery.mjs` |
| `theme.css` | The hard theme's tokens (`--bg`, `--line`, `--text`, `--muted`, `--accent`, the brand colours, `--fire`, …), the @font-face rules of Chakra Petch, IBM Plex Sans and JetBrains Mono (relative `fonts/` next to the file), base styles, chamfered buttons, chips and boxes (`.cut`), HUD rings, triangles, beams and the floor, and the sigils' motion, all stopped under `prefers-reduced-motion`. A Worker's build copies it next to its fonts |
| `fonts.mjs` | `copyFonts(out)`: copies the theme's web fonts and their OFL licences from `cloud/shared/node_modules` (the `@fontsource` packages are dependencies here) into `out`. The builds of cloud/universe and cloud/host call it |

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

1. **Install the dependencies here.** esbuild, Vite and TypeScript resolve `@noble/ciphers` from the importing file, which lives in `cloud/shared/net/`. So `cloud/shared/node_modules` must exist, and the Worker's own `node_modules` does not help. Run `bun install` in `cloud/shared` before building or testing a Worker that imports it, for example from the Worker's `package.json`:

   ```json
   "scripts": { "postinstall": "cd ../shared && bun install --frozen-lockfile" }
   ```

   bun runs a project's own `postinstall` on every `bun install`, also with `--frozen-lockfile` and when nothing changed. In CI, add `cloud/shared/bun.lock` to the key of the bun cache.
2. **TypeScript:** the shared files import each other with `.ts` extensions (so Node can run them for the vectors), so the Worker's `tsconfig.json` needs `"allowImportingTsExtensions": true`, which works together with its `"noEmit": true`.
3. **Types:** the modules are written against `@cloudflare/workers-types`, which every Worker here already uses.

`bun run bundle-check` bundles the tiny Worker in `net/test/bundle/` with `wrangler deploy --dry-run`, which proves that the imports resolve in a real bundle. Nothing is deployed.

## Test vectors

The two halves check each other in both directions:

- **Python → TypeScript**: `net/vectors.json` is written by tau-net itself:

  ```sh
  uv run python packages/tau-net/scripts/make_ts_vectors.py
  ```

  It holds identities, base64url and address verdicts, envelopes built by `build_envelope`, tampered envelopes and universe requests, and in `hosted` the envelopes a hub and the universe write to a hosted tau at `host.example/@bob`, which tau-host's tests deliver (`cloud/host/test/interop.test.ts`). The script pins the ephemeral key and nonce, so the output is deterministic. `net/test/vectors.test.ts` verifies and opens every envelope, and rebuilds each one byte for byte. `packages/tau-net/tests/test_ts_vectors.py` fails when the file is stale.
- **TypeScript → Python**: `net/ts-vectors.json` is written by `bun run vectors` from fresh random keys, with `host/@handle` addresses, `visit` envelopes and `claim` requests. tau-net's test verifies and opens them, and signs and seals the same bytes from the recorded inputs. `net/test/ts-vectors.test.ts` rebuilds the file from its inputs and fails when the TypeScript output has changed. When it does, run `bun run vectors` and commit the file.

Every key in both files is a test-only key.

## Commands

Requirements: bun (and Node 24). `bun run` starts Vitest, Wrangler and the vectors script on Node (`vectors` runs the TypeScript with Node's type stripping).

```sh
bun install              # once, and after a change to package.json
bun run test             # vitest, every test in workerd and in Node
bun run typecheck        # tsc
bun run vectors          # rewrite net/ts-vectors.json
bun run bundle-check     # bundle net/test/bundle/ with wrangler (dry run)
```

CI runs the same commands in `.github/workflows/cloud-shared.yml`.
