# 177 · The turn protocol: JSON turn events and session history shared by the hub and tau-host

Status: ready-for-agent
Type: AFK
Layer: L4 · Interface
Packages: tau-core, cloud/shared, docs
Blocked by: –

## What to build

The contract between the web app and either backend ([ADR 0015](../../docs/adr/0015-web-app-agentic-chat.md) §1).

**The spec.** Write `docs/reference/turn-protocol.md`, a reference page in English only.

- **Events.** Each event is one JSON line `{v: 1, seq, type, …}`. `seq` rises by one within a turn. The types are:
  - `turn {turn, session}`
  - `text {delta}` and `reasoning {delta}`
  - `tool_use {id, tool, tier, input}`, with the input cut at 8 KB and marked as cut
  - `tool_progress {id, message}`
  - `tool_result {id, status: ok|error|refused|rejected|locked, summary}`
  - `approval {request, tool, tier, input, reason, expires_at}` and `approval_decided {request, decision}`
  - `widget {id, tool_use, title, html}` (180)
  - `throttled {role, reason}`
  - `notice {key, params, text}`
  - `guard {action, …}`, which carries ADR 0008's challenge events
  - `end {stop_reason}`, where the stop reasons are tau-core's `STOP_REASONS`
  - `error {message}`
- **History.** A session's history is a list of display blocks: `user`, `assistant`, `tool` (use and result paired), `widget` and `notice`. Every block has the time it was recorded.
- **Transport.** Specify the routes both backends offer:
  - `POST /api/turns {session?, text}` returns the stream;
  - `GET /api/turns/<id>?after=<seq>` re-attaches;
  - `POST /api/turns/<id>/cancel`;
  - `POST /api/approvals/<id> {decision}`;
  - `GET /api/sessions` and `GET /api/sessions/<id>`;
  - `GET /api/capabilities`.
  - Paths are relative to a backend base, so tau-host can keep `/api/host/…`.

**tau-core.** Add a public, stable serializer (`tau_core.turn_json` or similar, exported from the package):

- `event_to_json(TurnEvent)`, and one function that builds the `approval` event from an `ApprovalRequest`;
- `history_blocks(messages, events)`, which turns a stored session (Strands messages plus `events.jsonl`) into display blocks;
- `ToolUseStarted` gains the tool's input. This is an additive change: the TUI ignores it.

**TypeScript.** Add the types and a runtime validator in `cloud/shared/turn/`, with vitest tests. This is not under `cloud/shared/net`, which belongs to the network work.

## Acceptance criteria

- [ ] `docs/reference/turn-protocol.md` specifies every event, the history blocks and the routes, with one example stream
- [ ] tau-core serializes every `TurnEvent` and approval to the protocol; a golden-file test pins the JSON of each type
- [ ] `history_blocks` reproduces a recorded session with tool calls, a refusal and an approval (fixture session)
- [ ] `cloud/shared/turn` validates the same golden files (a shared fixture directory read by pytest and vitest)
- [ ] `ToolUseStarted.input` exists and the TUI and terminal still pass their tests

## Blocked by

None - can start immediately.

## Comments

- 2026-10-01: filed with ADR 0015. tau-host's current NDJSON events (`start`, `text`, `tool`, `tool_result`, `notice`, `approval`, `done`, `error`) move to this protocol in 185.
