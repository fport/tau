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

The system prompt is rebuilt before every model call (a Strands `BeforeModelCallEvent` hook), so
an edit to a persona file applies on the next model call without a restart, even inside a tool
loop. Its layout is fixed:

```text
<persona/persona.md>

## Kullanıcı
<persona/user.md, or: Kullanıcı dosyası yok (persona/user.md). Hitap: siz.>

## Şu an
- Tarih ve saat: 29.09.2026 15:30, Salı (Europe/Istanbul)
- Profil: ev
- Rol: hub
- Canlı node'lar: bilinmiyor
- Bugünkü bütçe: bilinmiyor
```

- `persona.md` is tau's character: Jarvis-style, Turkish, polite, dry humor, at most two
  sentences for notifications and voice, no jokes in approval requests, never inventing facts
  about the user. It is tracked, so it holds nothing personal.
- `user.md` holds the facts about the user and how to address them. It is gitignored; start
  from the made-up template with `cp persona/user.example.md persona/user.md`. Without it (or
  when it is empty) tau addresses the user as "siz" and knows nothing about them.
- A file is re-read only when its `(st_mtime_ns, st_size)` changes. HTML comments
  (`<!-- ... -->`) are notes for humans and never reach the model.
- A missing, empty or unreadable `persona.md` makes `build_agent` raise `ConfigError`. If the
  file breaks later (deleted, truncated mid-save, not UTF-8), the last good version stays in
  use until it is fixed; each such problem is logged once.
- Time is always Europe/Istanbul. A value no layer provides yet reads `bilinmiyor` (an empty
  node list reads `yok`), and the persona tells the model never to guess it.

Later layers fill the dynamic block through context sources: zero-argument callables that
return partial overrides (`nodes`, `budget`), merged in order. They run before every model
call, so they must return a cached value quickly. Unknown keys are ignored, `None` means
unknown, and a source that raises is skipped and logged once.

```python
agent = build_agent(
    context_sources=[
        lambda: {"nodes": ["mac", "arm"]},  # live nodes (L5)
        lambda: {"budget": "fast 0,12 $ / 1 $"},  # today's spend (L2)
    ],
)
```

## Tiers and approval

Every tool declares a tier with `@tau_tool(tier=Tier.READ | Tier.DIGITAL_WRITE | Tier.PHYSICAL)`;
untiered tools are refused, tier-2 calls wait for the channel's `Approver`, and every call is
recorded as a `tool_call` agent event.

## Sessions

Conversations are recorded through a `SessionStore` (a Strands `SessionRepository` plus
listing, agent events and metadata); `[sessions].backend` picks the backend (`memory` today).

## Hub

`tau hub` will run tau as a long-lived hub process with a launchd service (issue 009); the
command group exists and prints a placeholder until then.

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
