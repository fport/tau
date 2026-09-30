# Configure

Two files configure tau. `tau.toml` is static data: which model serves which role, how long a turn may run, where sessions go. `.env` holds credentials and the few environment variables that pick the roots. This page walks through both; the [tau.toml reference](../reference/tau-toml.md) and the [environment reference](../reference/environment.md) list every key.

!!! note "Config versus Settings"
    tau uses the word **config** for these two files, read once at start-up; the TUI's `/settings` screen and the terminal's `/settings` command edit them in place. **Settings** are runtime values that will change while tau runs (ambient mode, retention, notification preferences). Those live in a file under `TAU_DATA_DIR` and are hot-reloaded; they are planned in roadmap issue 019 and are not part of this page.

## Edit from the interface

You do not have to open the files. In `tau tui`, `/settings` (alias `/ayarlar`) or F10 opens an editor with six sections: **Model roles**, **Credentials**, **Interface**, **Agent**, **Doctor** and **Files**. `↑↓` picks a section, Tab moves through its fields, `ctrl+s` or F2 saves, Esc closes. A save is validated first (a bad value stays in the dialog with the reason in the status line), keeps the comments in `tau.toml`, keeps `.env` at mode `0600`, and rebuilds the agent on the same session when something that affects the model changed. [First run](first-run.md#in-the-interface-tau-tui) shows the screen.

The provider select offers only providers that are built. A planned one (a provider a later roadmap issue builds; there is none today) is listed in a note and cannot be chosen, because a role on it cannot start; a role that already names it is left as it is, and should a stored `tau.toml` ever put `brain` on it, `tau tui` still opens, without an agent, on the Model roles section so you can pick another provider. The editor changes a role's provider and model id but leaves its `budget` table alone; edit budgets in the file and run `tau proxy keys` (see [Model proxy and budgets](../guides/model-proxy.md)). A credential row also says when its value comes from your shell environment: `.env` never overrides a variable that is already set, so a value you save there would not be used at the next start until you unset the shell's.

`tau chat` has the terminal form:

```text
you> /settings
Settings · ~/.tau
Model roles:
  brain  proxy · brain · credentials ok
  fast   proxy · fast · credentials ok
  local  proxy · local · missing TAU_PROXY_KEY_LOCAL
UI language: en · profile: home
Context: sliding, window 60 · max_turns 12 · max_total_tokens none
Files:
  tau.toml            ~/.tau/tau.toml · present
  …
Change: /settings language en|tr · /settings profile NAME · /settings model ROLE PROVIDER MODEL_ID · /settings set NAME · /settings clear NAME. …
```

`/settings language tr`, `/settings profile travel` and `/settings model brain anthropic claude-sonnet-5` write the value and reload; `/settings set ANTHROPIC_API_KEY` asks for the value with a hidden prompt (nothing is echoed) and `/settings clear NAME` removes it. The Python API behind both channels is `tau_core.settings` (see the tau-core README).

The rest of this page is the files themselves.

## Roles, not model ids

Code never names a model. It asks for a **role** and `tau.toml` maps the role to a provider and a model id. By default every role goes through the **model proxy**, a LiteLLM proxy tau runs in Docker on the hub (`infra/litellm`), which puts a hard spend cap on each role. The shipped file:

```toml
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
```

- **`brain`** is the conversation and planning model (Claude Sonnet 5). `tau chat` and `tau tui` use it unless you say otherwise (`--role`, `/model`).
- **`fast`** is for triage and summaries (Claude Haiku 4.5). Today it is available through `/model fast`; later layers use it for memory extraction.
- **`local`** is an on-device model through Ollama on the Mac (`qwen3.5:9b` recommended). When Ollama is not reachable, the proxy answers with `fast` instead.

With `provider = "proxy"`, `model_id` is not a model id but the proxy's **model group**; `infra/litellm/config.yaml` maps each group to a real model. Each role calls with its own virtual key (`TAU_PROXY_KEY_BRAIN`, `…_FAST`, `…_LOCAL`), and the key carries the role's **budget**: `usd` per `period`. When a budget is spent, the `degrade_to` role answers until the reset, or, without one, tau tells you when the budget resets. Setting the proxy up is one guide: [Model proxy and budgets](../guides/model-proxy.md).

**Without the proxy.** The direct `anthropic` provider works without Docker. It is what `tau init` writes when it finds `ANTHROPIC_API_KEY` but no proxy key: `brain` and `fast` call Anthropic directly, `local` calls Ollama directly (`provider = "ollama"`, `model_id = "qwen3.5:9b"`), and the `budget` tables are left out, because nothing but the proxy would enforce them:

```toml
[models.roles.brain]
provider = "anthropic"
model_id = "claude-sonnet-5"
max_tokens = 4096

[models.roles.fast]
provider = "anthropic"
model_id = "claude-haiku-4-5"
max_tokens = 1024

[models.roles.local]
provider = "ollama"
model_id = "qwen3.5:9b"
max_tokens = 1024
```

`bedrock` stays available as an optional direct provider for installations that want it; tau's own setup no longer uses it.

A role may have one **`fallback`** table with the same keys. The fallback is used only when the primary provider's credentials are missing; `tau doctor` and `/status` tell you when that happens. The shipped file defines none: on a `proxy` role a fallback would bypass the budget whenever the key is missing.

**Prompt caching** is optional and per role. The direct Anthropic and Bedrock providers honour it; `proxy`, `ollama` and `fake` ignore it:

```toml
[models.roles.brain.cache]
strategy = "auto"                         # auto | anthropic
ttl = "1h"                                # optional: "5m", "1h"
# system_prompt_ttl = true               # bool or a TTL
# tools_ttl = "5m"
```

!!! tip
    Model ids are data. In proxy mode the real ids live in `infra/litellm/config.yaml` and `tau.toml` names only the groups; in direct mode they are in `tau.toml` (Bedrock ids use the Converse API form with the cross-region `global.` prefix). A wrong id is a model error at the first call, not a config error.

## `[agent]`: turns, context and budget

```toml
[agent]
max_turns = 12                            # model calls per user turn (loop guard)
context = "sliding"                       # sliding | summarize
window_size = 60                          # sliding: messages kept; summarize: recent messages never summarized
# max_total_tokens = 200000               # optional per-turn token budget
```

- **`max_turns`** caps how many model calls one of your messages may trigger. When tau hits it, the tools of the last call still run, tau stops and says so, and you decide whether it continues.
- **`context`** picks what the model sees of a long session. `sliding` sends the last `window_size` messages. `summarize` keeps the last `window_size` messages verbatim and a summary of the rest. The session store keeps every message either way.
- **`max_total_tokens`** is an optional per-turn token budget. When it is reached tau stops the turn with a notice.

!!! warning "Changing `context` after the fact"
    A session remembers the context mode it was recorded with. After you switch `sliding` to `summarize`, an older session refuses to open with `Session <id> was recorded with a different [agent] context setting; set it back to sliding or start a new session`. Nothing is lost; set the value back or start fresh. Details in [Sessions and compaction](../reference/sessions.md).

## `[sessions]`

```toml
[sessions]
backend = "file"                          # memory | file
```

`file` writes one directory per session under `TAU_DATA_DIR/sessions/` and is what the shipped file sets. `memory` keeps sessions in the process and is for tests and throwaway runs. When the key is absent the code defaults to `memory`, so keep the line.

## `[hub]`

```toml
[hub]
control_port = 7877
heartbeat_seconds = 5
```

The hub's control API listens on `127.0.0.1:<control_port>` only and answers `GET /health`, `GET /status` and, from the `spend` service, `GET /spend` (what every proxy role spent in its period). `TAU_HUB_PORT` overrides the port. The heartbeat is how often the running hub refreshes its state file; `tau hub status` reads it. See [Run tau as a service](../guides/hub-service.md).

## `[ui]`

```toml
[ui]
language = "en"                           # en | tr
```

The **UI language** is the language of the chrome: slash-command help, notices, the approval prompt, pane titles and key hints. It is not the language tau answers in; the persona decides that and mirrors yours. `TAU_LANG` overrides the file, `tau --lang tr …` overrides both for one run, and `/lang en|tr` switches it inside a session.

## `[components]`: switch parts on or off

Everything pluggable in tau is a component, discovered through entry points and listed by `tau components`. The `[components]` table disables tools and picks context sources and hub services without uninstalling anything:

```toml
[components]
context = []                              # enabled tau.context sources; empty = every discovered one

[components.tools]
disabled = ["demo_physical_action", "dist:tau-example-tool"]   # tool names or dist:<distribution>

[components.hub]
services = []                             # enabled tau.hub_services; empty = every discovered one
```

- `tools.disabled` can only remove tools. It never adds one, gives one a tier or changes a tier.
- An unknown key inside these tables is an error, so a typo such as `disable` cannot leave a tool switched on by accident.
- A name that no installed component provides is a `tau doctor` warning, not an error.

A component's own settings go into a free `[component.<name>]` table:

```toml
[component.telegram]
chat_id_env = "TELEGRAM_CHAT_ID"
```

Any other top-level table in `tau.toml` is logged once and ignored. [Components and plugins](../reference/components.md) has the full picture.

## Roots and identity: the environment

Four variables decide where tau reads and writes and who it is. Set them in your shell or in `<root>/.env`; the defaults cover a single-user machine.

| Variable | Default | Meaning |
|---|---|---|
| `TAU_HOME` | the current directory if it holds `tau.toml`, else `~/.tau` | The configuration root: `tau.toml`, `.env`, `persona/`, `tools/`. `tau --home DIR` wins over it. |
| `TAU_DATA_DIR` | `~/.local/share/tau` | Mutable state: `sessions/`, `hub/`, `logs/`. Never inside a repository. |
| `TAU_PROFILE` | `home` | The active profile: `home`, `travel` or `sport`. `tau --profile NAME` wins over it. |
| `TAU_LANG` | `[ui] language` | UI language override, `en` or `tr`. `tau --lang` wins over it. |

Two more exist for later layers: `TAU_ROLE` (`hub` or `node`, default `hub`; the mesh in layer 5 uses it) and `TAU_HUB_PORT`.

```sh
# ~/.tau/.env
TAU_DATA_DIR=~/tau-data
TAU_PROFILE=home
ANTHROPIC_API_KEY=sk-ant-...
```

!!! note "Precedence, once"
    Command-line option → environment variable → `.env` → `tau.toml` → built-in default. A variable already set in your shell is never overridden by `.env`.

## Persona files

`persona/persona.md` is tau's character and is safe to publish. `persona/user.md` is the facts about you and is private. Both are re-read when they change, before the next model call, so an edit needs no restart. Keep `persona.md` non-empty: a missing or empty file stops `tau chat` at start-up with a `ConfigError`; a file that breaks while tau runs keeps its last good version in use.

## After a change

```sh
tau doctor        # config, roles, credentials, persona, components
tau components    # what is discovered, enabled and in use
```

Neither starts a model. After changing a `budget`, also run `tau proxy keys` so the proxy enforces the new cap. Inside a running session, `/status` shows the resolved model per role, the context mode and window, the tool counts and, with the proxy, each role's spend against its budget; `/settings` shows the files' values and lets you change them, and the TUI's **Doctor** section runs the same checks as `tau doctor`.
