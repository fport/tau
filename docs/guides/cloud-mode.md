# Run tau in Cloudflare (cloud mode)

By default tau runs on your own machine and keeps your life data there (local mode, [ADR 0006](../adr/0006-private-first-topology.md)). **Cloud mode** runs the same tau without a machine at home. The hub runs as a container in your own Cloudflare account, next to your spine Worker, and you talk to it through Telegram. The decision is [ADR 0007](../adr/0007-cloud-mode-and-tau-network.md).

!!! warning "What you trade"
    In cloud mode your sessions, persona (including `persona/user.md`) and settings live in **your** Cloudflare account: D1 and KV, under Cloudflare's own at-rest encryption, not a key only you hold. Anyone who gets into that account, or a leaked `HUB_TOKEN`, can read them. Local mode keeps all of this on your machine. Pick cloud mode only when you accept that.

## What runs where

| Piece | Where |
|---|---|
| The spine Worker (`tau-spine`) | Cloudflare Workers: your address, card and mailbox, the store API, a cron |
| The brain (`tau hub run`, the same Python code) | a Cloudflare Container managed by the spine, started with `tau cloud run` |
| Sessions, small state (contacts, cursors) | D1, through the spine (`[sessions] backend = "spine"`) |
| `tau.toml`, `persona/*.md` | KV, uploaded with `tau cloud push` |
| Credentials (model keys, Telegram token, network identity) | Worker secrets, handed to the container as environment variables |

## Before you start

- A Cloudflare account on **Workers Paid** (about $5/month), because Containers need it. The container itself is billed for the time it runs; the spine's cron keeps it awake so the Telegram poller can run.
- **Docker** running on the machine you deploy from, because Wrangler builds the image locally.
- Node.js 20+ and pnpm, and a clone of this repo.
- A working local setup first (`tau init`, `tau doctor`), because cloud mode uploads your `tau.toml` and persona.

## 1. Configure and deploy the spine in cloud mode

```sh
cd cloud/spine
pnpm install
pnpm run configure --cloud --force    # wrangler.jsonc from wrangler.cloud.example.jsonc
pnpm exec wrangler login
```

Open `cloud/spine/wrangler.jsonc` and set `SPINE_URL` to the URL your spine will have: the `workers.dev` URL, or your custom domain if you add a route. The container uses it to reach the spine. Then deploy:

```sh
pnpm run deploy:cloud
```

## 2. Set the secrets

Every value below goes in with `wrangler secret put <NAME>`, which prompts for it. Never pass a secret as a command argument.

| Secret | Value |
|---|---|
| `HUB_TOKEN` | a long random value; your local `tau cloud` commands use it as `TAU_SPINE_TOKEN` |
| `ANTHROPIC_API_KEY` (and `ANTHROPIC_WORKSPACE_ID` if needed), or `AWS_REGION` + `AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY` / `AWS_BEARER_TOKEN_BEDROCK` | the model credentials your `tau.toml` roles need |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_CHAT_IDS` | as in the [Telegram guide](telegram.md) |
| `TAU_NET_IDENTITY` | your network identity, if the cloud tau should join the tau network: base64url of the JSON in `TAU_DATA_DIR/net/identity.json` ([Join the tau network](tau-network.md)) |

## 3. Upload your configuration and persona

On the machine that has your `tau.toml` and `persona/`, put `TAU_SPINE_URL` (the spine URL) and `TAU_SPINE_TOKEN` (the `HUB_TOKEN`) in `.env`, then:

```sh
tau cloud push      # tau.toml, persona.md, net.md; asks before uploading user.md
tau cloud status    # spine health and the brain container's health
```

`tau cloud pull` downloads the same files, for example onto a new machine. `.env` is never uploaded.

## 4. Talk to it

Write to your bot on Telegram. The container's hub answers, and tier-2 approvals arrive as inline buttons exactly as in local mode. Sessions are stored in D1, so they survive a container restart. `/resume` works as usual.

## Going back to local mode

Deploy the local-mode configuration again (`pnpm run configure --force && pnpm run deploy`). The container stops, and your address and contacts stay. The data stored in D1 and KV stays in your account until you delete it (`wrangler d1 execute`, `wrangler kv key delete`, or delete the resources in the dashboard).
