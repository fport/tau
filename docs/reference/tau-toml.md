# tau.toml

`tau.toml` is tau's static configuration, read once at start-up by `tau_core.config.Config`. It lives in the configuration root (`TAU_HOME`); `tau init` writes it from a shipped template that equals the repository's own file. This page lists every table and key with its type and default.

Rules that apply everywhere:

- Top-level tables tau reads: `models`, `agent`, `sessions`, `hub`, `ui`, `components`, `component`. Any other top-level table is logged once and ignored, never an error (a typo such as `[model]` shows up in `tau doctor` as a warning).
- Inside a role table and inside `[components]`, an unknown key **is** an error, so a misspelled switch cannot silently leave a tool on.
- Provider and backend names are validated at load time by name only; nothing is imported until a role is used.
- Secrets never go here. Credentials come from the environment or `.env`.

## `[models.roles.<role>]`

One table per role. The shipped file defines `brain`, `fast` and `local`; any name is allowed, and `tau chat --role` or `/model` can pick it.

| Key | Type | Default | Meaning |
|---|---|---|---|
| `provider` | string | required | `proxy` (the LiteLLM proxy, the shipped default), `anthropic`, `bedrock`, `ollama`, `fake`, or the name of a `tau.providers` component. |
| `model_id` | string | required | Data, never code. For `proxy` it is the proxy's model group (`brain`, `fast`, `local`), which `infra/litellm/config.yaml` maps to a real model; for `ollama` the Ollama model name (`qwen3.5:9b`); otherwise the provider's model id. Bedrock ids use the Converse form with the `global.` prefix. |
| `region` | string | none | Bedrock region. When set, `AWS_REGION` is no longer required for this role. |
| `max_tokens` | integer ≥ 1 | provider default (4096 for `anthropic`, `proxy` and `ollama`) | Output token limit per call. |
| `params` | table | `{}` | Passed to the provider's model as extra parameters, except the tau-specific keys below. |
| `fallback` | table | none | A second role table with the same keys (no nested fallback, no `budget`). Used only when the primary provider's credentials are missing. The shipped file defines none: on a `proxy` role it would call its provider directly, without the budget, whenever the role's key is missing. |
| `cache` | table | none | Prompt-cache settings, see below. |
| `budget` | table | none | The role's hard spend cap, see below. Only the `proxy` provider enforces it. |

`params` keys tau reads itself (not forwarded):

| Key | Providers | Meaning |
|---|---|---|
| `api_key_env` | anthropic, proxy | The variable that holds the key, instead of `ANTHROPIC_API_KEY` (anthropic) or `TAU_PROXY_KEY_<GROUP>` (proxy). |
| `base_url` | anthropic, proxy, ollama | anthropic: an alternative API base URL. proxy: the proxy's URL, else `TAU_PROXY_URL`, else `http://127.0.0.1:4000`. ollama: the Ollama server, else `TAU_OLLAMA_URL`, else `http://127.0.0.1:11434`. For proxy and ollama give it without `/v1`; tau appends it. |
| `workspace_id` | anthropic | The workspace id sent as `anthropic-workspace-id`; `ANTHROPIC_WORKSPACE_ID` in the environment does the same. |

For `proxy`, the key variable is `TAU_PROXY_KEY_` plus the model group upper-cased with every character that is not a letter or digit turned into `_`: group `brain` → `TAU_PROXY_KEY_BRAIN`. `tau proxy keys` writes these. `ollama` needs no credentials and has no budget or fallback of its own; those need the proxy.

### `[models.roles.<role>.budget]`

The hard spend cap of a `proxy` role. The proxy enforces it on the role's virtual key; [`tau proxy keys`](cli.md#tau-proxy-keys) writes `usd` and `period` to the key, so a change takes effect when you run it. A table or an inline table (`budget = { usd = 1, period = "1d" }`) both work.

| Key | Type | Default | Meaning |
|---|---|---|---|
| `usd` | number > 0 | required | Dollars per period. |
| `period` | string | required | LiteLLM's `budget_duration`: a number followed by `s`, `m`, `h`, `d` or `mo`, e.g. `"1d"`, `"7d"`, `"1mo"`. Periods reset in UTC. |
| `degrade_to` | string | none | Another role defined in this file that answers once this budget is spent, until the reset. It must not be the role itself, and following `degrade_to` from role to role must not loop. Omit it to stop the turn and tell the user when the budget resets. |

```toml
[models.roles.brain.budget]
usd = 15
period = "1mo"
degrade_to = "fast"
```

- `budget` is not allowed inside a `fallback` table; set it on the role.
- On any provider other than `proxy` nothing enforces it; `tau doctor` warns (`role brain: has a budget, but provider 'anthropic' cannot enforce it (only the proxy does; ADR 0009)`).
- A `proxy` role without a budget works, but its key has no cap; `tau doctor` warns about that too.
- When the budget is spent, the channel shows `The brain budget is spent until 01.10.2026 03:00; fast answered instead.` (with `degrade_to`) or `The brain budget is spent ($15.00 of $15.00) and resets at 01.10.2026 03:00. To raise the cap, change it in tau.toml and run tau proxy keys.` (without), in the UI language. See [Model proxy and budgets](../guides/model-proxy.md).

### `[models.roles.<role>.cache]`

Maps to Strands' `CacheConfig`. Anthropic and Bedrock honour it; `proxy`, `ollama` and `fake` ignore it (prompt caching does not pass through the proxy yet).

| Key | Type | Default | Meaning |
|---|---|---|---|
| `strategy` | `"auto"` \| `"anthropic"` | `"auto"` | How cache points are placed. |
| `ttl` | string | provider default | Cache TTL, e.g. `"5m"`, `"1h"`. |
| `system_prompt_ttl` | bool or string | unset | Cache the system prompt (`true`) or with its own TTL. |
| `tools_ttl` | bool or string | unset | The same for the tool definitions. |

```toml
[models.roles.brain]
provider = "anthropic"
model_id = "claude-sonnet-5"
max_tokens = 4096
cache = { strategy = "auto", ttl = "1h" }
```

## `[agent]`

| Key | Type | Default | Meaning |
|---|---|---|---|
| `max_turns` | integer ≥ 1 | `12` | Model calls per user turn (the loop guard, Strands `Limits(turns=…)`). At the limit the last call's tools still run; tau stops with a notice. |
| `context` | `"sliding"` \| `"summarize"` | `"sliding"` | What the model sees of a long session. `sliding` sends the last `window_size` messages; `summarize` keeps the last `window_size` verbatim plus a summary of the rest. The store keeps everything either way. A session remembers the mode it was recorded with. |
| `window_size` | integer ≥ 1 | `60` | Messages kept (`sliding`) or never summarized (`summarize`). |
| `max_total_tokens` | integer ≥ 1 | unset | Optional per-turn token budget (`Limits(total_tokens=…)`). |

The SDK's `context_manager = "auto"` / `"agentic"` presets are rejected with a `ConfigError`: they register untiered SDK tools that the tier gate would refuse.

## `[sessions]`

| Key | Type | Default | Meaning |
|---|---|---|---|
| `backend` | string | `"memory"` in code; the shipped file sets `"file"` | `memory` (in-process, for tests), `file` (`TAU_DATA_DIR/sessions/`), or the name of a `tau.sessions` component. |

## `[hub]`

| Key | Type | Default | Meaning |
|---|---|---|---|
| `control_port` | integer 1–65535 | `7877` | Port of the loopback control API. `TAU_HUB_PORT` overrides it. |
| `heartbeat_seconds` | integer ≥ 1 | `5` | How often the running hub refreshes `hub/state.json`. |

## `[ui]`

| Key | Type | Default | Meaning |
|---|---|---|---|
| `language` | `"en"` \| `"tr"` | `"en"` | The chrome language of the terminal and the TUI. `TAU_LANG` overrides it; `tau --lang` overrides both; `/lang` switches it for one run. |

## `[components]`

Switches for discovered components. Unknown keys in any of these tables are an error.

| Key | Type | Default | Meaning |
|---|---|---|---|
| `context` | list of strings | `[]` | Enabled `tau.context` sources by name. Empty means every discovered one. |
| `tools.disabled` | list of strings | `[]` | Tools to switch off, by tool name or `dist:<distribution>` for every tool of a distribution. It can only remove tools. |
| `hub.services` | list of strings | `[]` | Enabled `tau.hub_services` by name. Empty means every discovered one. |

```toml
[components]
context = []

[components.tools]
disabled = ["demo_physical_action", "dist:tau-example-tool"]

[components.hub]
services = []
```

A name that no installed component provides is a `tau doctor` warning. `build_agent(tools=[...])` with an explicit list bypasses `tools.disabled`.

## `[component.<name>]`

Free tables for a component's own settings, returned as a fresh dict by `Config.component("<name>")`. tau does not validate their contents.

```toml
[component.telegram]
poll_timeout_seconds = 50    # Telegram long-poll timeout (default 50)
backoff_max_seconds = 60     # cap of the backoff after network errors (default 60)
approval_timeout_seconds = 300   # an unanswered tier-2 approval is a timeout (default 300)

[component.example]
nodes = ["mac", "arm"]
```

## The shipped file

This is the template `tau init` writes, verbatim; it equals the repository's own `tau.toml`, and a test keeps the two identical.

```toml
# tau.toml — static configuration read by tau_core.config.Config.
# Role → provider + model id. Model ids are data; code never hardcodes them.
# Secrets never go here: credentials come from .env (see .env.example).
#
# provider = "proxy": the role goes through the LiteLLM proxy (infra/litellm, ADR 0009).
# model_id is the proxy's model group, infra/litellm/config.yaml maps it to a real model, and the
# role's own virtual key (TAU_PROXY_KEY_<GROUP>, written by `tau proxy keys`) carries the
# budget. `tau init` without a proxy key writes direct providers (anthropic, ollama) and drops
# the budget tables, which only the proxy can enforce.

[models.roles.brain]
provider = "proxy"                        # proxy | anthropic | bedrock | ollama | fake
model_id = "brain"
max_tokens = 4096

[models.roles.brain.budget]               # hard cap of the role's proxy key; `tau proxy keys` applies changes
usd = 15                                  # dollars per period
period = "1mo"                            # LiteLLM budget_duration: 1d, 7d, 1mo, ... (resets in UTC)
degrade_to = "fast"                       # once spent, this role answers until the reset; omit to stop and say so

[models.roles.fast]
provider = "proxy"
model_id = "fast"
max_tokens = 1024

[models.roles.fast.budget]
usd = 1
period = "1d"

[models.roles.local]
provider = "proxy"                        # Ollama on the Mac; the proxy answers with fast when Ollama is away
model_id = "local"
max_tokens = 1024

[models.roles.local.budget]               # Ollama is free; the cap bounds what the fast fallback may spend
usd = 0.5
period = "1d"

# Optional per-role prompt caching for the direct Anthropic and Bedrock providers (the proxy and
# the fake provider ignore it):
# [models.roles.brain.cache]
# strategy = "auto"                       # auto | anthropic; Strands CacheConfig(strategy=...)
# ttl = "1h"                              # optional cache TTL ("5m", "1h"); system_prompt_ttl / tools_ttl take a bool or a TTL

[agent]
max_turns = 12                            # per-turn loop guard, Strands Limits(turns=...)
context = "sliding"                       # sliding | summarize: what the model sees of a long session (the store keeps everything)
                                          # A session remembers this value; to resume it after a change, set it back or start a new session.
window_size = 60                          # sliding: messages kept; summarize: recent messages never summarized
# max_total_tokens = 200000               # optional per-turn token budget, Strands Limits(total_tokens=...)

[sessions]
backend = "file"                          # memory | file (under TAU_DATA_DIR/sessions); the store stays on the hub (ADR 0006)

[hub]
control_port = 7877
heartbeat_seconds = 5

[ui]
language = "en"                           # en | tr: chrome of the terminal and the TUI (commands, notices, approval prompt).
                                          # TAU_LANG or `tau --lang` override it; /lang switches it for one run.

# Components (see `tau components`): switch discovered parts on or off without uninstalling.
# Unknown keys in these tables are an error (a typo must not leave a tool switched on);
# a name nothing installed provides is a `tau doctor` warning.
# [components]
# context = []                            # enabled tau.context sources; empty = every discovered one
# [components.tools]
# disabled = ["demo_physical_action", "dist:tau-example-tool"]   # tool names or dist:<distribution>
# [components.hub]
# services = []                           # enabled tau.hub_services; empty = every discovered one
#
# Free tables for a component's own settings, read with Config.component("name"):
# [component.telegram]
# poll_timeout_seconds = 50
```

`tau init` writes it unchanged when it picks the `proxy` provider (`TAU_PROXY_KEY_BRAIN` is present). For any other provider it rewrites `brain` and `fast` to that provider with the model ids of its shipped `models.toml` table, points `local` at `ollama` with `model_id = "qwen3.5:9b"`, and drops the `budget` tables, which only the proxy enforces. `tau init --provider fake`, for example, gives `brain` and `fast` `provider = "fake"` with the ids `fake-brain` / `fake-fast`, and `tau init --provider anthropic` gives them `claude-sonnet-5` / `claude-haiku-4-5`.

## Errors you may see

All `ConfigError` messages are plain English, since they are raised before any channel exists:

| Message | Cause |
|---|---|
| `Configuration file not found: <path>. Set TAU_HOME or run from the repository root.` | no `tau.toml` in the resolved root |
| `tau.toml: [models.roles.brain] needs a 'provider'.` | a required key is missing |
| `tau.toml: [models.roles.brain] has unknown keys: model.` | a typo inside a role table |
| `tau.toml: unknown provider for role 'brain': 'x'. Valid values: …` | a provider no distribution declares |
| `tau.toml: [models.roles.brain] 'budget' must be a table.` | `budget = 15` instead of a table |
| `tau.toml: [models.roles.brain] 'budget' has unknown keys: cap.` | a typo inside the budget |
| `tau.toml: [models.roles.brain] 'budget' needs 'usd', a positive number of dollars.` | `usd` missing, zero, negative or not a number |
| `tau.toml: [models.roles.brain] 'budget' needs 'period' like "1d", "7d" or "1mo" (a number followed by s, m, h, d or mo).` | `period` missing or in another form, e.g. `"month"` |
| `tau.toml: [models.roles.brain] 'budget' 'degrade_to' must be the name of a role.` | `degrade_to` empty or not a string |
| `tau.toml: [models.roles.brain] 'budget.degrade_to' cannot name the role itself.` | `degrade_to = "brain"` on `brain` |
| `tau.toml: [models.roles.brain] 'budget.degrade_to' names 'cheap', which is not a defined role.` | `degrade_to` names a role the file does not define |
| `tau.toml: [models.roles.brain] 'budget.degrade_to' loops: brain → fast → brain.` | two roles that degrade to each other |
| `tau.toml: [models.roles.brain.fallback] cannot have a 'budget'; set it on the role.` | a budget inside a `fallback` table |
| `tau.toml: [agent] 'context' must be one of sliding, summarize, not 'auto'.` | an SDK preset or a typo |
| `tau.toml: [components.tools] has unknown keys: disable.` | a misspelled switch |
| `TAU_LANG must be one of en, tr, not 'de'.` | an unsupported language |
| `Session <id> was recorded with a different [agent] context setting; set it back to sliding or start a new session` | resuming after changing `context` |
