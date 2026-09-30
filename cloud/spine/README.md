# tau spine

The spine is a Cloudflare Worker that every tau on the tau network runs in its owner's own Cloudflare account. Its hostname is the tau's **address**. It:

- serves the tau's public **card** at `/.well-known/tau.json` (name, signing key, box key);
- takes signed, sealed **envelopes** from other taus at `/net/inbox`, checks them (size, shape, recipient, clock, the sender's card and signature, replays, rate limit) and keeps them in a **mailbox** until the hub picks them up;
- gives the owner's hub a bearer-token API (`/hub/*`) to publish the card, long-poll the mailbox and acknowledge envelopes;
- in **cloud mode** only, also stores the hub's state, config files and sessions (D1, KV) and runs the hub itself as a Cloudflare Container (the **brain**).

Local mode needs no D1 database: KV, one SQLite-backed Durable Object and a cron are all it uses, and all of them are on the Workers Free plan (see [Storage](#storage)).

The contract, with every status code, JSON shape and limit, is [the tau network reference](../../docs/reference/tau-network.md). The decision behind it is [ADR 0007](../../docs/adr/0007-cloud-mode-and-tau-network.md).

The spine never decrypts anything and holds no contacts: it cannot tell a friend from a stranger, and it answers both the same way. Only the hub opens boxes.

## Layout

```text
src/index.ts      fetch router and the cron entry (exports only handlers and classes)
src/net.ts        the card and POST /net/inbox (the §4 checks, in order)
src/hub.ts        /hub/*: auth, health, card, updates (long poll), ack
src/mailbox.ts    Mailbox, the Durable Object that stores envelopes and wakes a waiting long poll
src/store.ts      cloud mode: state, files, sessions, brain
src/brain.ts      TauBrain, the container class (cloud mode)
src/cron.ts       pruning and keep-awake
src/crypto.ts     base64url, Ed25519 verification (WebCrypto), constant-time token check
migrations/       D1 schema of the cloud store (cloud mode only)
container/        the brain image (python:3.12-slim + tau-core, tau-net, tau-cloud)
scripts/          configure.mjs, send-dev-envelope.mjs
```

## Local development

Requirements: Node 24 and pnpm 10. No Cloudflare account and no Docker are needed.

```sh
cd cloud/spine
pnpm install
pnpm run configure    # writes wrangler.jsonc (local mode) and .dev.vars with a random HUB_TOKEN
pnpm dev              # http://127.0.0.1:8787
```

`pnpm run configure` never prints the token. It is in `cloud/spine/.dev.vars`; the hub needs the same value:

```sh
# the hub's .env (repository root)
TAU_SPINE_URL=http://127.0.0.1:8787
TAU_SPINE_TOKEN=<HUB_TOKEN from cloud/spine/.dev.vars>
TAU_NET_ALLOW_INSECURE=1
```

`wrangler dev` keeps KV and the Mailbox's SQLite storage (and in cloud mode D1) on disk under `.wrangler/state`. A quick check:

```sh
curl http://127.0.0.1:8787/                                   # tau spine 127.0.0.1:8787
curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8787/hub/health
curl -H "Authorization: Bearer $TOKEN" "http://127.0.0.1:8787/hub/updates?timeout=5"
```

Other commands:

| Command | What it does |
|---|---|
| `pnpm test` | the Vitest suite in the Workers runtime; a `local` and a `cloud` project |
| `pnpm typecheck` | `tsc --noEmit` |
| `pnpm run types` | regenerates `worker-configuration.d.ts` (the `Env` type) from `wrangler.cloud.example.jsonc`. It is tracked, since it is small and lets CI type-check without a config; `wrangler dev` in local mode reports it as "out of date", which is expected |
| `pnpm run dev:cloud` | the spine in cloud mode from `wrangler.cloud.example.jsonc`, whatever mode your `wrangler.jsonc` is in: applies the D1 migrations locally, then runs with containers off. The store routes answer, `/hub/brain` is 503, no Docker needed. For testing the `spine` session backend of `tau-cloud` |
| `curl http://127.0.0.1:8787/cdn-cgi/local/scheduled` | runs the cron once (`wrangler dev` does not run crons by itself) |

With the cloud configuration in `wrangler.jsonc`, plain `pnpm dev` also builds and runs the brain container, which needs Docker. `pnpm dev` applies no D1 migrations, so run `pnpm exec wrangler d1 migrations apply DB --local` once first.

### Two taus on one machine

Two spines can talk to each other locally. Each needs its own port, persistence directory and address; `.dev.vars` sets `ALLOW_INSECURE_PEERS=1`, so they fetch each other's cards over `http://127.0.0.1`. `--persist-to` gives each spine its own KV and Mailbox storage; there is no database to migrate.

```sh
# Spine A: 127.0.0.1:8787 (the dev address in wrangler.jsonc; its address is the request host)
pnpm dev

# Spine B: 127.0.0.1:8788, own state, explicit address (a second terminal)
pnpm exec wrangler dev --port 8788 --inspector-port 9230 \
  --persist-to .wrangler/state-b --var ADDRESS:127.0.0.1:8788
```

Publish a card on each (`PUT /hub/card`; a hub does this on start), then send an envelope from A to B. `scripts/send-dev-envelope.mjs` plays A's hub: it signs with A's key, seals the box to B's `box_key` (so a real hub can open it) and posts to B's inbox:

```sh
node scripts/send-dev-envelope.mjs --from 127.0.0.1:8787 --to 127.0.0.1:8788 --text "hello"
node scripts/send-dev-envelope.mjs --from 127.0.0.1:8787 --to 127.0.0.1:8788 --kind contact_request --name "Tau A"
curl -H "Authorization: Bearer $TOKEN" "http://127.0.0.1:8788/hub/updates?timeout=20"
```

Without `--identity` (an `identity.json` of `tau net init`) or `TAU_NET_IDENTITY`, the script signs with the public test-vector keys of the reference, so spine A's card must carry that `sign_key` (`A6EHv_POEL4dcN0Y50vAmWfk1jCbpQ1fHdyGZBJVMbg`). `--print` prints the envelope instead of posting it.

## Deploy: local mode

Local mode is the default (ADR 0006 unchanged): the hub runs at home, and the spine only stores and forwards sealed envelopes. It fits the Workers Free plan and uses no D1 database, so it deploys even on an account whose D1 databases are all taken by other projects.

```sh
cd cloud/spine
pnpm run configure             # if you have not yet
npx wrangler login
pnpm run deploy                # wrangler deploy; there is no database to migrate
npx wrangler secret put HUB_TOKEN
```

- The first deploy provisions the KV namespace and writes its id into your `wrangler.jsonc` (gitignored; keep it). The Mailbox Durable Object needs no provisioning: its class is created by the `v1` migration in the config, and it creates its tables on first use.
- Use a long random `HUB_TOKEN` (for example `openssl rand -base64 32 | tr '+/' '-_' | tr -d '='`); do not reuse the development one.
- The address is `tau-spine.<your-subdomain>.workers.dev`. The hub's `.env` gets `TAU_SPINE_URL=https://tau-spine.<your-subdomain>.workers.dev` and `TAU_SPINE_TOKEN=<the secret>`.

**Custom domain (optional).** In your own `wrangler.jsonc`, with a zone on your account:

```jsonc
"routes": [{ "pattern": "tau.example.com", "custom_domain": true }],
"vars": { "ADDRESS": "tau.example.com", ... }
```

Then `pnpm run deploy` again. The address becomes `tau.example.com`; contacts know your tau by its address, so pick it before you add any.

## Deploy: cloud mode

Cloud mode runs the hub itself in your Cloudflare account: no machine at home. Life data (sessions, state, `tau.toml`, persona files) then lives in your account's D1 and KV. Requirements: the Workers Paid plan (Containers), Docker running (the image is built on deploy), and R2 enabled on the account once (dashboard > R2; the `MEDIA` bucket is reserved for later).

```sh
cd cloud/spine
pnpm run configure --cloud     # --force replaces a local-mode wrangler.jsonc and keeps its ids
```

Cloud mode adds a D1 database (`DB`, the cloud store for state and sessions), which counts against your account's D1 databases. The mailbox stays in the Mailbox Durable Object, so switching keeps the mail in transit.

Set `vars.SPINE_URL` in `wrangler.jsonc` to your deployed URL (`https://tau-spine.<your-subdomain>.workers.dev`, or your custom domain); the brain reaches its store through it. Then:

```sh
npx wrangler login
pnpm run deploy:cloud          # checks the config, builds the image, deploys, migrates D1
npx wrangler secret put HUB_TOKEN
# model credentials: ANTHROPIC_API_KEY (and ANTHROPIC_WORKSPACE_ID), or AWS_REGION with
#   AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY or AWS_BEARER_TOKEN_BEDROCK
npx wrangler secret put ANTHROPIC_API_KEY
npx wrangler secret put TELEGRAM_BOT_TOKEN
npx wrangler secret put TELEGRAM_ALLOWED_CHAT_IDS
npx wrangler secret put TAU_NET_IDENTITY   # the identity as base64url JSON (tau net init)
npx wrangler secret put TAU_LANG           # optional: tr
```

The container gets `TAU_SPINE_URL`, `TAU_SPINE_TOKEN` and each of these secrets that is set as environment variables. Secrets reach a running container only when it starts again; after changing one, redeploy or wait for the next start.

Then, from the hub machine (with `TAU_SPINE_URL` and `TAU_SPINE_TOKEN` in its `.env`), copy config and persona into the spine:

```sh
uv run tau cloud push           # tau.toml, persona/persona.md, persona/net.md; asks first
uv run tau cloud push --include-user   # persona/user.md too (it then lives in your account)
uv run tau cloud status         # the spine, the files it holds, the brain
```

The brain reads the files when it starts, so a push applies from its next start. The image runs `tau cloud run`: it pulls the files into `/tau`, sets `[sessions] backend = "spine"` and `[component.net] store = "spine"` in the pulled `tau.toml`, answers `GET /health` on port 8080 and runs `tau hub run` until SIGTERM. `GET /hub/brain` (with the token) answers that health JSON, `{"ok": true, "version", "hub": <the hub's /status or null>}`. With `KEEP_AWAKE=1` (the default in the cloud config) the cron pings the brain every minute so the Telegram poller inside it never sleeps.

To build and try the image by hand (from the repository root):

```sh
docker build -f cloud/spine/container/Dockerfile -t tau-brain .
docker run --rm tau-brain tau cloud --help
```

**Back to local mode.** `pnpm run configure --force` writes the local config again (the KV id and your address are kept; the local config has no D1 binding). The deployed Worker still has the `TauBrain` Durable Object class, which a deploy cannot drop silently, so extend `migrations` in your `wrangler.jsonc` before `pnpm run deploy`:

```jsonc
"migrations": [
  { "tag": "v1", "new_sqlite_classes": ["Mailbox"] },
  { "tag": "v2", "new_sqlite_classes": ["TauBrain"] },
  { "tag": "v3", "deleted_classes": ["TauBrain"] }
]
```

That deletes the brain's own Durable Object storage, not the Mailbox, your D1 database or your KV data. Life data stays in D1 and KV until you remove it; a local-mode spine never serves it (those routes answer `404 cloud_mode_off`) and no longer binds the D1 database at all.

## Storage

| What | Where | Mode |
|---|---|---|
| The card, cached peer cards (`peer:<address>`, one hour) | KV `TAU` | both |
| The mailbox, the replay guard (`seen`) and the per-sender arrival counts of the rate limit | the `Mailbox` Durable Object (one instance, `hub`), in its own SQLite storage | both |
| `tau.toml` and the persona files | KV `TAU` (`file:<name>`) | cloud |
| State and sessions (the cloud store) | D1 `DB`, schema in `migrations/` | cloud |
| Media (reserved) | R2 `MEDIA` | cloud |

The Mailbox creates its tables on first use and records a schema version in its `meta` table. It judges duplicates, the rate limit and the mailbox cap, stores the envelope and wakes a waiting long poll in one step, so a poll can never miss mail that arrived just before it started to wait. The Worker parses the envelope, fetches the sender's card and checks the signature before it calls the Mailbox. The minute cron calls the Mailbox's `prune`, which deletes mailbox rows older than 7 days and `seen` rows older than 1 day.

Local mode binds no D1 database. A Workers Free account allows 10 D1 databases, and other projects often use them all; a Durable Object class does not count against that limit.

## Costs

- **Local mode** fits the Workers Free plan. A hub long-polling with the 25-second timeout makes about 3 500 Worker requests a day, plus 1 440 cron runs, each of which calls the Mailbox once (about 5 000 of the 100 000 Durable Object requests a day). The `Mailbox` object is active while a poll waits, about 10 800 of the 13 000 GB-s of Durable Object duration the Free plan allows per day. Its SQLite storage stays far below the Free plan's limits (5 GB stored, 5 million rows read and 100 000 rows written a day): an envelope costs fewer than ten written rows from arrival to acknowledgement. KV use stays far below its free limits, and there is no D1 use at all.
- **Cloud mode** needs Workers Paid ($5 per month). The brain is a `basic` container (1/4 vCPU, 1 GiB memory, 4 GB disk). Kept awake all month, it is billed for about 720 GiB-hours of memory, of which 25 are included: roughly $6 per month, plus a little for disk and for the CPU it actually uses. With `KEEP_AWAKE=0` it sleeps 15 minutes after the last request and costs almost nothing, but then Telegram messages wait until something wakes it.

Check [Workers pricing](https://developers.cloudflare.com/workers/platform/pricing/) and [Containers pricing](https://developers.cloudflare.com/containers/pricing/) for current numbers.

## Privacy

- **Local mode**: the spine holds only what is in transit, in the Mailbox Durable Object. Envelopes are sealed end to end to your hub's box key; the spine keeps them until the hub acknowledges them (at most 7 days) and remembers envelope ids for a day to stop replays. It sees who wrote to you and when, never what. Your life data stays on the hub.
- **Cloud mode**: your life data lives in your own Cloudflare account (D1, KV), under Cloudflare's at-rest encryption, not your own key. Nothing moves there until you deploy the cloud configuration and run `tau cloud push`.
- Nothing in this directory carries personal data: the example configs have no resource ids and no hostnames. Your ids and addresses go only into the gitignored `wrangler.jsonc`, and secrets only into `.dev.vars` (local) and `wrangler secret` (deployed).
