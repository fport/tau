# 058 · Load hub-hosted services from entry points in `tau hub run`

Status: done
Type: AFK
Layer: L1 · Agent
Packages: tau-core
Blocked by: none

## What to build

`tau hub run` (`tau_core/hub/cli.py:run_command`) wires a fixed set: `Hub(config)` plus `ControlApi` plus a banner service. The Telegram relay connection (#014), voice (#031) and the MCP server (#028) need to start as `HubService`s inside the hub without editing tau-core.

Add discovery of `tau.channels` (or a dedicated `tau.hub_services`) entry points that return `HubService` instances, start them after the `ControlApi`, log and skip load failures the way `plugins.discover_tools` does, and let each register status sources and control API routes. Decide the group name alongside ADR 0002, which reserves `tau.channels` for hub-hosted channels.

## Acceptance criteria

- [x] A package installed with an entry point in the chosen group has its `HubService` started by `tau hub run` and stopped in reverse order on shutdown
- [x] A service that fails to load is logged and skipped; the hub still starts
- [x] A service can add `/status` keys and control API routes
- [x] ADR 0002 records the group name and contract; the tau-core README `## Hub` section documents it
- [x] Tests with a fake entry point (no network)

## Blocked by

None - should land before #014 starts.

## Comments

- 2026-09-29: proposed by the agent that closed #009 (it suggested L3 · Cloud; filed under L1 because the code lives in `tau_core.hub` and it unblocks several L3/L4 issues).
- 2026-09-29: absorbed by 065 (component builder), closed when 065 closes. Group name decided: `tau.hub_services` (`tau.channels` stays reserved for hub-hosted channels); recorded in ADR 0005 by 065.
- 2026-09-29: implemented by 065 (`tau_core.registry.hub_services`, `assemble_hub` in `tau_core.hub.cli`, `Hub.add_service(optional=True)`, `Hub.find_service("control-api")`); the group is `tau.hub_services`, recorded in ADR 0005 and the tau-core README `## Hub`. The "ADR 0002 records the group name" criterion is met by ADR 0005 instead; ADR 0002 keeps the `tau.channels` reservation and should gain a pointer to 0005 (outside the 065 agent's file set). Fixture: `tests/fixtures/tau-example-service`; tests in `test_hub_daemon.py` (in-thread and the real `tau hub run` process).
- 2026-09-29: fix round after review: `Hub.find_service` returns only services whose `start` succeeded (a skipped optional service is `None` to the ones after it) and `ControlApi.add_route` is additive only (`ValueError` on an existing route, so `/health` and `/status` cannot be replaced by a discovered service). Tests in `test_hub_daemon.py` and `test_hub_control.py`.
- 2026-09-29: done (orchestrator): absorbed by 065; group name `tau.hub_services`, contract in ADR 0005, pointer added to ADR 0002, README `## Hub` documents it. Commit b3493f9.
