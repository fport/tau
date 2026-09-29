# tau-tui

A [Textual](https://textual.textualize.io/) terminal interface for tau: a chat pane where replies
stream in, a live event pane (tool calls with tier and approval result, errors, notices) and an
in-TUI approval dialog for tier-2 calls. It is built for 80x24 and works over SSH/mosh from a
phone (Termius).

It is its own distribution (`tau-tui`, import `tau_tui`), uses only the public API of `tau-core`
and plugs into the `tau` command through the `tau.commands` entry point (`tui`):

```sh
pip install tau-tui          # or, in this repo: uv sync --all-packages --group dev
tau tui                      # new session
tau tui --resume             # continue the most recent session
tau tui --resume ID          # continue a given session
tau --home /path/to/tau tui --profile ev
```

Configuration comes from `tau.toml` and `.env` like every other channel (`TAU_HOME`,
`TAU_DATA_DIR`, `TAU_PROFILE`). Missing credentials or config end the command with the Turkish
message and exit code 2 before the interface opens.

## Layout

```
tau  profil: ev  oturum: 20260929-120000-abcd        one-line header: profile + session id only
sen: saat kaç?                                        chat pane (Sohbet)
     ⚙ current_time (tier 0)
     ✓ current_time: 15:30
tau: Saat 15:30 efendim.
─Olaylar──────────────────────────────────────        event pane
12:00:01 ✓ current_time · tier 0 · ok · 3 ms — 15:30
Mesajınızı yazın · /araçlar · /çık                    input line
```

Under 100 columns the panes stack (chat above events); wider terminals put them side by side.
The header and the input take one row each and the panes have no side borders, so most of an
80x24 screen goes to the conversation. Both panes re-wrap their content when the terminal is
resized. Colors come from the brand palette (`docs/brand/`).

- **Chat pane** — `sen:` / `tau:` blocks. Only the turn events of `TauAgent.stream()` drive it:
  text deltas stream into the current `tau:` block, tool starts and results show as indented
  lines (`⚙`, `✓`, `✗ … onaylanmadı`), notices as `ℹ` lines.
- **Event pane** — subscribes to the agent's `EventBus` and shows every agent event with local
  time: `tool_call` (tool, tier, `ok`/`error`/`rejected`, approval, duration, summary),
  `approval` (tool, tier, decision, channel), `turn_limit`, `error`, `notice`; unknown kinds are
  shown as `kind: {data}`.

## Keys and commands

| Key / command | Effect |
|---|---|
| Enter | send the message (ignored with a notice while tau is still answering; the text stays) |
| `/araçlar` | list the registered tools with their tiers |
| `/çık` (or `/cik`), Ctrl+Q | quit (Ctrl+C only shows how to quit, it copies inside the input) |

## Approvals

`TuiApprover` (`name = "tui"`) is the channel's `Approver`. For a tier-2 call it opens
`ApprovalScreen`: tool, arguments as pretty JSON, effect, and the buttons **Onayla** / **Reddet**.

- `e` approves, `h` or Esc rejects; focus starts on **Reddet**, so Enter rejects.
- `e` and **Onayla** only work 0.5 s after the dialog opens, so keys typed for the chat cannot
  approve by accident.
- Anything other than an explicit approval rejects: a dialog closed another way, an approver
  with no running app, or a cancelled wait (the dialog is taken down so it cannot approve later).

Nothing in this package approves on its own.

## Logs

While the interface runs the terminal belongs to Textual, so details go to
`<TAU_DATA_DIR>/logs/tau.log` (for example `~/.local/share/tau/logs/tau.log`); the chat shows a
short Turkish notice instead of a traceback.

## Python API

```python
from tau_tui import TauApp, build_app, ChatPane, EventPane, ApprovalScreen, TuiApprover

app = build_app(config, session_store=store, session_id=None)  # builds the agent (channel "tui")
app.run()
```

`build_app` calls `tau_core.build_agent(..., approver=TuiApprover(), channel="tui")` and wraps
the result in `TauApp`; tests pass `model=FakeModel([...])`, `tools=[...]`, a fixed `clock` and
`session_id`. `resolve_resume(store, resume)` turns `--resume [ID]` into a session id and a
notice (`SessionNotFound` for an unknown id).

## Development

```sh
uv run pytest packages/tau-tui -q                      # pilot + snapshot tests, offline
uv run pytest packages/tau-tui --snapshot-update       # after an intended visual change
```

The snapshot under `tests/__snapshots__/` is the empty app at 80x24 with a fixed session id;
review the new SVG before committing it (it must never contain a local path).

License: MIT.
