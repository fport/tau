# 058 · Load hub-hosted services from entry points in `tau hub run`

Status: in-progress
Type: AFK
Layer: L1 · Agent
Packages: tau-core
Blocked by: none

## What to build

`tau hub run` (`tau_core/hub/cli.py:run_command`) wires a fixed set: `Hub(config)` plus `ControlApi` plus a banner service. The Telegram relay connection (#014), voice (#031) and the MCP server (#028) need to start as `HubService`s inside the hub without editing tau-core.

Add discovery of `tau.channels` (or a dedicated `tau.hub_services`) entry points that return `HubService` instances, start them after the `ControlApi`, log and skip load failures the way `plugins.discover_tools` does, and let each register status sources and control API routes. Decide the group name alongside ADR 0002, which reserves `tau.channels` for hub-hosted channels.

## Acceptance criteria

- [ ] A package installed with an entry point in the chosen group has its `HubService` started by `tau hub run` and stopped in reverse order on shutdown
- [ ] A service that fails to load is logged and skipped; the hub still starts
- [ ] A service can add `/status` keys and control API routes
- [ ] ADR 0002 records the group name and contract; the tau-core README `## Hub` section documents it
- [ ] Tests with a fake entry point (no network)

## Blocked by

None - should land before #014 starts.

## Comments

- 2026-09-29: proposed by the agent that closed #009 (it suggested L3 · Cloud; filed under L1 because the code lives in `tau_core.hub` and it unblocks several L3/L4 issues).
- 2026-09-29: absorbed by 065 (component builder), closed when 065 closes. Group name decided: `tau.hub_services` (`tau.channels` stays reserved for hub-hosted channels); recorded in ADR 0005 by 065.
