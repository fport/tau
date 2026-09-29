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

- [ ] `/sessions`, `/resume`, `/resume <n|id>`, `/new` and `/session` work in the TUI with the same wording as the terminal channel (shared `tau_core.commands` spec and message table)
- [ ] Resuming rebuilds the agent on the stored session; the header shows the new session id and the event pane follows the new `EventBus`
- [ ] A resumed session's stored events are replayed into the event pane before live events
- [ ] A failed rebuild leaves the current agent working
- [ ] Pilot tests with `MemorySessionStore`/`FileSessionStore` and `FakeModel`

## Blocked by

None - #007 and #008 are done.

## Comments

- 2026-09-29: merged from two proposals by the agents that closed #007 ("Session picker and event replay in the TUI") and #008 ("Session commands in the TUI").
- 2026-09-29: absorbed by 063 (premium TUI), closed when 063 closes. Command names reworded to the English canonical names from 062.
