# tau-core

The agent core of tau, a personal "smart body" agent platform: `build_agent`, the persona,
permission tiers, model roles, session stores and the `tau` command line.
It is built on [Strands Agents](https://strandsagents.com/) and is published on its own as
`tau-core` (import name `tau_core`).

```sh
pip install tau-core        # or, inside the tau repo: uv sync --all-packages --group dev
tau --help                  # chat, hub, components, doctor, init, version, plus plugin commands (tui, ...)
tau init                    # create ~/.tau/tau.toml and the persona files from the templates
tau doctor                  # check config, credentials, sessions, persona, .env, the hub
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
`home`), `TAU_ROLE` (`hub`|`node`), `TAU_HUB_PORT`, `TAU_LANG` (see below). Built-in providers:
`bedrock`, `anthropic` (with an optional per-role `fallback`) and `fake`; a `tau.providers`
component adds more (see [Components](#components)). A missing credential stops `tau chat` with
a message naming the variables; `tau doctor` reports it without starting anything, and `tau tui`
opens its settings screen so the key can be added in place.

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

### Editing the two files: `tau_core.settings`

Both channels edit the bootstrap config in place: `/settings` in `tau chat` (a report plus
`language`, `profile`, `model`, `set NAME` and `clear NAME` setters; the value of `set` is read
with `getpass` and never echoed) and the settings screen of the TUI. The shared editor is
`tau_core.settings`, small and testable:

```python
from tau_core.settings import (
    load_document,
    set_role,
    set_ui_language,
    set_agent_option,
    save_document,
    validate,
    set_credential,
    clear_credential,
    credential_status,
    known_env_names,
    mask,
    describe_home,
)

doc = load_document(home)  # tomlkit: comments and layout survive
set_role(doc, "brain", "anthropic", "claude-…", max_tokens=4096, fallback=None)  # None removes,
set_agent_option(doc, "max_total_tokens", None)  # KEEP (the default) leaves a key as it is
set_ui_language(doc, "tr")
save_document(home, doc)  # check_document() first, then temp file + rename
set_credential(home, "ANTHROPIC_API_KEY", value, export=True)  # .env at mode 0600; os.environ too
credential_status(home, config.roles["brain"])  # ok | none | missing | fallback | unavailable
validate(home)  # Config.load on the saved files
```

`save_document` refuses a document `Config` would not load (nothing is written), keeps the
file's mode, and `.env` is created private and kept private. No function returns, logs or
prints a credential value; the UI shows `mask(value)` (`sk-…abcd` from 20 characters on,
`ab…yz` for 12 to 19, only `…` and the last two below that) or a `set` / `not set` flag, and
`credential_source` says whether the shell environment or `.env` supplies a value (the shell
always wins). `set_role` and `check_document` refuse a planned provider a save would newly
introduce (`ollama` until issue 012), since a role on it cannot start; one that is already in
the file is left alone. `known_env_names(home)` lists what a credentials editor
should offer: the variables of the configured providers, then every other provider's, then the
names in `.env.example` and `.env`. `report_lines(config, language=…)` is the `/settings`
listing both channels print. `Config.load` raises `ConfigNotFound` (a `ConfigError`) when there
is no `tau.toml`, which is what the TUI's setup screen keys on.

`context` picks Strands' `SlidingWindowConversationManager` or `SummarizingConversationManager`;
the session store still keeps every message, only what the model sees is windowed. A session
remembers the manager it was recorded with (Strands refuses to restore it under the other one),
so after changing `context` an earlier session fails to open with `Session <id> was recorded
with a different [agent] context setting; set it back to sliding or start a new session`
(`SessionContextMismatch`, a `ConfigError`) in `tau chat --session`/`--resume`, `tau tui
--resume`, `/resume` and the TUI's picker and sidebar alike; the current session is kept. The SDK's
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
| `/compact [focus]` | `/özet`, `/ozet` | summarize this session into a new one and continue there; the old one is kept (see [Compaction](#compaction)) |
| `/clear` | `/temizle`, `/cls` | clear the screen; the session continues, nothing is deleted (`--resume` shows the history again) |
| `/status` | `/durum` | profile, session, model, context, tools, UI language, versions, hub |
| `/model [role]` | `/rol` | list the model roles, or switch this session to one (remembered by `/resume`) |
| `/lang en\|tr` | `/dil` | switch the UI language for this run |
| `/settings [key value]` | `/ayarlar`, `/ayar` | show the bootstrap config (roles, credential status, language, profile, context, files); `language en\|tr`, `profile NAME`, `model ROLE PROVIDER MODEL_ID`, `set NAME` (hidden prompt), `clear NAME` change one and reload; the TUI opens its settings screen |
| `/quit` | `/çık`, `/cik`, `/exit` | leave (`/exit` is an alias, `/quit` is the name the hints show) |

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
- Budget: unknown
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
unknown, and a source that raises is skipped and logged once. Without an explicit
`context_sources` list, `build_agent` uses the enabled `tau.context` components (see
[Components](#components)); an explicit list, even an empty one, replaces them.

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
- **Owner guard** (see [Guard](#guard)): with a guard, a tier-1 or tier-2 call is refused
  without asking when the guard does not admit the turn (approval `locked`, note "tau was
  locked before the user answered."), and an approved tier-2 call also needs the guard's
  step-up (anything but a literal `True` turns it into `rejected`, note "The guard could not
  confirm the user's identity."; the `approval` event gains `step_up: passed | failed`). The
  guard can only refuse; exempt calls reach neither check. Every `TierGate(...)` in the repo
  passes `guard=` explicitly (a repo rule).
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
| `locked` | the owner guard refused the turn before any history, prompt or model work; nothing was appended (see [Guard](#guard)) | `guard.refused.<reason>`, `guard` event |

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
  backend; `/clear` erases the screen (an ANSI clear, then the ready banner again) and nothing
  else: the session and the agent go on, and `--resume` shows the history again.
- `/status` prints the profile, the session (id, title, stored message count, role), the model
  (role → provider, whether the role's `fallback` is in use, the model id; never a key), the
  context mode and window with the in-memory message count, the tools (registered, how many
  need approval), the UI language, the installed `tau-*` versions and whether a hub answers on
  `http://127.0.0.1:<control_port>/health` (the `tau doctor` probe, one second, information
  only).
- `/model` lists the roles of `tau.toml` with their providers and marks the current one;
  `/model fast` rebuilds the agent on the **same** session with that role: the new agent is
  built first (`build_agent(role=..., session_id=<current>)`, which restores the stored history
  and takes over a pending repair notice), and only then is the previous one closed, so a
  failed build changes nothing. Every session records the `role` it last ran on in its
  metadata (`build_agent` writes it next to `channel` and `profile`), so `/resume` and
  `tau chat --resume` come back on that role, also for sessions opened by `/new` and
  `/compact`. `tau chat --role ROLE` pins the role for the run and wins over the stored one
  (and is recorded in turn); an unknown role, missing credentials or an unavailable provider
  leave the current agent unchanged and print why. `TauAgent.role` is the role an agent was
  built for.

Resuming rebuilds the agent on the stored session (`build_agent(session_id=...,
session_store=...)`), so Strands restores `agent.messages`; the model sees the last
`[agent] window_size` messages (or a summary plus the recent ones), the store keeps them all.
A new backend implements the nine `SessionRepository` methods plus the five extras and arrives
as a `tau.sessions` entry point or through `register_session_backend(name, factory)` (see
[Components](#components)); `SESSION_BACKENDS` is the built-in seed.

### Compaction

`/compact [focus]` is how a long conversation goes on without its whole history, while every
session stays on record:

1. `tau_core.compaction.summarize(agent, focus=...)` runs a throwaway Strands `Agent` on the
   agent's **own model** over a deep copy of `agent.messages` (no tools, no hooks, no session
   manager, so the tier gate is not involved and the live agent is untouched), with an English
   system prompt that asks for a continuation summary: facts about the user, decisions, open
   tasks, tool results that still matter, and the language the user writes in; `focus` is
   appended as `Focus on: ...`. An empty history, a failed model call or an empty reply raise
   `CompactionError` and nothing changes.
2. `seed_messages(summary, previous_session_id)` is the two-message history the new session
   starts with: a user message `Summary of the previous conversation (session <id>):` plus the
   summary, and the assistant's `Understood. I will continue from this summary.`.
3. `build_agent(seed_messages=..., session_id=None)` opens the new session with that history.
   The seed goes in as the Strands `Agent(messages=...)`; the SDK's `RepositorySessionManager`
   writes every initial message to the store when it creates the agent record, so the seed is
   part of the session and survives `--resume` (a test proves the file-store round trip).
4. The new session's metadata gets `title` (the old title, or its first user line) and
   `compacted_from = <old id>`; the old session gets `compacted_to = <new id>` and keeps every
   message. `/sessions` lists both.

The channel then prints `Compacted N messages into a summary. New session <id>; the previous
session <old id> is kept.` and the summary itself. `N` is what was summarized: the messages in
memory, which the conversation window may have trimmed below the stored count.

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
`approvals_pending`, `nodes`, plus the keys hub services add (`telegram`). Requests with a
non-loopback `Host` header get 403.

Every other route is **protected** (ADR 0008): `add_route(method, path, handler, open=False)`,
and only `/health` and `/status` are open. At start, while it holds the hub lock, the hub writes
a random token to `<TAU_DATA_DIR>/hub/control.token` (0600, `hub/` chmod 0700) and deletes it
on a clean stop if it is still its own. The token never travels: a protected request carries
`X-Tau-Nonce` and `X-Tau-Auth = hex(HMAC-SHA256(token, "req"|nonce|method|path))`, and the
answer carries `X-Tau-Proof = hex(HMAC-SHA256(token, "resp"|nonce|method|path|status|body))`
(`tau_core.hub.control.auth_headers`, `request_auth`, `response_proof`). The server answers 403
before dispatch when the token file is missing, empty or not the hub's, when the nonce or
`X-Tau-Auth` is missing or wrong, when any `Origin` header is present, or when a POST is not
`application/json`. A process that binds the port after a hard hub exit (a stale token file)
sees nothing it can sign with, so clients refuse its answers. `GET /spend` is protected too.
Other processes call protected routes with `tau_core.hub.HubClient(config)`: loopback only, no
proxy, no redirects, the token re-read on every request and once more after a 403, every
request signed and every proof checked; it raises `HubUnavailable` (`reason`: `no_hub`,
`timeout`, `bad_proof`, `bad_response`) or `HubError(status, payload)`.

Extending the hub: a `HubService` has a `name`, `async start(hub)` and `async stop()`; services
start in order after the crash check and stop in reverse. `tau hub run` starts the control API
first and then every enabled `tau.hub_services` component (see [Components](#components)): the
entry point is a `factory(config) -> HubService`, the service is *optional* (one that fails to
build or to start is logged and skipped, the hub runs on), and inside `start(hub)` it can call
`hub.add_status_source(fn)` to add keys to `/status` and
`hub.find_service("control-api").add_route(method, path, handler)` to add protected routes
(handlers run in the server thread; reach the event loop with
`asyncio.run_coroutine_threadsafe(..., hub.loop)`).
Routes are additive only: `add_route` raises `ValueError` for a `(method, path)` that exists, so
no service can replace `GET /health`, `GET /status` or another service's route (the service
then fails to start and is skipped). `find_service` returns only services that have *started*:
`None` for one that failed to start, has not started yet or after the hub stopped, so a service
never wires into a half-initialised component. A service's own settings live in
`[component.<name>]` and are read with `config.component(name)`.

```python
class VoiceService:  # in another distribution
    name = "voice"

    def __init__(self, config):
        self.settings = config.component("voice")

    async def start(self, hub):
        hub.add_status_source(lambda: {"voice": {"listening": True}})
        api = hub.find_service("control-api")
        api.add_route("POST", "/voice/say", self.say)

    async def stop(self): ...


def make_service(config):  # [project.entry-points."tau.hub_services"] voice = "pkg:make_service"
    return VoiceService(config)
```

tau-core itself ships one hub service, `telegram` (see [Telegram](#telegram)).

launchd is driven through the `Launchctl`
protocol; tests pass `FakeLaunchctl` to the CLI as `obj={"launchctl": fake}`. The launchd plist
and systemd unit are package templates; `infra/services/` in the tau repo has rendered examples
and the install notes.

## Telegram

`tau_core.channels.telegram` is the Telegram channel, a `tau.hub_services` component
(`telegram = "tau_core.channels.telegram:make_service"`) that runs inside `tau hub run`. The hub
polls the Bot API itself with a `getUpdates` long poll: outbound HTTPS only, no webhook, no relay,
no inbound port (ADR 0006). Each text message from an allowed chat is one turn of that chat's
session, built with `build_agent(channel="telegram")`, and the reply goes back with
`sendMessage`. Messages and button presses from any other chat are dropped and logged, never
answered.

It reads two names from `.env` (or the environment):

| variable | meaning |
|---|---|
| `TELEGRAM_BOT_TOKEN` | the bot token from @BotFather (`/newbot`) |
| `TELEGRAM_ALLOWED_CHAT_IDS` | the chat ids the bot answers, comma-separated (yours: send the bot a message, then read `message.chat.id` from `getUpdates`) |

and its own table in `tau.toml`:

```toml
[component.telegram]
poll_timeout_seconds = 50    # server-side long-poll timeout
backoff_max_seconds = 60     # cap of the exponential backoff after network errors
approval_timeout_seconds = 300   # an unanswered tier-2 approval counts as not approved
```

Without a token, or without an allowed chat, the service starts idle, logs one line and reports
`"telegram": {"configured": false, "reason": ...}` in `/status`; it never fails the hub. When it
runs, `/status` shows `state` (`starting`, `polling`, `retrying`, `failed`, `stopped`), `bot`,
`allowed_chats`, `last_poll_at`, `last_error`, `retry_in_s`, `handled` and `dropped`, never the
token or a chat id; `tau doctor` prints the same as its `telegram` line. On start it calls
`deleteWebhook` (Telegram refuses `getUpdates` while a webhook is set). Network errors back off
exponentially (1 s, 2 s, 4 s, … up to `backoff_max_seconds`) and the hub stays up; a token the
Bot API rejects (401) stops the poller until the next hub start.

Each allowed chat has a worker that handles its messages in order, so the poller keeps polling
while a turn runs (and while it waits for an approval); messages that arrive meanwhile queue up.
State lives under `TAU_DATA_DIR/telegram/`: `offset` is the next `update_id` to ask for, written
once an update is routed; `inflight.json` holds the messages a worker has not finished, and a
start runs them again, so a restart neither re-processes nor skips a message (one whose turn a
stop interrupted runs again); `chats.json` maps each chat to its current session, so a chat
keeps its conversation across restarts.

The slash commands `/help`, `/tools`, `/sessions`, `/resume`, `/new`, `/session`, `/status`,
`/model`, `/compact` and `/lang` resolve through `tau_core.commands` with the terminal's wording
(Turkish aliases accepted, never shown; `/start` and a bare `/` show the help). On start they
are set as the bot's command menu (`setMyCommands`) for each allowed chat only, in the UI
language; `/lang` sets it again. `/clear`, `/quit` and any command that edits the configuration
answer that they are not available on Telegram; credentials are never set from a chat. Replies
are sent as HTML converted from the model's Markdown and fall back to plain text when Telegram
rejects the markup; longer than 4096 characters they are split. "typing…" shows while a turn
runs.

Tier 2 (issue 017): `TelegramApprover` sends the tool, its arguments and its effect to the chat
the call came from, with **Approve** / **Reject** inline buttons labelled in the UI language.
The press comes back as a `callback_query` through the same poll loop; nothing sits between
Telegram and the hub, so it is a first-party approval (ADR 0006). It counts only when the user
who pressed is in `TELEGRAM_ALLOWED_CHAT_IDS` (in a private chat that is the chat id) and the
request id, chat and message match a pending request; any other press is answered with
`answerCallbackQuery`, logged and has no effect. No answer within `approval_timeout_seconds` is a
timeout. The message is then edited to show the outcome and loses its buttons (also when the
hub stops while it waits). Every decision is an `approval` agent event in the session, like a
terminal approval, and `/status` shows `approvals_pending`. A pending approval does not survive
a hub restart (068 moves it onto Strands interrupts): its message runs again after the restart
and asks again. Nothing is ever auto-approved.

Tests use `tau_core.testing.FakeBotApi`, an offline Bot API: `push_message(chat_id, text)`
queues an update, `sent` / `texts()` show what the bot sent, `buttons(chat_id)` and
`press(chat_id, index)` work the inline buttons, `edits` and `answers` record message edits and
callback answers, `fail(method, *errors)` scripts network losses and refusals.

## Guard

The owner guard (ADR 0008) decides who may use tau's guarded surfaces right now. tau-core
ships the seam and imports no camera library; the camera, the state machine and the `/guard/*`
routes come from the `tau-guard` hub service, and the lock screens from the channels. An install without a guard is unchanged: `resolve_guard(config)`
returns `None`.

- **Active** when `<TAU_DATA_DIR>/guard/enrolled` exists (JSON `{"v", "enrollment", "model",
  "created"}`, written by tau-guard) or `[component.guard] enabled = true`. While the marker
  exists, `enabled = false` is ignored. A non-bool `enabled`, an unknown key in
  `[component.guard]` or any platform but macOS gives a `LockedGuard` that refuses everything;
  otherwise `resolve_guard` returns a `HubGuard`. A found guard is memoized per `(home,
  data_dir)`; `None` is not, so a process started before `tau guard setup` is guarded from its
  next build on.
- **Admission.** `build_agent(guard=DISCOVER, client_id=None)` resolves the guard unless the
  caller passes one; `TauAgent` keeps `channel`, `guard` and `client_id` (random per process).
  `stream()` asks `guard.admit(GuardTurn(channel, session_id, client_id))` inside its lock
  before anything else; a refused turn yields `Notice(t("guard.refused.<reason>"))` and
  `TurnEnd("locked")`, emits `guard {"action": "refused", "channel", "reason"}` and changes no
  history. `ask()` raises `GuardLocked(reason)`, `summarize()` raises `CompactionLocked` (a
  `CompactionError` and a `GuardLocked`) before any model call. A raising guard, a timeout or
  an unknown reason refuses (`admit_turn`).
- **`HubGuard(config)`** talks to the hub through `HubClient`. Only a proven `unlocked` answer
  (`allowed: true` from `POST /guard/admit`) whose `enrollment` equals the local marker's
  admits; `off`, 404, 403, 5xx, a timeout, bad JSON, a missing proof or another enrollment
  mean `unavailable`. `admit` has a 3 s bound, all HTTP runs in daemon threads, and
  `unlock`/`step_up` post `/guard/verify`, long-poll `GET /guard/status?since=` (calling
  `on_progress` on every step) and post `/guard/cancel` when cancelled. The route contract is in
  the `tau_core.guard` module docstring.
- **Identified in-hub channels opt out in code**: Telegram and network turns pass
  `guard=None`, and a repo rule refuses `guard=None` anywhere else. No flag, variable or
  config key selects a channel.
- **Reports.** `/status` adds `guard_status_line(status, language)` when a guard is active;
  `tau doctor` adds `guard_doctor_check(config, hub_status)`.

Public API: `Guard` (protocol: `status`, `watch`, `admit`, `unlock`, `cancel`, `lock`,
`step_up`; every method fails closed), `GuardState`, `GuardStatus`, `GuardVerdict`,
`GuardProgress`, `GuardTurn`, `Admission`, `GuardLocked`, `LockedGuard`, `HubGuard`,
`resolve_guard`, `VERDICT_REASONS`, `ADMISSION_REASONS`, `LOCK_TRIGGERS`, `PROGRESS_STEPS`,
`ALLOWED_WHILE_LOCKED` from `tau_core`; `DISCOVER`, `ENROLLED_MARKER`, `GUARD_CONFIG_KEYS`,
`LOCKED_NOTE`, `STEP_UP_NOTE`, `admit_turn`, `guard_status_line`, `guard_doctor_check`,
`read_enrollment` and `reset_guards` from `tau_core.guard`; `HubClient`, `HubUnavailable`,
`HubError` from `tau_core.hub`. The guard's messages (`guard.*`, `status.guard`,
`doctor.guard.*`) register themselves with `register_messages`. Tests use
`tau_core.testing.FakeGuard(state, verdicts=..., step_ups=..., progress=..., admissions=...)`,
which replays scripted answers and never approves anything.

## Components

Every pluggable part of tau is a *component*: it reaches tau through a built-in seed
(`PROVIDERS`, `SESSION_BACKENDS`), an entry point in a `tau.*` group declared by any installed
distribution, or an in-process registration (`register_provider`, `register_session_backend`),
and `tau.toml` decides which discovered components are on (ADR 0005). `tau_core.registry` loads
them all with one rule: an entry point that fails to load, or loads the wrong kind of object,
is logged with its distribution name and skipped; it never breaks the CLI.

| group | entry point value | picked by |
|---|---|---|
| `tau.tools` | an `AgentTool` with a tier, a list of them, or a zero-argument factory | `build_agent` (all, minus `tools.disabled`) |
| `tau.commands` | a `click.Command`, mounted as `tau <name>` | the `tau` command |
| `tau.providers` | `factory(RoleConfig, env) -> Model`; optional `required_env = [["VAR", ...], ...]` on the factory (credential alternatives) | a role's `provider` in `tau.toml` |
| `tau.sessions` | `factory(Config) -> SessionStore` | `[sessions].backend` |
| `tau.context` | `factory(Config) -> ContextSource` (a callable returning `{"nodes": ..., "budget": ...}`) | `build_agent` when no `context_sources` are passed |
| `tau.hub_services` | `factory(Config) -> HubService` | `tau hub run`, after the control API |

`tau.channels` stays reserved for hub-hosted channels. A plugin package declares what it ships:

```toml
[project.entry-points."tau.tools"]
mine = "my_package:TOOLS"              # tools carry a tier (tau_tool); untiered ones are skipped

[project.entry-points."tau.commands"]
mine = "my_package.cli:command"        # `tau mine`

[project.entry-points."tau.providers"]
ollama = "my_package.models:make_model"   # make_model(role_cfg, env) -> Model; make_model.required_env = []

[project.entry-points."tau.sessions"]
cloud = "my_package.sessions:make_store"  # make_store(config) -> SessionStore

[project.entry-points."tau.context"]
nodes = "my_package.mesh:make_source"     # make_source(config) -> callable returning {"nodes": [...]}

[project.entry-points."tau.hub_services"]
voice = "my_package.voice:make_service"   # make_service(config) -> HubService
```

A seed name wins over an entry point with the same name (an installed package cannot replace
`bedrock` silently); `register_provider` / `register_session_backend` replace anything, since
they are explicit code. `Config.load` validates provider and backend *names* without loading a
single entry point, so `tau version` never imports a provider SDK.

Switch discovered components on or off in `tau.toml` without uninstalling them:

```toml
[components]
context = []                 # enabled tau.context sources; empty = every discovered one
[components.tools]
disabled = ["demo_physical_action", "dist:tau-example-tool"]   # tool names or dist:<distribution>
[components.hub]
services = []                # enabled tau.hub_services; empty = every discovered one

[component.telegram]         # a component's own settings: config.component("telegram")
poll_timeout_seconds = 50
```

`tools.disabled` can only remove tools; it never adds one, gives one a tier or changes a tier,
and an explicit `build_agent(tools=[...])` bypasses it. Any other top-level table in `tau.toml`
is logged once and ignored, never a failure. Nothing in `[components]` can replace the tier
gate, the approver or the catalog: a tool that reaches the Strands agent behind the catalog's
back (through a `Plugin`, for instance) is refused as unknown.

Three commands show, check and set up an installation (English, `--json` where useful):

```sh
tau components          # every component in every group: distribution, version, enabled/disabled, load error
tau doctor              # config, per-role provider + credentials (no client built), session store, persona
                        # files, .env names vs .env.example, component load errors, [components] names that
                        # no installed component provides, control API reachable, Telegram poller state;
                        # exit 1 when a check fails
                        # ("warn" for a planned provider such as ollama and for the unknown names)
tau init                # tau.toml from the shipped template (provider: bedrock > anthropic > fake, by the
                        # credentials present in the environment or <home>/.env), persona/persona.md,
                        # user.example.md, user.md (from the example unless it exists) and .env.example;
                        # asks the UI language unless --language or --yes
tau init --home ~/.tau --provider anthropic --language tr --profile home --yes   # non-interactive
```

`tau init` never overwrites an existing `tau.toml` or `persona.md` without `--force` and never
overwrites `user.md` or `.env.example` (the latter is the list of names `tau doctor` checks
`.env` against; add your own names there); `--profile` appends `TAU_PROFILE` to `<home>/.env`
when it is not set there. The shipped templates equal the repository's `tau.toml`,
`persona/persona.md` and `persona/user.example.md` (a test keeps them identical); the
`.env.example` template is the repository's file without its L0 remote-access section. A
`tau.providers` entry point that is declared but does not load is reported as `Model provider
'x' from <distribution> failed to load: ...` by `tau doctor`, `tau chat` and `tau components`
alike; only a name no distribution declares is an `Unknown model provider`.

## Logging

`configure_logging(logs_dir, verbose=False)` sends `WARNING`s (or `INFO` with `verbose`) to
stderr as one-line messages and, when `logs_dir` is given, `INFO` and up with tracebacks to
`<logs_dir>/tau.log` (`tau chat` and `tau hub run` use `config.logs_dir`); it returns the log
file path. `reset_logging()` removes those handlers again. Both are part of the public API so a
channel in another package (the TUI, Telegram) writes to the same file; a full-screen UI that
owns the terminal passes `console=False` to keep stderr silent while the file log still
receives every record.

## Development

```sh
uv sync --all-packages --group dev
uv run pytest -q
uv run ruff check . && uv run ruff format .
uv build --package tau-core
```

License: MIT.
