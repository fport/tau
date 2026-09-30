# Components and plugins

A **component** is any pluggable part of tau: a tool, a subcommand, a model provider, a session backend, a context source or a hub service. Components reach tau through a built-in seed, an entry point in a `tau.*` group declared by any installed distribution, or an in-process registration. `tau.toml` decides which discovered components are on, and `tau components` shows all of them. The rule that makes this safe: **a component that fails to load is logged with its distribution name and skipped; it never breaks the CLI, and a tool that reaches the agent behind the catalog's back is refused.** The decision is [ADR 0005](../adr/0005-components-and-entry-point-groups.md).

A *plugin* is a third-party distribution that provides components. To write one, see [Write a plugin](../contributing/plugins.md).

## The six entry-point groups

| Group | Entry point value | Picked by |
|---|---|---|
| `tau.tools` | an `AgentTool` with a tier (`@tau_tool`), a list of them, or a zero-argument factory | `build_agent`, all of them minus `[components.tools] disabled` |
| `tau.commands` | a `click.Command`, mounted as `tau <name>` | the `tau` command |
| `tau.providers` | `factory(RoleConfig, env) -> Model`; optional `required_env = [["VAR", …], …]` on the factory (credential alternatives) | a role's `provider` in `tau.toml` |
| `tau.sessions` | `factory(Config) -> SessionStore` | `[sessions] backend` |
| `tau.context` | `factory(Config) -> ContextSource` (a callable returning `{"nodes": …, "budget": …}`) | `build_agent` when no explicit `context_sources` are passed, minus what `[components] context` leaves out |
| `tau.hub_services` | `factory(Config) -> HubService` | `tau hub run`, after the control API, minus what `[components.hub] services` leaves out |

`tau.channels` is reserved for hub-hosted channels; a channel that runs inside the hub ships a `tau.hub_services` entry point today, as tau-core's own `telegram` service does ([Telegram](../guides/telegram.md)).

### Precedence

- A **seed** name (`anthropic`, `openai`, `gemini`, `ollama`, `bedrock`, `fake`, `memory`, `file`) wins over an entry point of the same name; the entry point is logged and ignored, so an installed package cannot silently replace `bedrock`.
- An **in-process registration** (`register_provider`, `register_session_backend`) replaces anything, because it is explicit code.
- `Config.load` validates provider and backend **names** without loading any entry point, so `tau version` and `tau hub status` never import a provider SDK. A name that is declared but fails to load errors when the role is resolved, with the entry point's own error: `Model provider 'x' from <distribution> failed to load: …`. Only a name no distribution declares is an `Unknown model provider`.

## `[components]` in `tau.toml`

```toml
[components]
context = []                 # enabled tau.context sources; empty = every discovered one

[components.tools]
disabled = ["demo_physical_action", "dist:tau-example-tool"]   # tool names or dist:<distribution>

[components.hub]
services = []                # enabled tau.hub_services; empty = every discovered one

[component.telegram]         # a component's own settings: Config.component("telegram")
poll_timeout_seconds = 50
```

- `tools.disabled` can only remove tools. It never adds one, gives one a tier or changes a tier. An explicit `build_agent(tools=[...])` bypasses it.
- Unknown keys inside `[components]`, `[components.tools]` and `[components.hub]` are a `ConfigError`, so a typo such as `disable` cannot leave a tool switched on.
- A name nothing installed provides is a `tau doctor` warning.
- Nothing in `[components]` can replace the tier gate, the approver or the catalog.

## `tau components`

```sh
tau components
tau components --json
```

In a repository checkout with the `dev` group installed, the listing also shows `tau-net`, `tau-cloud` and the three test-fixture distributions (`tau-example-*`); a plain install shows only `tau-core` and `tau-tui`:

```text
tau.tools
  example_echo          tau-example-tool 0.0.1  enabled  tier 0
  current_time          tau-core 0.3.1          enabled  tier 0
  demo_physical_action  tau-core 0.3.1          enabled  tier 2
  net_contacts          tau-net 0.1.0           enabled  tier 0
  net_log               tau-net 0.1.0           enabled  tier 0
  net_send              tau-net 0.1.0           enabled  tier 2
tau.commands
  chat        tau-core 0.3.1   enabled  tau chat
  components  tau-core 0.3.1   enabled  tau components
  doctor      tau-core 0.3.1   enabled  tau doctor
  hub         tau-core 0.3.1   enabled  tau hub
  init        tau-core 0.3.1   enabled  tau init
  spend       tau-core 0.3.1   enabled  tau spend
  tui         tau-tui 0.3.1    enabled  tau tui
  net         tau-net 0.1.0    enabled  tau net
  cloud       tau-cloud 0.1.0  enabled  tau cloud
tau.providers
  anthropic  tau-core 0.3.1              enabled  in use: brain, fast (built-in)
  openai     tau-core 0.3.1              enabled  available (built-in)
  gemini     tau-core 0.3.1              enabled  available (built-in)
  ollama     tau-core 0.3.1              enabled  in use: local (built-in)
  bedrock    tau-core 0.3.1              enabled  available (built-in)
  fake       tau-core 0.3.1              enabled  available (built-in)
  fake2      tau-example-provider 0.0.1  enabled  available
tau.sessions
  memory   tau-core 0.3.1              enabled  available (built-in)
  file     tau-core 0.3.1              enabled  in use (built-in)
  example  tau-example-provider 0.0.1  enabled  available
  spine    tau-cloud 0.1.0             enabled  available
tau.context
  example  tau-example-service 0.0.1  enabled
  budget   tau-core 0.3.1             enabled
tau.hub_services
  example   tau-example-service 0.0.1  enabled
  spend     tau-core 0.3.1             enabled
  telegram  tau-core 0.3.1             enabled
  net       tau-net 0.1.0              enabled
```

The `budget` context source, the `spend` hub service and the `spend` command are tau-core's three readers of the spend ledger ([Models and budgets](../guides/models-and-budgets.md)).

Columns: name, distribution and version, `enabled`/`disabled` (from `[components]`), then a note: `tier N` for a tool (or `no tier: never registered`), `tau <name>` for a command, `in use: <roles>` / `available` / `planned` for a provider, `in use` / `available` for a backend, and the load error for anything that failed. `--json` gives the same rows as objects with `group`, `name`, `distribution`, `version`, `source` (`built-in`, `entry point`, `registered`, `planned`), `enabled`, `note`, `error`.

## Fail-closed rules

These are the invariants every component runs under. They are what makes an untrusted plugin safe to install.

1. **A tool without a tier is never registered.** `@tau_tool(tier=…)` records the tier in the tool spec; a plain Strands `@tool` raises `UntieredToolError` in the catalog, is refused by `build_agent(tools=[…])` and is skipped with a warning when a plugin ships it.
2. **An unknown tool is refused, not run.** Every call is looked up live in the `ToolCatalog`; a tool that reached the Strands agent through a `Plugin` or another side door is refused with `Tool '<name>' is not registered; it was not run.` and an `error` event.
3. **The tier gate has the last word.** `TierHook` is registered at `HookOrder.SDK_LAST`; `build_agent` raises a `ConfigError` for any hook registered above it, so no plugin hook can rewrite a call after it was approved. A hook added to the SDK agent *after* build cannot be refused; the gate then records a refused call that ran, or an approved call whose arguments changed, as an `error` with `where: tier_gate`.
4. **Nothing approves on its own.** No component can replace the approver; a channel passes its own `Approver` to `build_agent`, and the default rejects.
5. **A broken component is skipped, never fatal.** An entry point that fails to import or returns the wrong kind of object is logged with its distribution and left out; `tau components` and `tau doctor` show the error.
6. **A hub service is optional.** One that fails to build or start is logged and skipped; the hub runs on. Control API routes are additive only: `add_route` raises for a `(method, path)` that exists, so no service can replace `GET /health`, `GET /status` or another service's route.
7. **Tiers come from the process, not from the wire.** The `annotations["tau"]` block in a tool spec is authoritative only for tools registered in-process. A spec that arrives from outside (an MCP tool provider, layer 5) has it stripped and gets its tier from the hub's own configuration.
8. **`tools.disabled` only removes.** It cannot add, promote or demote a tool.

## In code

```python
from tau_core import register_provider, register_session_backend
from tau_core.i18n import register_messages

register_provider("mine", make_model, required_env=[["MINE_API_KEY"]])
register_session_backend("mine", make_store)
register_messages({"mine.hello": {"en": "Hello", "tr": "Merhaba"}})
```

Both registrations replace a seed or an entry point of the same name and invalidate the cached merged view. `Config.component("<name>")` returns a fresh dict of the component's `[component.<name>]` table.
