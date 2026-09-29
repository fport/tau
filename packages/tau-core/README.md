# tau-core

The agent core of tau, a personal "smart body" agent platform: `build_agent`, the persona,
permission tiers, model roles, session stores and the `tau` command line.
It is built on [Strands Agents](https://strandsagents.com/) and is published on its own as
`tau-core` (import name `tau_core`).

```sh
pip install tau-core        # or, inside the tau repo: uv sync --all-packages --group dev
tau --help                  # chat, hub, version, plus any plugin commands (tui, ...)
tau chat                    # talk to tau in the terminal
tau --lang tr chat          # same, with Turkish UI chrome
```

```python
import asyncio
from tau_core import build_agent

agent = build_agent("home")  # config from tau.toml + .env, model from the "brain" role
print(asyncio.run(agent.ask("Merhaba!")))
```

`build_agent` makes no hub assumptions: no network of its own, no launchd, no globals. With
`tau_core.testing.FakeModel` it runs fully offline, which is how the test suite runs.

## Configuration

`tau.toml` (under `TAU_HOME`) maps each model role to a provider and model id; code only ever
asks for a role (`brain`, `fast`, `local`). Credentials and roots come from the environment or
`TAU_HOME/.env` (never overriding variables that are already set): `TAU_HOME` (config root,
default: the current directory if it has a `tau.toml`, else `~/.tau`), `TAU_DATA_DIR` (mutable
state, default `~/.local/share/tau`), `TAU_PROFILE` (`home` | `travel` | `sport`, default
`home`), `TAU_ROLE` (`hub`|`node`), `TAU_HUB_PORT`, `TAU_LANG` (see below). Providers today:
`bedrock`, `anthropic` (with an optional per-role `fallback`) and `fake`; a missing credential
stops `tau chat` with a message naming the variables.

```toml
[models.roles.brain]
provider = "bedrock"
model_id = "..."
max_tokens = 4096
cache = { strategy = "auto", ttl = "1h" }  # optional: Strands CacheConfig (bedrock, anthropic)

[agent]
max_turns = 12            # model calls per user turn (Limits(turns=...))
context = "sliding"       # sliding | summarize: the model's window on a long session
window_size = 60          # sliding: messages kept; summarize: recent messages never summarized
max_total_tokens = 200000 # optional per-turn token budget (Limits(total_tokens=...))
```

`context` picks Strands' `SlidingWindowConversationManager` or `SummarizingConversationManager`;
the session store still keeps every message, only what the model sees is windowed. The SDK's
`context_manager = "auto"`/`"agentic"` presets are rejected with a `ConfigError`: they register
untiered SDK tools that the tier gate would refuse. `cache` accepts the `CacheConfig` fields
(`strategy`, `ttl`, `system_prompt_ttl`, `tools_ttl`); the fake provider ignores it.

## UI language and commands

Everything a person reads in a channel's chrome (commands, notices, the approval prompt, tier
labels, the TUI's titles and key hints) comes from one message table, `tau_core.i18n`, so the
terminal and the TUI never drift. The language is per installation:

```toml
[ui]
language = "en"   # en | tr
```

`TAU_LANG` overrides the file, `tau --lang tr ...` overrides both (it is exported as `TAU_LANG`,
like `--profile`), and `/lang en|tr` switches it for one run. `Config.ui.language` is what a
channel reads. What the *model* reads (system-prompt scaffolding, tool descriptions, the gate's
refusal texts) is fixed English; errors raised before a `Config` exists (`ConfigError`,
`MissingCredentials`, hub messages, `tau hub status`) are plain English too. The persona itself
is Turkish by default and answers in the language the user writes.

Slash commands are shared by `tau chat` and `tau tui` (`tau_core.commands`); the Turkish aliases
are accepted forever but never shown in hints:

| command | aliases | meaning |
|---|---|---|
| `/help` | `/yardım`, `/yardim`, `/?` | list the commands with one-line help |
| `/tools` | `/araçlar`, `/araclar` | registered tools with tier and description |
| `/sessions` | `/oturumlar` | the 10 most recent earlier sessions, numbered |
| `/resume [n\|id]` | `/devam` | resume the most recent earlier session, the n-th of the last listing, or an id |
| `/new` | `/yeni` | start a fresh session |
| `/session` | `/oturum` | current session id, title, message count, store |
| `/lang en\|tr` | `/dil` | switch the UI language for this run |
| `/quit` | `/çık`, `/cik`, `/exit` | leave |

Matching is `str.casefold()` on the typed name (`/ARAÇLAR` works). In code:

```python
from tau_core import LANGUAGES, SLASH_COMMANDS, command_hint, resolve_command, t

resolve_command("/Devam 2")  # ("resume", "2"); None for "/x" or plain text
command_hint()  # "/help, /tools, /sessions, /resume, /new, ..."
t("session.not_found", "tr", session="x")  # "Oturum bulunamadı: x."
```

`t(key, language, **kwargs)` formats with `str.format`, raises `KeyError` for an unknown key and
falls back to English for a language that lacks the key. Plugins add their own keys with
`tau_core.i18n.register_messages({"mine.hello": {"en": "...", "tr": "..."}})`.

## Persona

The system prompt is rebuilt before every model call (a Strands `BeforeModelCallEvent` hook), so
an edit to a persona file applies on the next model call without a restart, even inside a tool
loop. Its layout is fixed:

```text
<persona/persona.md>

## User
<persona/user.md, or: No user file (persona/user.md). Address the user formally.>

## Now
- Date and time: 29.09.2026 15:30, Tuesday (Europe/Istanbul)
- Profile: home
- Host role: hub
- Live nodes: unknown
- Budget today: unknown
```

The scaffolding (headings, labels, `unknown`) is English because the model reads it; the
persona decides the reply language. The model receives the prompt as three content blocks
(`PersonaLoader.build_system_content`): the persona plus `## User` (stable), a `cachePoint`,
then `## Now` (changes every minute), so a provider that caches system prompts reuses the
stable part; `build_system_prompt` returns the same text as one string for tests and logging.

- `persona.md` is tau's character: Jarvis-style, Turkish by default and mirroring the language
  the user writes in, polite, dry humor, at most two sentences for notifications and voice, no
  jokes in approval requests, never inventing facts about the user. It is tracked, so it holds
  nothing personal.
- `user.md` holds the facts about the user and how to address them. It is gitignored; start
  from the made-up template with `cp persona/user.example.md persona/user.md`. Without it (or
  when it is empty) tau addresses the user formally ("siz") and knows nothing about them.
- A file is re-read only when its `(st_mtime_ns, st_size)` changes. HTML comments
  (`<!-- ... -->`) are notes for humans and never reach the model.
- A missing, empty or unreadable `persona.md` makes `build_agent` raise `ConfigError`. If the
  file breaks later (deleted, truncated mid-save, not UTF-8), the last good version stays in
  use until it is fixed; each such problem is logged once.
- Time is always Europe/Istanbul. A value no layer provides yet reads `unknown` (an empty
  node list reads `none`), and the persona tells the model never to guess it.

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

Every tool declares a tier; a tool without one cannot be registered.

| Tier | Meaning | What happens |
|---|---|---|
| 0 `Tier.READ` | reads, no side effects | runs freely |
| 1 `Tier.DIGITAL_WRITE` | changes digital state (files, notes, messages) | runs and is logged |
| 2 `Tier.PHYSICAL` | acts on the physical world, or activates self-written code | waits for an approval |

```python
from tau_core import Tier, tau_tool


@tau_tool(tier=Tier.PHYSICAL, effect="Switches the desk lamp on or off.")
def desk_lamp(state: str) -> str:
    """Switches the desk lamp on or off.

    Args:
        state: "on" or "off".
    """
```

`effect` is the sentence approval prompts show (default: the tool description); write
descriptions and effects in English, the model reads them. A plain
Strands `@tool` has no tier: `ToolCatalog.add` raises `UntieredToolError`, `build_agent` refuses
it when passed in `tools=` and skips it with a warning when a plugin ships it. `tau_tool`
records the tier and effect in the tool spec (`tool_spec["annotations"]["tau"] = {"tier",
"effect"}`), so a `@tau_tool` method on a class keeps its tier when accessed through an
instance (Strands builds a new tool object for bound methods); `tier_of`/`effect_of` read the
annotation first and the older `tau_tier`/`tau_effect` attributes second.

Every call passes `TierGate` (`build_agent` wires it in through `TierHook`, registered at
`HookOrder.SDK_LAST` so the `tool_use` the gate sees is the one Strands runs, whatever other
hooks, interventions or plugins rewrite before it):

- **Unknown tool** (not in the catalog, looked up live): refused with
  `Tool '{tool}' is not registered; it was not run.` and an `error` agent event.
- **Tier 0 and 1**: allowed.
- **Tier 2**: allowed when an exemption matches, otherwise the channel's `Approver` decides.
  Anything but `Decision.APPROVED` (a rejection, a timeout, an approver that raises or answers
  something invalid) refuses the call, and the model reads
  `The user did not approve this action: {tool}. Do not perform it; tell the user briefly.` as
  the tool result. Prompts are asked one at a time.
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
- `TerminalApprover` (`tau chat`) prints the tool, its arguments as JSON and the effect in the
  UI language (`format_approval_prompt(request, language)`), and approves only on `y`, `yes`,
  `e` or `evet` whatever the language; anything else, Ctrl-D included, rejects. It has no
  timeout: a blocked `input()` cannot be cancelled.
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

**Extra components.** `build_agent(hooks=[...], plugins=[...])` passes Strands `HookProvider`s
and `Plugin`s through to the `Agent`. The gate keeps the last word: `TierHook` runs at
`HookOrder.SDK_LAST`, no `BeforeToolCallEvent` callback may run after it (`build_agent`
checks the registry and raises `ConfigError` for a hook registered above `SDK_LAST`, since the
SDK accepts any order), and a tool a plugin registers behind the catalog's back is refused as
unknown (fail closed); a component that wants its tools to run ships them through `tau.tools`
with a tier. A hook added to the SDK agent *after* build cannot be refused; the gate then
records a refused call that ran, or an approved call whose arguments changed, as `error`
with an `error` event (`where: tier_gate`). When any registered tool is tier 2, `build_agent` uses the SDK's
`SequentialToolExecutor`, so two approved physical calls in one model turn never run at the
same time. Every span carries `trace_attributes` `tau.session_id`, `tau.channel`,
`tau.profile`.

## Turns and stop reasons

`TauAgent.stream(prompt)` runs one user turn and yields `TurnEvent`s; `ask(prompt)` returns
only the text. Calls are serialized with an `asyncio.Lock` (created per event loop), so two
channels on one agent queue up instead of overlapping.

| event | meaning |
|---|---|
| `TextDelta(text)` | a piece of the reply |
| `ReasoningDelta(text)` | a piece of the model's extended thinking (SDK `reasoningText`) |
| `ToolUseStarted(tool_use_id, tool, tier)` | the model asked for a tool (`tier` is `None` for an unknown tool) |
| `ToolProgress(tool_use_id, tool, text)` | progress from a streaming tool (SDK `tool_stream_event`) |
| `ToolFinished(tool_use_id, tool, status, summary, approval)` | from the `tool_call` event the gate recorded |
| `Throttled(delay_seconds)` | the provider throttled the call; the SDK retries after the delay |
| `Notice(text)` | something the user should read, in the UI language |
| `TurnEnd(stop_reason)` | always the last event |

`to_turn_event(event)` is the pure mapping from the SDK's dict events (`data`,
`current_tool_use`, `reasoningText`, `tool_stream_event`, `event_loop_throttled_delay`,
`force_stop`); the terminal prints `Throttled` as a dim line and ignores reasoning and progress
for now. `TurnEnd.stop_reason` (`tau_core.STOP_REASONS`):

| stop reason | what happened | notice / event |
|---|---|---|
| `end_turn` | the model finished | – |
| `limit_turns` | `[agent] max_turns` model calls were used; the last call's tools still ran | `notice.turn_limit`, `turn_limit` event |
| `limit_total_tokens` | `[agent] max_total_tokens` was reached | `notice.total_tokens`, `turn_limit` event |
| `max_tokens` | the reply hit the provider's output limit; the partial reply is kept | `notice.max_tokens`, `notice` event |
| `cancelled` | `TauAgent.cancel()` stopped the turn at the SDK's next safe point; a cancel while no turn runs is ignored | `notice.cancelled`, `notice` event |
| `interrupt` | a hook kept interrupting after `max_turns` refusals; tau cleared the SDK's interrupt state | `notice.interrupt_refused`, `error` event |
| `error` | the model call failed (`notice.model_error`), the context window overflowed (`notice.overflow`) | `error` event with `where`: `model`, `context` or `interrupt` |
| `busy` | another invocation held the SDK's concurrency guard; nothing ran | `notice.busy`, no event |

tau never appends to the history by hand. When a turn leaves the history *dangling* - on a
`user` message (a failed model call, the loop guard or token budget after a tool result, a
cancel around tool execution, a session restored after a crash) or on an `assistant` message
with a `toolUse` and no result (the hub died while an approval was pending, or an interrupt
was given up) - the **next** `stream()` sends a two-message prompt to the SDK: an `assistant`
message with the last notice in parentheses (or "The previous turn did not finish." for a
crash-restored session), then the new `user` message. Both go through the SDK's own append
path, so they get tracking ids and reach the session store like every other message; for a
dangling `toolUse` the SDK first inserts its own "Tool was interrupted." result, so roles keep
alternating. The pending notice survives a `busy` turn (nothing was appended) and a window
trim (the check is by identity of the last message, not by length). A cancel during model
streaming needs no repair: the SDK stores its own "Cancelled by user" placeholder as the
reply. A hook that raises a Strands interrupt (`event.interrupt(...)`) gets
`{"tau": "rejected"}` as the answer inside the same turn, once per interrupt up to
`max_turns` refusals, with the turn's remaining `Limits` budget; the user sees
`notice.interrupt_refused`. If that does not clear it, or a session comes back from the store
in interrupt state, tau leaves the SDK's interrupt state itself and repairs on the next turn,
so the agent is never left stuck (interrupt-based approvals are issue 068).

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
session.json                         Strands session record; updated_at orders /sessions
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

- `/sessions` lists the last 10 earlier sessions that have messages
  (`n. id  date  channel  title (N messages)`).
- `/resume` resumes the most recent earlier session and says which one; `/resume <n>` resumes
  the n-th of the last `/sessions` listing (without a listing, of the one `/sessions` would
  print now); `/resume <id>` resumes that session. `tau chat --resume [ID]` does the same at
  start-up.
- `/new` starts a fresh session; `/session` shows the current id, title, message count and
  backend.

Resuming rebuilds the agent on the stored session (`build_agent(session_id=...,
session_store=...)`), so Strands restores `agent.messages`; the model sees the last
`[agent] window_size` messages (or a summary plus the recent ones), the store keeps them all.
A new backend implements the nine `SessionRepository` methods plus the five extras and
registers a factory in `tau_core.sessions.SESSION_BACKENDS`.

## Hub

`tau hub run` runs tau as a long-lived process in the hub role. Only one hub runs per machine
(`flock` on `<TAU_DATA_DIR>/hub/hub.lock`; a second start exits 1 with `tau hub is already
running (pid N)…`). While it runs it refreshes `hub/state.json` every `[hub].heartbeat_seconds`; SIGTERM
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
