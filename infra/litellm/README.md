# infra/litellm

The LiteLLM proxy that serves tau's model roles, with a hard budget on every role ([ADR 0009](../../docs/adr/0009-anthropic-only-models-behind-the-proxy.md), roadmap 010–012).

```
tau (provider = "proxy")  ──►  127.0.0.1:4000  LiteLLM proxy  ──►  Anthropic API   (brain, fast)
   one virtual key per role        │  spend per key               └►  Ollama on the Mac (local → fast)
                                   └► Postgres (compose network only)
```

- **Model groups are tau's roles.** In `config.yaml`, `brain` is Claude Sonnet 5, `fast` is Claude Haiku 4.5, and `local` is Ollama. `tau.toml` points each role at its group with `provider = "proxy"` and `model_id = "<group>"`.
- **Fallbacks.** `brain` falls back to `fast` when Anthropic refuses Sonnet. `local` falls back to `fast` when Ollama is unreachable. Both show up in the hub log as `the proxy fell back from model group …`.
- **Budgets live in `tau.toml`** (`[models.roles.<role>.budget]`). `tau proxy keys` writes them to the roles' virtual keys, and the proxy refuses a key whose budget is spent. tau then answers with the role's `degrade_to` or tells you when the budget resets.
- **Isolated and pinned.** `litellm` is never installed with pip: the PyPI releases 1.82.7 and 1.82.8 were compromised in March 2026. The proxy runs only here, from an image pinned by tag and digest, next to a pinned Postgres. Both images are multi-arch (amd64, arm64), so the same files run on the RPi5 hub.
- **Private.** The proxy publishes only `127.0.0.1:${TAU_PROXY_PORT:-4000}`, and the database publishes no port at all. The spend log keeps costs, never prompts or replies. The proxy uses the cost map bundled with the image; it never fetches one at start.

## Requirements

- Docker: Docker Desktop on macOS, the `docker.io` package on the RPi5.
- `ANTHROPIC_API_KEY` in the repo's `.env`. The proxy reads the same variables as tau.
- For `local`: Ollama with the model pulled. On the Mac: `ollama pull qwen3.5:9b`.

## Start

```sh
infra/litellm/proxy.sh init     # generates LITELLM_MASTER_KEY, LITELLM_SALT_KEY, TAU_PROXY_DB_PASSWORD into .env
infra/litellm/proxy.sh up       # starts the proxy and Postgres in the background, waits until healthy
uv run tau proxy keys           # one virtual key per proxy role, with its budget, written to .env
uv run tau doctor               # "proxy brain: $0.00 of $15.00 per 1mo, within budget" …
```

`proxy.sh init` only adds names that are missing, so running it again is safe. **Never change `LITELLM_SALT_KEY`** after the first start: it encrypts what the proxy stores.

The containers use `restart: unless-stopped`: they come back after a reboot as soon as Docker runs. On the Mac, turn on "Start Docker Desktop when you sign in".

`tau.toml` must use the proxy for the roles you want budgeted; the repo's `tau.toml` already does. A home created by `tau init` without a proxy key uses direct providers. `tau init --provider proxy --force` rewrites it for the proxy.

## Stop, restart, inspect

```sh
infra/litellm/proxy.sh status   # containers, health, the model groups the proxy serves
infra/litellm/proxy.sh logs     # follow the proxy log (fallbacks, refused budgets)
infra/litellm/proxy.sh restart  # after editing config.yaml (it is mounted, so edits need a restart)
infra/litellm/proxy.sh down     # stop; the volume tau-litellm-db keeps every key and spend record
```

While the proxy is down, every proxy role answers with "The model proxy at http://127.0.0.1:4000 is not answering. Start it with infra/litellm/proxy.sh up." tau never falls back to calling Anthropic directly, because that would bypass the budgets.

## Budgets and spend

```toml
[models.roles.brain.budget]               # in tau.toml
usd = 15                                  # dollars per period
period = "1mo"                            # 1d, 7d, 1mo, … (resets in UTC)
degrade_to = "fast"                       # once spent, fast answers until the reset; omit to stop
```

- **Change a cap:** edit `tau.toml`, then run `uv run tau proxy keys`. It is safe to repeat, and it prints `updated`, `unchanged` or `created` per role. `tau doctor` warns when a key's cap differs from `tau.toml`.
- **See the spend:** `uv run tau proxy spend` (or `--json`), `/status` in a channel, and `GET http://127.0.0.1:7877/spend` on the hub. The amounts are what each key spent in its current period.
- **Test a cap:** give a throwaway role a tiny budget (`usd = 0.000001`, `period = "1d"`). Its second call is refused.

## Rotate a key

```sh
uv run tau proxy rotate brain   # new key in .env; the period's spend moves over, so the budget does not reset
uv run tau hub stop             # then start the hub again (TauBar: "Run the hub") so it reads the new key
```

`rotate` does four things in order:

1. Renames the old key's alias.
2. Creates the new key with the old key's spend.
3. Writes the new key to `.env`.
4. Deletes the old key.

If creating the new key fails, the old key gets its alias back. LiteLLM's own `/key/regenerate` is an enterprise feature, so it is not used.

If `.env` lost a key while the proxy still holds one under the alias `tau-<role>`, `tau proxy keys` refuses to take it over. The key may belong to another tau home that shares this proxy. Run `uv run tau proxy keys --replace` if it is yours; its spend carries over.

To rotate the master key, set a new `LITELLM_MASTER_KEY` in `.env` and run `proxy.sh up`. The virtual keys stay valid.

## The local role and Ollama

- **Model.** `TAU_LOCAL_MODEL` (default `ollama_chat/qwen3.5:9b`) chooses the model. `qwen3.5:9b` answers well in Turkish. `think: false` in `config.yaml` makes it answer in about 2 s instead of reasoning first.
- **Hub on the Mac.** With `TAU_OLLAMA_URL` unset, the container reaches Ollama on the Docker host, which is the Mac itself.
- **Hub elsewhere (the RPi5).** Set `TAU_OLLAMA_URL=http://my-mac.tailXXXXXX.ts.net:11434` in the hub's `.env`, and on the Mac let Ollama listen on its tailnet address only (`OLLAMA_HOST=100.x.y.z`), never on every interface.
- **When the Mac is away.** Asleep or off the network, `local` answers through `fast`:
  - after about 2 s when the connection is refused;
  - after about 20 s when the Mac does not answer at all.

  After repeated failures the proxy skips Ollama for 30 s (`cooldown_time`).

## Upgrading the image

1. Pick a release on [github.com/BerriAI/litellm/releases](https://github.com/BerriAI/litellm/releases), not a `-rc` or `-dev` one.
2. Read its digest without pulling it:

   ```sh
   tok=$(curl -s "https://ghcr.io/token?scope=repository:berriai/litellm:pull" | python3 -c 'import json,sys;print(json.load(sys.stdin)["token"])')
   curl -sI -H "Authorization: Bearer $tok" -H 'Accept: application/vnd.oci.image.index.v1+json' \
     https://ghcr.io/v2/berriai/litellm/manifests/v1.103.1 | grep -i docker-content-digest
   ```

3. Change the tag and the digest in `docker-compose.yml` together, then `proxy.sh up`.
4. Run `uv run tau proxy spend` and `uv run tau doctor` to check that keys and spend survived. Prices come from the new image's cost map; compare `/model/info` for the roles' models if a budget suddenly behaves differently.

## Files

| File | What |
|---|---|
| `docker-compose.yml` | the proxy and Postgres, pinned by digest, loopback port only |
| `config.yaml` | model groups (the roles), fallbacks, no prompt logging |
| `proxy.sh` | `init`, `up`, `restart`, `down`, `status`, `logs` with the repo's `.env` |
