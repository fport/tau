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
| `provider` | string | required | `bedrock`, `anthropic`, `fake`, or the name of a `tau.providers` component. `ollama` is accepted and fails at use until issue 012. |
| `model_id` | string | required | The provider's model id. Data, never code. Bedrock ids use the Converse form with the `global.` prefix. |
| `region` | string | none | Bedrock region. When set, `AWS_REGION` is no longer required for this role. |
| `max_tokens` | integer ≥ 1 | provider default (4096 for Anthropic) | Output token limit per call. |
| `params` | table | `{}` | Passed to the provider's model as extra parameters, except the tau-specific keys below. |
| `fallback` | table | none | A second role table with the same keys (no nested fallback). Used only when the primary provider's credentials are missing. |
| `cache` | table | none | Prompt-cache settings, see below. |

`params` keys tau reads itself (not forwarded):

| Key | Providers | Meaning |
|---|---|---|
| `api_key_env` | anthropic | The variable that holds the key, instead of `ANTHROPIC_API_KEY`. |
| `base_url` | anthropic | An alternative API base URL (a proxy). |
| `workspace_id` | anthropic | The workspace id sent as `anthropic-workspace-id`; `ANTHROPIC_WORKSPACE_ID` in the environment does the same. |

### `[models.roles.<role>.cache]`

Maps to Strands' `CacheConfig`. Bedrock and Anthropic honour it; `fake` ignores it.

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
chat_id_env = "TELEGRAM_CHAT_ID"

[component.example]
nodes = ["mac", "arm"]
```

## The shipped file

```toml
[models.roles.brain]
provider = "bedrock"                      # bedrock | anthropic | fake (ollama: issue 012)
model_id = "global.anthropic.claude-sonnet-5"
max_tokens = 4096

[models.roles.brain.fallback]             # used only when the primary has no credentials
provider = "anthropic"
model_id = "claude-sonnet-5"

[models.roles.fast]
provider = "bedrock"
model_id = "global.anthropic.claude-haiku-4-5"
max_tokens = 1024

[models.roles.fast.fallback]
provider = "anthropic"
model_id = "claude-haiku-4-5-20251001"

[models.roles.local]
provider = "ollama"                       # arrives in issue 012; resolving it now raises a clear error
model_id = "qwen3:8b"

[agent]
max_turns = 12
context = "sliding"
window_size = 60
# max_total_tokens = 200000

[sessions]
backend = "file"

[hub]
control_port = 7877
heartbeat_seconds = 5

[ui]
language = "en"
```

`tau init --provider fake` writes the same file with `provider = "fake"` and the ids `fake-brain` / `fake-fast` for the two roles.

## Errors you may see

All `ConfigError` messages are plain English, since they are raised before any channel exists:

| Message | Cause |
|---|---|
| `Configuration file not found: <path>. Set TAU_HOME or run from the repository root.` | no `tau.toml` in the resolved root |
| `tau.toml: [models.roles.brain] needs a 'provider'.` | a required key is missing |
| `tau.toml: [models.roles.brain] has unknown keys: model.` | a typo inside a role table |
| `tau.toml: unknown provider for role 'brain': 'x'. Valid values: …` | a provider no distribution declares |
| `tau.toml: [agent] 'context' must be one of sliding, summarize, not 'auto'.` | an SDK preset or a typo |
| `tau.toml: [components.tools] has unknown keys: disable.` | a misspelled switch |
| `TAU_LANG must be one of en, tr, not 'de'.` | an unsupported language |
| `Session <id> was recorded with a different [agent] context setting; set it back to sliding or start a new session` | resuming after changing `context` |
