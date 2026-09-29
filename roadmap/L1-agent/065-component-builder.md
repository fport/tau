# 065 · Component builder: entry-point groups, `[components]` config, `tau components|doctor|init`

Status: in-progress
Type: AFK
Layer: L1 · Agent
Packages: tau-core
Blocked by: none

## What to build

tau's pluggable parts (model providers per role, session backends, context sources, hub services, tools) already have seams (`PROVIDERS`, `SESSION_BACKENDS`, `ContextSource`, `HubService`, `tau.tools` / `tau.commands` entry points) but nothing composes them from config or shows what is installed. Make every part a component that can be plugged in or pulled out with `pip install` and a `tau.toml` line, and give the user three English commands to see, check and set up the installation.

- Entry-point groups mirroring the registries: `tau.providers` (name → `factory(RoleConfig, env) -> Model`, optional `required_env`), `tau.sessions` (name → `factory(Config) -> SessionStore`), `tau.context` (name → `factory(Config) -> ContextSource`), `tau.hub_services` (name → `factory(Config) -> HubService`; this closes 058, the group name is decided here: `tau.channels` stays reserved for hub-hosted channels). The registries stay as the seed. One `tau_core.registry` helper with the skip-and-log discipline of `plugins.py`; name validation in `Config.load` becomes lazy (names only, cached) so `tau version` stays fast.
- `tau.toml` `[components]`: `tools.disabled = []` (tool names or `dist:<name>`), `context = []` (enabled context source names; empty = all discovered), `hub.services = []` (empty = all discovered), and free `[component.<name>]` tables exposed as `Config.component(name) -> dict`. Unknown top-level tables warn once.
- `tau components`: every entry point in every `tau.*` group with distribution, version, enabled/disabled and load error.
- `tau doctor`: config, per-role credentials without building clients, session store, persona files, `.env` names vs `.env.example`, hub control API reachability; exit 1 on a failing check. The Ollama `local` role shows as "not available until 012" instead of raising.
- `tau init`: writes `~/.tau/tau.toml` or `<home>/tau.toml` from a template, copies `persona/user.example.md` to `user.md`, picks the provider by which credentials are present, asks for the UI language; non-interactive with flags for tests.
- Hub (058): `tau hub run` starts discovered `HubService`s after the `ControlApi`, stops them in reverse order, logs and skips load failures, lets each register status sources and control API routes.
- Public API exports the seams: `ContextSource`, `PersonaLoader`, `HubService`, `discover_tools`, `register_provider`, `register_session_backend`, `PROVIDERS`, `SESSION_BACKENDS`.
- ADR 0005 "Components and entry-point groups" records the composition model, the fail-closed rule for plugin tools, and the `HookOrder.SDK_LAST` guarantee.

## Acceptance criteria

- [ ] `tau.providers`, `tau.sessions`, `tau.context` and `tau.hub_services` entry points are discovered through `tau_core.registry`; a broken entry point is logged and skipped; tests use fake entry points (no network)
- [ ] `Config.load` validates component names lazily; `tau version` does not import provider modules
- [ ] `[components]` with `tools.disabled`, `context`, `hub.services` and `[component.<name>]` tables is parsed; `Config.component(name)` returns the table; unknown top-level tables warn once
- [ ] `tau components` lists every entry point in every `tau.*` group with distribution, version, enabled/disabled and load error
- [ ] `tau doctor` checks config, per-role credentials (no client built), session store, persona files, `.env` vs `.env.example` names and hub control API reachability; exit 1 on a failing check; the unresolved `local` role is reported, not raised
- [ ] `tau init` writes the config template, copies `user.example.md` to `user.md`, picks the provider from present credentials, asks for the UI language, and works non-interactively with flags
- [ ] A package with a `tau.hub_services` entry point has its `HubService` started by `tau hub run` after the `ControlApi` and stopped in reverse order; a failing service is skipped; a service can add `/status` keys and control API routes (058)
- [ ] Public API exports `ContextSource`, `PersonaLoader`, `HubService`, `discover_tools`, `register_provider`, `register_session_backend`, `PROVIDERS`, `SESSION_BACKENDS`
- [ ] ADR 0005 written; ADR 0002 points to it for the group names; tau-core README documents `[components]`, the three commands and the `## Hub` service contract; `CONTEXT.md` gains "Component"
- [ ] All output is English; `uv run pytest -q`, `uv run ruff check .` and `uv run ruff format --check .` are green; 058 is closed with a note pointing here

## Blocked by

None - can start immediately; the `tau init` language prompt uses `LANGUAGES` from 062 (same wave).

## Comments

- 2026-09-29: opened by the 2026-09-29 wave on the user's request (English UI, premium TUI, Strands audit, plug-and-play setup). Absorbs 058; spec: wave decisions section 6.
