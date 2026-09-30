# Model proxy and budgets

tau's model roles (`brain`, `fast`, `local`) go through a **LiteLLM proxy** by default. LiteLLM is an open-source gateway that speaks the OpenAI API, forwards every call to the real model provider and counts what each **virtual key** spends; a virtual key is a key the proxy issues itself, with its own model list and spend cap. tau gives every role its own key, and the key carries the role's budget from `tau.toml`, so a role can never spend more than you allowed.

The proxy runs in Docker on the hub, next to a small Postgres database that keeps the spend. The decision is [ADR 0009](../adr/0009-anthropic-only-models-behind-the-proxy.md); the operations reference (compose file, image upgrades, logs) is [`infra/litellm/README.md`](https://github.com/fport/tau/blob/main/infra/litellm/README.md). This guide is the user's side: set it up, choose the caps, see the spend, and what happens when a budget runs out.

```text
tau (provider = "proxy")  ──►  127.0.0.1:4000  LiteLLM proxy  ──►  Anthropic API       brain, fast
   one virtual key per role        │  spend per key               └►  Ollama on the Mac  local (→ fast when away)
                                   └► Postgres (compose network only)
```

## Why a proxy

- **A hard cap per role.** `brain` may spend $15 a month, `fast` $1 a day, `local` $0.50 a day (the shipped values). The proxy refuses a key whose budget is spent; nothing is billed past the cap.
- **Spend inside tau.** The model sees its budget in every prompt, `/status` prints it, the hub serves it on `GET /spend`, and `tau proxy spend` lists it.
- **Graceful degradation.** When Anthropic refuses a Sonnet call (overloaded, 5xx), the proxy answers with `fast`. When Ollama on the Mac is asleep or away, `local` answers with `fast`. tau logs every such fallback.
- **Isolation.** The `litellm` Python package is never installed with pip (its PyPI releases were compromised in March 2026); it runs only inside a container pinned by digest. The proxy listens on `127.0.0.1` only, keeps costs but never prompts or replies in its spend log, and its images are multi-arch, so the same setup runs on the Raspberry Pi 5 hub.

## Before you start

- **Docker.** Docker Desktop on macOS (turn on *Start Docker Desktop when you sign in*, so the proxy comes back after a reboot), the `docker.io` package on the Raspberry Pi.
- **`ANTHROPIC_API_KEY`** in `.env`. The proxy reads the same variable as tau (and `ANTHROPIC_WORKSPACE_ID`, if your key needs it).
- **Ollama** for the `local` role, with the model pulled: `ollama pull qwen3.5:9b`. Without it, `local` simply answers through `fast`.

!!! note "Which `.env`?"
    `infra/litellm/proxy.sh` reads the repository's `.env`; tau reads `<TAU_HOME>/.env`. In a checkout that is the same file. If your configuration root is elsewhere (`~/.tau`), point the script at it, so the proxy's secrets and the role keys end up in the file tau reads:

    ```sh
    export TAU_ENV_FILE=~/.tau/.env
    ```

## Set it up

Run these from the repository checkout (inside it, `tau` is `uv run tau`).

**1. Generate the proxy's secrets.**

```sh
infra/litellm/proxy.sh init
```

It adds `LITELLM_MASTER_KEY` (the proxy's admin key), `LITELLM_SALT_KEY` (encrypts what the proxy stores) and `TAU_PROXY_DB_PASSWORD` to `.env`, only the ones that are missing, so running it again is safe. Never change `LITELLM_SALT_KEY` after the first start.

**2. Start the proxy.**

```sh
infra/litellm/proxy.sh up
```

```text
  ✓ proxy listening on http://127.0.0.1:4000
```

It starts the proxy and Postgres in the background and waits until both are healthy. The containers restart on their own whenever Docker runs.

**3. Put the roles on the proxy.** In a checkout there is nothing to do: the repository's `tau.toml` already uses `provider = "proxy"` for every role. A root that `tau init` wrote for the direct provider is rewritten with:

```sh
tau init --provider proxy --force
```

`--force` also rewrites `persona/persona.md` from the template (`user.md` and `.env.example` are kept). If you changed `persona.md`, edit the three role tables in `tau.toml` by hand instead; each looks like this, with the model group as `model_id`:

```toml
[models.roles.brain]
provider = "proxy"
model_id = "brain"
max_tokens = 4096

[models.roles.brain.budget]
usd = 15
period = "1mo"
degrade_to = "fast"
```

The full shipped file is in the [tau.toml reference](../reference/tau-toml.md#the-shipped-file).

**4. Create the role keys.**

```sh
tau proxy keys
```

```text
  brain    created   TAU_PROXY_KEY_BRAIN  $15.00 per 1mo, then fast
  fast     created   TAU_PROXY_KEY_FAST  $1.00 per 1d
  local    created   TAU_PROXY_KEY_LOCAL  $0.50 per 1d
```

One virtual key per role, limited to the role's model group and carrying its budget, written to `<TAU_HOME>/.env`. It needs `LITELLM_MASTER_KEY`.

**5. Check.**

```sh
tau doctor
```

Next to the role lines, `tau doctor` now reports each proxy role's key:

```text
ok   proxy brain: $0.00 of $15.00 per 1mo, within budget
ok   proxy fast: $0.00 of $1.00 per 1d, within budget
ok   proxy local: $0.00 of $0.50 per 1d, within budget
```

A running hub, `tau chat` or `tau tui` read `.env` when they start: restart them to pick up the new keys.

## Budgets

A budget is a table under the role in `tau.toml`:

| Key | Meaning |
|---|---|
| `usd` | Dollars per period, a positive number. |
| `period` | LiteLLM's `budget_duration`: a number plus `s`, `m`, `h`, `d` or `mo`, e.g. `1d`, `7d`, `1mo`. Periods reset in UTC. |
| `degrade_to` | Optional. Another role that answers once this budget is spent, until the reset. Not the role itself, and no loops (`brain` → `fast` → `brain`). Omit it and tau stops and says when the budget resets. |

The shipped values:

| Role | Model | Budget | When it is spent |
|---|---|---|---|
| `brain` | Claude Sonnet 5 | $15 per `1mo` | `fast` answers until the reset |
| `fast` | Claude Haiku 4.5 | $1 per `1d` | tau says when it resets |
| `local` | Ollama `qwen3.5:9b`, falling back to `fast` | $0.50 per `1d` | tau says when it resets |

The `local` budget only bounds what its `fast` fallback may spend; Ollama itself costs nothing.

**Change a cap:** edit the number in `tau.toml`, then apply it:

```sh
tau proxy keys
```

```text
  brain    updated   TAU_PROXY_KEY_BRAIN  max_budget → $20.00 per 1mo, then fast
  fast     unchanged TAU_PROXY_KEY_FAST  $1.00 per 1d
  local    unchanged TAU_PROXY_KEY_LOCAL  $0.50 per 1d
```

The proxy enforces the new cap at once. A changed `degrade_to` applies when tau next starts. Until you run `tau proxy keys`, `tau doctor` warns:

```text
warn proxy brain: the key's cap ($15.00 per 1mo) differs from tau.toml ($20.00 per 1mo); run tau proxy keys
```

A budget only means something on a `proxy` role. On any other provider nothing enforces it, and `tau doctor` says so.

## When a budget is spent

The proxy refuses the role's key, and tau turns that into one sentence in the UI language (Turkish with `[ui] language = "tr"`), never a stack trace. The terminal, the TUI and Telegram show the same text.

With `degrade_to`, the cheaper role answers and the reply ends with a notice:

```text
The brain budget is spent until 01.10.2026 03:00; fast answered instead.
```

Without `degrade_to`, the turn ends:

```text
The brain budget is spent ($15.00 of $15.00) and resets at 01.10.2026 03:00. To raise the cap, change it in tau.toml and run tau proxy keys.
```

When the stand-in is spent too:

```text
The brain budget is spent until 01.10.2026 03:00, and fast, which stands in for it, is spent too until 01.10.2026 03:00.
```

Times in the channels are Europe/Istanbul; a period that resets at 00:00 UTC shows as 03:00.

If the proxy is not running, every proxy role answers with:

```text
The model proxy at http://127.0.0.1:4000 is not answering. Start it with infra/litellm/proxy.sh up.
```

tau never falls back to calling Anthropic directly behind the proxy's back: that would bypass the budgets.

## See the spend

The amounts are what each key spent in its current period; for a daily cap that is today's spend.

**`tau proxy spend`** (`--json` for scripts):

```text
  brain    brain    $0.42 of $15.00 per 1mo, resets 2026-10-01 00:00 UTC
  fast     fast     $0.03 of $1.00 per 1d, resets 2026-10-01 00:00 UTC
  local    local    $0.00 of $0.50 per 1d, resets 2026-10-01 00:00 UTC
```

A spent key is marked `· SPENT` (with `, fast answers instead` when the role degrades), a key whose cap drifted from `tau.toml` `· differs from tau.toml, run tau proxy keys`.

**`/status`** in the terminal, the TUI or Telegram ends with a line read fresh from the proxy:

```text
Budget: brain $0.42 of $15.00 per 1mo (resets 01.10.2026 03:00); fast $0.03 of $1.00 per 1d (resets 01.10.2026 03:00); local $0.00 of $0.50 per 1d (resets 01.10.2026 03:00)
```

**The model** sees the same numbers as `- Budget: …` under `## Now` in its system prompt, so it can tell you how much is left. The line comes from a cache and never delays a reply.

**The hub** serves them on its control API (loopback only), and `GET /status` carries the cached copy under `spend`:

```sh
curl -s 127.0.0.1:7877/spend
```

```json
{
  "proxy": "http://127.0.0.1:4000",
  "roles": {
    "brain": {
      "group": "brain",
      "spend_usd": 0.42,
      "max_budget_usd": 15.0,
      "period": "1mo",
      "reset_at": "2026-10-01T00:00:00+00:00",
      "exhausted": false,
      "configured": {"usd": 15.0, "period": "1mo", "degrade_to": "fast"},
      "error": null
    }
  }
}
```

## The local role and Ollama

- **Model.** `qwen3.5:9b` is the recommended local model: it answers well in Turkish. `think: false` in the proxy's [`config.yaml`](https://github.com/fport/tau/blob/main/infra/litellm/config.yaml) makes it answer in about two seconds instead of reasoning first. Another model is `TAU_LOCAL_MODEL=ollama_chat/<ollama model name>` in `.env`, then `infra/litellm/proxy.sh up`.
- **Hub on the Mac.** Nothing to set: the container reaches Ollama on the Docker host, which is the Mac itself.
- **Hub elsewhere (the Raspberry Pi 5).** Set `TAU_OLLAMA_URL=http://my-mac.tailXXXXXX.ts.net:11434` in the hub's `.env`. On the Mac, let Ollama listen on its tailnet address only (`OLLAMA_HOST=100.x.y.z`), never on every interface: the tailnet is the only network that should reach it ([ADR 0006](../adr/0006-private-first-topology.md)).
- **When the Mac is away.** Asleep or off the network, `local` answers through `fast`: after about 2 seconds when the connection is refused, after about 20 when nothing answers. The hub log shows a warning such as `role local: the proxy fell back from model group local to fast …`.

## Rotate a key

```sh
tau proxy rotate brain
```

```text
  brain    rotated   TAU_PROXY_KEY_BRAIN  $0.42 spent this period kept
```

The new key goes into `.env` and the old one is deleted; the spend of the current period moves over, so a rotation never resets a budget. Restart the hub afterwards (`tau hub stop` and start it again, or untick and tick **Run the hub** in TauBar) so it reads the new key.

If `.env` lost a key while the proxy still holds one under the alias `tau-<role>`, `tau proxy keys` refuses to take it over, because it may belong to another tau home sharing this proxy. If it is yours, `tau proxy keys --replace` creates a new key and carries its spend over. Rotating the master key is in [`infra/litellm/README.md`](https://github.com/fport/tau/blob/main/infra/litellm/README.md#rotate-a-key).

## Without the proxy

The direct providers need no Docker. With only `ANTHROPIC_API_KEY` in `.env`, `tau init` writes them:

```sh
tau init --provider anthropic --force
```

`brain` and `fast` then call Anthropic directly, `local` calls Ollama directly (`provider = "ollama"` at `TAU_OLLAMA_URL`, else `http://127.0.0.1:11434`), and the budget tables are left out. In this mode:

- there are **no budgets**: nothing stops a role from spending;
- there is **no fallback** from `brain` or `local` to `fast`;
- tau shows **no spend**: `/status` has no Budget line and the prompt reads `- Budget: unknown`.

Either way, set a monthly spend limit on your Anthropic workspace in the Console. It is the last line of defence and also covers calls that never pass through tau. [Cloud mode](cloud-mode.md) runs without the proxy too, so it is always in direct mode.

## Troubleshooting

| You see | Do |
|---|---|
| `fail role brain: provider 'proxy' is missing TAU_PROXY_KEY_BRAIN` | `tau proxy keys`, then restart tau. |
| `warn proxy: not answering at http://127.0.0.1:4000` | `infra/litellm/proxy.sh up` (is Docker running?); `proxy.sh status` shows the containers. |
| `fail proxy brain: the proxy does not accept TAU_PROXY_KEY_BRAIN (…)` | The key is not this proxy's (a new database, another machine): `tau proxy keys`. |
| `Error: LITELLM_MASTER_KEY is not set; run infra/litellm/proxy.sh init and start the proxy.` | The master key is in another `.env`; see [Which `.env`?](#before-you-start). |
| `Error: the proxy already has a key named tau-brain that TAU_PROXY_KEY_BRAIN in .env does not match. …` | `tau proxy keys --replace` if the key is yours. |
| `warn role brain: has a budget, but provider 'anthropic' cannot enforce it (only the proxy does; ADR 0009)` | Put the role back on `proxy`, or remove its budget table. |
