# tau-core

The agent core of tau, a personal "smart body" agent platform: `build_agent`, the persona,
permission tiers, model roles, session stores and the `tau` command line.
It is built on [Strands Agents](https://strandsagents.com/) and is published on its own as
`tau-core` (import name `tau_core`).

```sh
pip install tau-core        # or, inside the tau repo: uv sync --all-packages --group dev
tau --help                  # chat, hub, version, plus any plugin commands (tui, ...)
tau chat                    # talk to tau in the terminal (Turkish)
```

```python
import asyncio
from tau_core import build_agent

agent = build_agent("ev")  # config from tau.toml + .env, model from the "brain" role
print(asyncio.run(agent.ask("Merhaba!")))
```

`build_agent` makes no hub assumptions: no network of its own, no launchd, no globals. With
`tau_core.testing.FakeModel` it runs fully offline, which is how the test suite runs.

## Configuration

`tau.toml` (under `TAU_HOME`) maps each model role to a provider and model id; code only ever
asks for a role (`brain`, `fast`, `local`). Credentials and roots come from the environment or
`TAU_HOME/.env` (never overriding variables that are already set): `TAU_HOME` (config root,
default: the current directory if it has a `tau.toml`, else `~/.tau`), `TAU_DATA_DIR` (mutable
state, default `~/.local/share/tau`), `TAU_PROFILE` (default `ev`), `TAU_ROLE` (`hub`|`node`),
`TAU_HUB_PORT`. Providers today: `bedrock`, `anthropic` (with an optional per-role `fallback`)
and `fake`; a missing credential stops `tau chat` with a Turkish message naming the variables.

## Persona

The system prompt is rebuilt before every model call from `persona/persona.md`,
`persona/user.md` (gitignored; `user.example.md` is the template) and a dynamic block with the
time (Europe/Istanbul), profile, host role, live nodes and budget; edits apply on the next turn.

## Tiers and approval

Every tool declares a tier with `@tau_tool(tier=Tier.READ | Tier.DIGITAL_WRITE | Tier.PHYSICAL)`;
untiered tools are refused, tier-2 calls wait for the channel's `Approver`, and every call is
recorded as a `tool_call` agent event.

## Sessions

Conversations are recorded through a `SessionStore` (a Strands `SessionRepository` plus
listing, agent events and metadata); `[sessions].backend` picks the backend (`memory` today).

## Hub

`tau hub run` runs tau as a long-lived process in the hub role. Only one hub runs per machine
(`flock` on `<TAU_DATA_DIR>/hub/hub.lock`; a second start exits 1 with `tau hub zaten çalışıyor
(pid N)…`). While it runs it refreshes `hub/state.json` every `[hub].heartbeat_seconds`; SIGTERM
or SIGINT stops it cleanly and writes `stopped_at`. A start that finds a `state.json` without
`stopped_at` records a crash report (`crash_reports.jsonl`, `last_crash.json`); the reason comes
from `crash.json` when the dying hub could write one, else `unexpected exit (no clean shutdown)`.

```sh
tau hub run            # foreground; Ctrl-C or `tau hub stop` stops it
tau hub status         # running or not, heartbeat, last crash, launchd state (--json for scripts)
tau hub stop           # SIGTERM to the running hub; waits until it is gone
tau hub install        # macOS: launchd user agent, restarted after a crash or kill
tau hub uninstall
tau hub systemd-unit   # prints the systemd user unit (RPi5 hub)
```

The control API listens on `127.0.0.1:<control_port>` only (default 7877, `TAU_HUB_PORT`
overrides) and speaks JSON: `GET /health` → `{"ok": true, "pid", "uptime_s"}`, `GET /status` →
`role`, `profile`, `version`, `started_at`, `heartbeat_at`, `uptime_s`, `last_crash`,
`approvals_pending`, `nodes`. Requests with a non-loopback `Host` header get 403.

Extending the hub: a `HubService` has a `name`, `async start(hub)` and `async stop()`; services
passed to `Hub(config, services=...)` start in order after the crash check and stop in reverse.
`ControlApi.add_route(method, path, handler)` adds routes (handlers run in the server thread; reach
the event loop with `asyncio.run_coroutine_threadsafe(..., hub.loop)`) and
`hub.add_status_source(fn)` adds keys to `/status`. launchd is driven through the `Launchctl`
protocol; tests pass `FakeLaunchctl` to the CLI as `obj={"launchctl": fake}`. The launchd plist
and systemd unit are package templates; `infra/services/` in the tau repo has rendered examples
and the install notes.

## Plugins

Other distributions extend tau through entry points: `tau.tools` (tools, tier required) and
`tau.commands` (click commands mounted under `tau`); `tau.channels` is reserved for L3.

```toml
[project.entry-points."tau.tools"]
mine = "my_package:TOOLS"          # an AgentTool, a list of them, or a zero-argument factory

[project.entry-points."tau.commands"]
mine = "my_package.cli:command"    # a click.Command, available as `tau mine`
```

## Development

```sh
uv sync --all-packages --group dev
uv run pytest -q
uv run ruff check . && uv run ruff format .
uv build --package tau-core
```

License: MIT.
