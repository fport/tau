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

Every tool declares a tier; a tool without one cannot be registered.

| Tier | Meaning | What happens |
|---|---|---|
| 0 `Tier.READ` | reads, no side effects | runs freely |
| 1 `Tier.DIGITAL_WRITE` | changes digital state (files, notes, messages) | runs and is logged |
| 2 `Tier.PHYSICAL` | acts on the physical world, or activates self-written code | waits for an approval |

```python
from tau_core import Tier, tau_tool


@tau_tool(tier=Tier.PHYSICAL, effect="Masa lambasını açar veya kapatır.")
def desk_lamp(state: str) -> str:
    """Masa lambasını açar veya kapatır.

    Args:
        state: "on" ya da "off".
    """
```

`effect` is the Turkish sentence approval prompts show (default: the tool description). A plain
Strands `@tool` has no tier: `ToolCatalog.add` raises `UntieredToolError`, `build_agent` refuses
it when passed in `tools=` and skips it with a warning when a plugin ships it.

Every call passes `TierGate` (`build_agent` wires it in through `TierHook`):

- **Unknown tool** (not in the catalog, looked up live): refused with
  `'{tool}' aracı kayıtlı değil; çalıştırılmadı.` and an `error` agent event.
- **Tier 0 and 1**: allowed.
- **Tier 2**: allowed when an exemption matches, otherwise the channel's `Approver` decides.
  Anything but `Decision.APPROVED` (a rejection, a timeout, an approver that raises or answers
  something invalid) refuses the call, and the model reads
  `Kullanıcı bu eylemi onaylamadı: {tool}. Eylemi yapma, kullanıcıya kısaca bildir.` as the
  tool result. Prompts are asked one at a time.
- **Every call of every tier** emits a `tool_call` agent event (`tool`, `tier`, `arguments`,
  `status`, `result_summary`, `approval`, `duration_ms`, `tool_use_id`); every tier-2 question
  emits an `approval` event. The log gets tier 0 at `DEBUG`, tiers 1 and 2 at `INFO` (with
  arguments, result summary and approval; `tau chat` writes `INFO` and up to
  `<data_dir>/logs/tau.log`), unknown tools at `WARNING`.

A channel (TUI, Telegram, TauBar) implements `Approver` and passes it to `build_agent`:

```python
from tau_core import ApprovalRequest, Decision, build_agent


class ButtonApprover:
    name = "telegram"
    timeout_seconds = 600  # optional: stop waiting after 10 minutes and record TIMEOUT

    async def decide(self, request: ApprovalRequest) -> Decision:
        # show request.tool, request.arguments and request.effect; await the user's button
        ...


agent = build_agent(approver=ButtonApprover(), channel="telegram")
```

- Without an approver, `AutoRejectApprover` rejects every tier-2 call. No approver approves on
  its own; tests script decisions with `tau_core.testing.ScriptedApprover([Decision.APPROVED])`
  and use `UnansweredApprover` for timeouts.
- `TerminalApprover` (`tau chat`) prints the tool, its arguments as JSON and the effect, and
  approves only on `e` or `evet`; anything else, Ctrl-D included, rejects. It has no timeout:
  a blocked `input()` cannot be cancelled.
- **Timeouts:** `TierGate(timeout_seconds=...)`, else the approver's own `timeout_seconds`, else
  none. When it runs out the question is cancelled and the decision is `timeout`; silence never
  approves.
- **Exemptions** let registered routines (#037) skip per-call approval:
  `build_agent(exemptions=[fn])` or `agent.gate.add_exemption(fn)` (returns an undo function).
  `fn(tool_name, arguments)` sees a copy of the arguments and must return `True`; it is asked
  only for tier-2 calls to known tools, one that raises does not exempt, and the call is still
  recorded with `approval: "exempt"`.

`TierGate.check()` and `record()` do not need Strands, so the reflex engine and the MCP server
can use the same policy.

**Loop guard.** `[agent] max_turns` in `tau.toml` (default 12) caps the model calls of one user
turn (Strands `Limits(turns=...)`); the tools the last allowed call asked for still run. When it
trips, the turn ends with
`Bu turda araç çağrısı sınırına ulaştım ({n} tur). Durdum; devam etmemi isterseniz söyleyin.`,
a `turn_limit` event and `TurnEnd(stop_reason="limit_turns")`. The next user turn starts with a
fresh budget.

## Sessions

Every conversation is a session: its messages, its agent events (tool calls, approval
decisions, turn limits, errors) and its metadata (channel, profile, title = the first user
message, cut to 60 characters). Callers only use `SessionStore`, a Strands
`SessionRepository` plus `list_sessions`, `append_event`/`read_events`, `write_meta`/`read_meta`
and `event_sink`. `[sessions].backend` in `tau.toml` picks the backend and
`open_session_store(config)` builds it:

| Backend  | Where                                  | Notes                                   |
|----------|----------------------------------------|-----------------------------------------|
| `memory` | the process                            | tests and throwaway runs                |
| `file`   | `TAU_DATA_DIR/sessions/<session id>/`  | the default in the repo's `tau.toml`    |
| `cloud`  | D1 through the tau-cloud Worker API    | issue 018; the hub holds no D1 secrets  |

The `file` layout, one directory per session (ids look like `20260929-153012-3f9a`, UTC):

```
session.json                         Strands session record; updated_at orders /devam
meta.json                            channel, profile, title
events.jsonl                         one agent event per line, append-only
agents/tau/agent.json                Strands agent state
agents/tau/messages/000000.json      one file per message, in order
```

JSON files are replaced atomically (temp file, fsync, rename), directories are `0700` and
files `0600`, symlinks and ids that are not plain names are refused. **Nothing is ever
deleted**: the store has no delete method and never overwrites a message; retention is "keep
everything".

In `tau chat`:

- `/devam` lists the last 10 earlier sessions that have messages
  (`n. id  date  channel  title (N mesaj)`) and resumes the most recent one.
- `/devam <n|id>` resumes that one; `tau chat --resume [ID]` does the same at start-up.
- `/yeni` starts a fresh session; `/oturum` shows the current id, title, message count and
  backend.

Resuming rebuilds the agent on the stored session (`build_agent(session_id=...,
session_store=...)`), so Strands restores `agent.messages` and the model sees the whole
conversation again. A new backend implements the nine `SessionRepository` methods plus the
five extras and registers a factory in `tau_core.sessions.SESSION_BACKENDS`.

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
