# tau.toml

`tau.toml` is tau's static configuration, read once at start-up by `tau_core.config.Config`. It lives in the configuration root (`TAU_HOME`); `tau init` writes it from a shipped template that equals the repository's own file. This page lists every table and key with its type and default.

Rules that apply everywhere:

- Top-level tables tau reads: `models`, `agent`, `sessions`, `hub`, `ui`, `components`, `component`. Any other top-level table is logged once and ignored, never an error (a typo such as `[model]` shows up in `tau doctor` as a warning).
- Inside a role table, a `[models.prices]` table and `[components]`, an unknown key **is** an error, so a misspelled switch cannot silently leave a tool on.
- Provider and backend names are validated at load time by name only; nothing is imported until a role is used.
- Secrets never go here. Credentials come from the environment or `.env`.

## `[models.roles.<role>]`

One table per role. The shipped file defines `brain`, `fast` and `local`; any name is allowed, and `tau chat --role` or `/model` can pick it. [Models and budgets](../guides/models-and-budgets.md) explains the roles, the providers and the budgets.

| Key | Type | Default | Meaning |
|---|---|---|---|
| `provider` | string | required | `anthropic`, `openai`, `gemini`, `ollama`, `bedrock`, `fake`, or the name of a `tau.providers` component. Every provider is called directly. |
| `model_id` | string | required | Data, never code: the provider's model id (`claude-sonnet-5`, `gpt-6-luna`, `gemini-3.5-flash`), for `ollama` the Ollama model name (`qwen3.5:9b`). Bedrock ids use the Converse form with the `global.` prefix. The id also picks the price (see [`[models.prices]`](#modelsprices)). |
| `region` | string | none | Bedrock region. When set, `AWS_REGION` is no longer required for this role. |
| `max_tokens` | integer ≥ 1 | provider default (4096 for `anthropic`, `openai`, `gemini` and `ollama`) | Output token limit per call. `openai` sends it as `max_completion_tokens`, `gemini` as `max_output_tokens`. |
| `params` | table | `{}` | Passed to the provider's model as extra parameters, except the tau-specific keys below. The shipped `local` role sets `reasoning_effort = "none"`. |
| `fallback` | table | none | A second role table with the same keys (no nested fallback, no `budget`, no `failover`). Used only when the primary provider's credentials are missing. |
| `cache` | table | none | Prompt-cache settings, see below. |
| `budget` | table | none | The role's hard spend cap per day, week or month, enforced by tau; see below. |
| `failover` | string | none | Another role that answers when this role's model cannot be reached; see below. |

`params` keys tau reads itself (not forwarded):

| Key | Providers | Meaning |
|---|---|---|
| `api_key_env` | anthropic, openai, gemini | The variable that holds the key, instead of `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` or `GEMINI_API_KEY`/`GOOGLE_API_KEY`. |
| `base_url` | anthropic, openai, ollama | anthropic: an alternative API base URL. openai: any OpenAI-compatible API. ollama: the Ollama server, else `TAU_OLLAMA_URL`, else `http://127.0.0.1:11434`; give it without `/v1`, tau appends it. |
| `workspace_id` | anthropic | The workspace id sent as `anthropic-workspace-id`; `ANTHROPIC_WORKSPACE_ID` in the environment does the same. |

`ollama` needs no credentials. It connects with a 3-second timeout and never retries, so a role's `failover` answers within seconds while Ollama is away.

### `[models.roles.<role>.budget]`

The role's hard spend cap. tau enforces it itself: every answer's token usage is priced and recorded in the ledger under `TAU_DATA_DIR` (`spend.sqlite3`), and before every call the role's spend in the current period is compared with the cap. It works the same for every provider. A table or an inline table (`budget = { usd = 1, period = "day" }`) both work.

| Key | Type | Default | Meaning |
|---|---|---|---|
| `usd` | number > 0 | required | Dollars per period. |
| `period` | `"day"` \| `"week"` \| `"month"` | required | A calendar period in Europe/Istanbul: a day resets at midnight, a week on Monday at 00:00, a month on the 1st at 00:00. |
| `degrade_to` | string | none | Another role defined in this file that answers once this budget is spent, until the reset. Omit it to end the turn and tell the user when the budget resets. |

```toml
[models.roles.brain.budget]
usd = 15
period = "month"
degrade_to = "fast"
```

- `budget` is not allowed inside a `fallback` table; set it on the role.
- A change applies when tau starts: restart the hub and reopen `tau chat` / `tau tui`. `tau spend` and `tau doctor` read the file each time.
- A budgeted role whose model has no price counts its calls as $0; `tau doctor` warns (`role brain: has a budget, but model 'my-model' has no price, so its calls count as $0; add [models.prices."my-model"] to tau.toml`).
- Only roles with a `budget` or a `failover` are metered; `tau spend` shows the others as `no budget (its calls are not counted)`.
- When the budget is spent, the channel shows `The brain budget is spent until 01.10.2026 00:00; fast answered instead.` (with `degrade_to`) or `The brain budget is spent ($15.00 of $15.00) and resets at 01.10.2026 00:00. To raise the cap, change it in tau.toml.` (without), in the UI language.

### `failover`

`failover = "<role>"` names the role that answers when this role's model cannot be reached before anything streamed: the connection is refused or times out, or the provider answers with a 5xx. Throttling is left to Strands' retry. The channel then shows `local is not reachable right now; fast answered instead.` and the hub log a warning. The shipped `local` role (Ollama) fails over to `fast`.

`budget.degrade_to` and `failover` must both name another defined role, not the role itself, and following them from role to role must not loop, alone or together: `brain` degrading to `fast` while `fast` fails over to `brain` is refused. A stand-in is an ordinary role: its own budget and failover apply, and its spend counts under its own name.

### `[models.roles.<role>.cache]`

Maps to Strands' `CacheConfig`. Anthropic and Bedrock honour it; `openai`, `gemini`, `ollama` and `fake` ignore it.

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

## `[models.prices]`

What a model costs, in US dollars per million tokens, one table per model id. tau-core ships a price table (`templates/prices.toml`); these tables extend it or override it for the same id. The shipped file has none.

| Key | Type | Default | Meaning |
|---|---|---|---|
| `input` | number ≥ 0 | required | Dollars per million input tokens. |
| `output` | number ≥ 0 | required | Dollars per million output tokens. |
| `cache_read` | number ≥ 0 | `input` | Dollars per million tokens read from the prompt cache. |
| `cache_write` | number ≥ 0 | `input` | Dollars per million tokens written to the prompt cache. |

```toml
[models.prices."my-model"]
input = 0.5
output = 1.5
cache_read = 0.05
```

The id is quoted because model ids contain dots and colons. `ollama` and `fake` are always free. A model that is in neither table is unpriced: its calls are recorded without a cost. The shipped prices are listed in [Models and budgets](../guides/models-and-budgets.md#prices).

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
# Providers are called directly (ADR 0011). A budget caps what a role may spend per day, week or
# month (Europe/Istanbul); tau prices every answer and keeps the spend under TAU_DATA_DIR
# (`tau spend`). Prices come from tau-core's prices.toml; a model it does not know needs a
# [models.prices."<model_id>"] table (input, output, cache_read, cache_write in $ per 1M tokens).

[models.roles.brain]
provider = "anthropic"                    # anthropic | openai | gemini | ollama | bedrock | fake
model_id = "claude-sonnet-5"
max_tokens = 4096

[models.roles.brain.budget]               # a hard cap tau enforces itself
usd = 15                                  # dollars per period
period = "month"                          # day | week | month; resets at midnight, on Monday, on the 1st
degrade_to = "fast"                       # once spent, this role answers until the reset; omit to stop and say so

[models.roles.fast]
provider = "anthropic"
model_id = "claude-haiku-4-5"
max_tokens = 1024

[models.roles.fast.budget]
usd = 1
period = "day"

[models.roles.local]
provider = "ollama"                       # Ollama on this machine; TAU_OLLAMA_URL points at another (the Mac over the tailnet)
model_id = "qwen3.5:9b"                   # answers well in Turkish; `ollama pull qwen3.5:9b`
max_tokens = 1024
params = { reasoning_effort = "none" }    # answer at once instead of reasoning first
failover = "fast"                         # answers while Ollama is not reachable (a sleeping or absent Mac)

# Optional per-role prompt caching (Anthropic and Bedrock; the other providers ignore it):
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

`tau init` writes it unchanged for the `anthropic` provider. For another provider it rewrites only the `provider` and `model_id` of `brain` and `fast`, with the model ids of its shipped `models.toml` table: `gpt-6.1-sol` / `gpt-6-luna` for `openai`, `gemini-3.5-flash` / `gemini-3.1-flash-lite` for `gemini`, `global.anthropic.claude-sonnet-5` / `global.anthropic.claude-haiku-4-5` for `bedrock`, `fake-brain` / `fake-fast` for `fake`. The budget tables stay, since tau enforces them for every provider, and `local` stays on Ollama with its failover.

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
| `tau.toml: [models.roles.brain] 'budget' needs 'period', one of day, week, month.` | `period` missing or in another form, e.g. `"1mo"` |
| `tau.toml: [models.roles.brain] 'budget' 'degrade_to' must be the name of a role.` | `degrade_to` empty or not a string |
| `tau.toml: [models.roles.brain] 'budget.degrade_to' cannot name the role itself.` | `degrade_to = "brain"` on `brain` |
| `tau.toml: [models.roles.brain] 'budget.degrade_to' names 'cheap', which is not a defined role.` | `degrade_to` names a role the file does not define |
| `tau.toml: [models.roles.brain] 'failover' must be the name of a role.` | `failover` empty or not a string |
| `tau.toml: [models.roles.brain] 'failover' cannot name the role itself.` | `failover = "brain"` on `brain` |
| `tau.toml: [models.roles.local] 'failover' names 'cheap', which is not a defined role.` | `failover` names a role the file does not define |
| `tau.toml: [models.roles.brain] stand-ins loop: brain → fast → brain (budget.degrade_to and failover together).` | `degrade_to` and `failover` that lead back to a role, e.g. `brain` degrades to `fast` and `fast` fails over to `brain` |
| `tau.toml: [models.roles.brain.fallback] cannot have a 'budget'; set it on the role.` | a budget inside a `fallback` table (the same for `failover`) |
| `tau.toml: [models.prices."my-model"] needs 'input' and 'output' (dollars per million tokens).` | a price table without `input` or `output` |
| `tau.toml: [models.prices."my-model"] has unknown keys: cached.` | a typo inside a price table |
| `tau.toml: [models.prices."my-model"] 'input' must be a number of dollars, 0 or more.` | a negative or non-numeric price |
| `tau.toml: [agent] 'context' must be one of sliding, summarize, not 'auto'.` | an SDK preset or a typo |
| `tau.toml: [components.tools] has unknown keys: disable.` | a misspelled switch |
| `TAU_LANG must be one of en, tr, not 'de'.` | an unsupported language |
| `Session <id> was recorded with a different [agent] context setting; set it back to sliding or start a new session` | resuming after changing `context` |
