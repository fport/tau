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
tau cloud push      # tau.toml, persona.md, net.md; shows the list and asks first
tau cloud status    # spine health and mode, the files it holds, the brain container's health
```

- The file set is exactly `tau.toml`, `persona/persona.md`, `persona/user.md` and `persona/net.md`. Nothing else is read or sent, and `.env` is never uploaded.
- `persona/user.md` holds what tau knows about you, so it has its own question, and the default answer is no. `tau cloud push --include-user` uploads it without the question.
- In a script (no terminal), `tau cloud push --yes` uploads without asking; `persona/user.md` then goes up only with `--include-user` as well.
- The brain reads these files when it starts. After a push, the running brain keeps the old ones until its next start (a redeploy restarts it).
- `tau cloud pull` downloads the same files, for example onto a new machine. It never replaces a local file that differs unless you pass `--force`.

## 4. Talk to it

Write to your bot on Telegram. The container's hub answers, and tier-2 approvals arrive as inline buttons exactly as in local mode. Sessions are stored in D1, so they survive a container restart. `/resume` works as usual.

## What the brain container runs

The image (`cloud/spine/container/Dockerfile`) starts `tau cloud run`, which:

1. checks that `TAU_SPINE_URL` and `TAU_SPINE_TOKEN` are set and that the spine runs in cloud mode (otherwise it exits with one line);
2. pulls the files into `TAU_HOME` and changes two keys of the pulled `tau.toml`: `[sessions] backend = "spine"` and `[component.net] store = "spine"`. Everything else, comments included, stays as you wrote it;
3. answers `GET /health` on port 8080 with `{"ok": true, "version": ..., "hub": <the hub's /status or null>}`, which the spine's `GET /hub/brain` passes on;
4. runs `tau hub run` in the same process, until the container runtime sends SIGTERM, which stops the hub cleanly.

`tau cloud run` refuses a `TAU_HOME` that holds a `tau.toml` it did not write, so it never overwrites your own configuration.

## Try it locally, without a container

`pnpm run dev:cloud` runs the spine in cloud mode with containers off, so you can check the files and the `spine` session backend without Docker or a Cloudflare account:

```sh
(cd cloud/spine && pnpm install && pnpm run configure && pnpm run dev:cloud)
# another terminal; TAU_SPINE_URL=http://127.0.0.1:8787 and TAU_SPINE_TOKEN from cloud/spine/.dev.vars in .env
tau cloud push && tau cloud status      # the brain shows as unavailable: containers are off
# play the container: the spine variables in the environment, an empty TAU_HOME and TAU_DATA_DIR,
# and another hub port in case your own hub runs on 7877
export TAU_SPINE_URL=http://127.0.0.1:8787 TAU_SPINE_TOKEN=<HUB_TOKEN from cloud/spine/.dev.vars>
export TAU_HOME=/tmp/brain/tau TAU_DATA_DIR=/tmp/brain/data TAU_HUB_PORT=7977
TAU_CLOUD_HEALTH_HOST=127.0.0.1 tau cloud run
curl http://127.0.0.1:8080/health       # a third terminal
```

A `tau chat` with the same variables then stores its session in the local spine's D1.

## Going back to local mode

Deploy the local-mode configuration again (`pnpm run configure --force && pnpm run deploy`). The container stops, and your address and contacts stay. The data stored in D1 and KV stays in your account until you delete it (`wrangler d1 execute`, `wrangler kv key delete`, or delete the resources in the dashboard).
