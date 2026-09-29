# 0005 · Components and entry-point groups

- Status: accepted (issue 065; closes 058)
- Date: 2026-09-29

## Context

tau's pluggable parts already had seams: `PROVIDERS` (models per role), `SESSION_BACKENDS`,
`ContextSource` callables for the `## Now` block, `HubService` for the hub process, and the
`tau.tools` / `tau.commands` entry-point groups (ADR 0002). But only tools and commands could
arrive from another distribution; a new provider, backend, context source or hub service
meant editing tau-core, and nothing showed the user what was installed, what was switched on
or why something did not load. The Telegram relay (014), voice (031) and the MCP server (028)
all need to start inside `tau hub run` without a change here. The repo's rule is that every
package must be publishable and replaceable on its own ("sök çıkar": plug in, pull out).

Strands 1.57 has its own composition ideas: `Agent(plugins=[...])` bundles hooks and tools,
`agent_config` loads an agent from a JSON/YAML description, and HITL/Interventions give
approvals a native shape. They were evaluated for this layer.

## Decision

**A component is any pluggable part that reaches tau through a registry seed, a `tau.*`
entry-point group or an in-process registration**, and `tau.toml` decides which discovered
components are on. `tau_core.registry` is the one loader; it keeps `plugins.py`'s discipline:
an entry point that fails to load, or loads the wrong kind of object, is logged with its
distribution and skipped. It never breaks the CLI.

The groups and their contracts:

| group | entry point value | used by |
|---|---|---|
| `tau.tools` | an `AgentTool` with a tier, a list, or a zero-argument factory (ADR 0002) | `build_agent` |
| `tau.commands` | a `click.Command` (ADR 0002) | the `tau` command |
| `tau.providers` | `factory(RoleConfig, env) -> Model`, optional `required_env` attribute (a list of alternative variable lists) | `resolve_model` for a role naming it |
| `tau.sessions` | `factory(Config) -> SessionStore` | `open_session_store` when `[sessions].backend` names it |
| `tau.context` | `factory(Config) -> ContextSource` | `build_agent` when the caller passes no `context_sources` |
| `tau.hub_services` | `factory(Config) -> HubService` | `tau hub run`, after the control API |

`tau.channels` stays reserved for hub-hosted channels as ADR 0002 says; a channel that needs
to run inside the hub ships a `tau.hub_services` entry point today.

- **The seeds stay.** `tau_core.models.PROVIDERS` and `tau_core.sessions.SESSION_BACKENDS` are
  the built-in components; `register_provider(name, factory, required_env=None)` and
  `register_session_backend(name, factory)` add to the merged view in-process. Precedence: a
  seed name wins over an entry point of the same name (logged and ignored, so an installed
  package cannot silently replace `bedrock`); an in-process registration replaces anything,
  because it is explicit code. Merged lookups are cached and invalidated by the register
  functions.
- **Name validation in `Config.load` is name-only.** It uses the seed names, the entry-point
  *names* and the registrations, never `EntryPoint.load`, so `tau version` and `tau hub status`
  never import a provider's SDK. A name that is declared but cannot be loaded fails when the
  role is resolved, with the entry point's own error (`Model provider 'x' from <distribution>
  failed to load: ...`, the same line `tau components` and `tau doctor` show); only a name no
  distribution declares is an `Unknown model provider`.
- **`[components]` in `tau.toml`** switches discovered components without uninstalling them:
  `tools.disabled` (tool names or `dist:<distribution>`), `context` (enabled `tau.context`
  names; empty = all discovered) and `hub.services` (same for `tau.hub_services`). Free
  `[component.<name>]` tables are a component's own settings, read with
  `Config.component(name)` (a copy). Any other top-level table is logged once and ignored,
  never a failure, so a typo or a table for a plugin that is not installed does not stop tau.
  Inside `[components]`, `[components.tools]` and `[components.hub]` an unknown key is a
  `ConfigError`: a `disable` typo must not leave a tier-2 tool switched on in silence. A name
  that is spelled right but that no installed component provides is a `warn` in `tau doctor`
  (and a warning in the log when the agent or the hub starts).
- **Three English commands** in tau-core, mounted through `tau.commands` like `chat` and
  `hub`: `tau components` (every entry point in every group plus the seeds: group, name,
  distribution, version, enabled/disabled, load error; `--json`), `tau doctor` (config, per-role
  provider and credentials without building a client, session store, persona files, `.env`
  names against `.env.example`, component load errors, `[components]` names nothing provides,
  control API reachability with a 1 s timeout; exit 1 on a failing check; `--json`) and
  `tau init` (a `tau.toml` from the shipped template with the provider picked from the
  credentials present in the environment or `<home>/.env`, bedrock > anthropic > fake; the
  persona files; an `.env.example` listing the variable names, never overwritten; the UI
  language asked or given; `--home`, `--provider`, `--language`, `--profile`, `--yes`,
  `--force`). The shipped `persona.md`, `user.example.md` and `tau.toml` templates are
  byte-identical to the repository's, and the `.env.example` template is the repository's
  file without its L0 remote-access section; a test keeps them so.
- **The public API exports the seams**: `ContextSource`, `PersonaLoader`, `HubService`,
  `discover_tools`, `register_provider`, `register_session_backend`, `PROVIDERS`,
  `SESSION_BACKENDS`, plus `configure_logging` / `reset_logging` (issue 059).

## Safety rules that components cannot change

- **Fail closed for tools.** Only a tool that entered the `ToolCatalog` with a tier can run.
  A tool that a Strands `Plugin`, a `hooks=` component or anything else registers with the SDK
  behind the catalog's back is refused by the tier gate as unknown (`Tool '{tool}' is not
  registered; it was not run.`). A component that wants its tools to run ships them through
  `tau.tools` with a tier. `[components] tools.disabled` can only remove tools; it cannot add
  one, give one a tier or change a tier. There is no default tier for an unknown tool.
- **The gate keeps the last word.** `TierHook` registers at `HookOrder.SDK_LAST`, so the
  `tool_use` it approves is the one Strands runs whatever a component rewrites before it, and
  `build_agent` refuses at build time (`ConfigError`) any component whose `BeforeToolCallEvent`
  callback would run after the gate (ADR 0001, amendment of 2026-09-29). No component list, no
  plugin and no `[components]` entry can replace `TierHook`, the `Approver` or the catalog.
- **Optional services stay optional.** A `tau.hub_services` component that fails to build or
  to start is logged and skipped and the hub runs on; the control API is not optional and a
  failure there still crashes the hub, as before, so launchd/systemd restart it.

## Why not Strands `agent_config`

Strands can build an agent from a declarative `agent_config` (model, tools, prompt) and the
vended `Plugin` class bundles hooks and tools. tau does not adopt them for composition:

- `agent_config` describes a Strands agent, not a tau installation: it has no notion of roles
  (`brain`/`fast`/`local`), tiers, the persona files, session stores or hub services, and it
  would put model ids next to code paths. `tau.toml` already is tau's declarative description,
  read by one `Config`, and it must keep working without Strands (the reflex engine and the
  doctor read it too).
- A `Plugin` registers tools directly with the SDK, bypassing the `ToolCatalog`; under the
  fail-closed rule those tools are refused. `build_agent(plugins=...)` is still accepted for
  hooks and behaviour, but tools come through `tau.tools`.
- Entry points are what `pip install` gives every Python package for free, need no tau-specific
  manifest, and are already the mechanism of ADR 0002.

## Consequences

- Three fixture distributions in `packages/tau-core/tests/fixtures/` (tool, provider + session
  backend, hub service + context source) prove each group end to end in the test suite; they
  are workspace members in the `dev` group and are not published.
- `build_agent(context_sources=None)` now means "the enabled `tau.context` components";
  passing a list, even an empty one, keeps meaning "exactly these".
- `Hub.add_service(service, optional=True)` and `Hub.find_service(name)` are the two small
  additions a discovered service needs: the second lets it reach the `ControlApi`
  (`hub.find_service("control-api")`) to add routes in `start(hub)`. `find_service` only
  returns services whose `start` succeeded (`None` for a skipped optional service, one not yet
  started, or after the hub stopped), so no component wires into a half-initialised one.
  `ControlApi.add_route` is additive only and raises `ValueError` for an existing
  `(method, path)`: `GET /health` and `GET /status`, which `tau hub status`, `tau doctor` and
  TauBar trust, cannot be replaced by a component, nor can one component shadow another's
  route; the offending service fails to start and is skipped.
- The group names are fixed here; ADR 0002 keeps `tau.tools`/`tau.commands` and the
  `tau.channels` reservation.
