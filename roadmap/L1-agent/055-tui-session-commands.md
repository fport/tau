# 055 · Session commands and event replay in the TUI

Status: in-progress
Type: AFK
Layer: L1 · Agent
Packages: tau-tui
Blocked by: none

## What to build

The TUI supports `tau tui --resume [ID]` at startup, plus `/tools` and `/quit`, but it cannot switch sessions while running. The terminal channel already has `/sessions`, `/resume`, `/new` and `/session` on top of the file session store (#007), and the store keeps every session's messages and agent events (tool calls, approvals, turn limits, errors).

Add the same three commands to `TauApp`: list recent sessions from `list_sessions()` in the chat pane, rebuild the agent with `build_app`/`build_agent` after `agent.close()`, re-subscribe the event pane to the new `EventBus`, and update the header's session id. When a session is resumed, replay its `read_events()` into the event pane so the user sees what tau did last time, not only the chat text. The public tau-core API (`open_session_store`, `SessionStore`) already covers it; tau-core needs no changes.

## Acceptance criteria

- [x] `/sessions`, `/resume`, `/resume <n|id>`, `/new` and `/session` work in the TUI with the same wording as the terminal channel (shared `tau_core.commands` spec and message table)
- [x] Resuming rebuilds the agent on the stored session; the header shows the new session id and the event pane follows the new `EventBus`
- [x] A resumed session's stored events are replayed into the event pane before live events
- [x] A failed rebuild leaves the current agent working
- [x] Pilot tests with `MemorySessionStore`/`FileSessionStore` and `FakeModel`

## Blocked by

None - #007 and #008 are done.

## Comments

- 2026-09-29: merged from two proposals by the agents that closed #007 ("Session picker and event replay in the TUI") and #008 ("Session commands in the TUI").
- 2026-09-29: absorbed by 063 (premium TUI), closed when 063 closes. Command names reworded to the English canonical names from 062.
- 2026-09-29: done inside 063 (`tau_tui/commands.py`, `TauApp.switch_session`, `EventLog.replay`; tests in `packages/tau-tui/tests/test_sessions.py` and `test_history.py`). The pilot tests use `MemorySessionStore`; the file store is covered by tau-core's own tests and the CLI smoke run.
- 2026-09-29: tests extended (sidebar rows and a pick at 160x45, an invalid `/resume` name, `/lang` relabelling the open picker, the picker snapshot `test_picker_80x24`).
- 2026-09-29: review fix: the picker built its rows as markup strings, so a session titled with `[/x]` raised `MarkupError` and took the app down; the list is `markup=False` now and `test_picker_shows_markup_looking_titles_verbatim` covers the picker, the `/sessions` card and the sidebar.
