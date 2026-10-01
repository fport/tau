# 177 · The turn protocol: JSON turn events and session history shared by the hub and tau-host

Status: done
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

- [x] `docs/reference/turn-protocol.md` specifies every event, the history blocks and the routes, with one example stream
- [x] tau-core serializes every `TurnEvent` and approval to the protocol; a golden-file test pins the JSON of each type
- [x] `history_blocks` reproduces a recorded session with tool calls, a refusal and an approval (fixture session)
- [x] `cloud/shared/turn` validates the same golden files (a shared fixture directory read by pytest and vitest)
- [x] The complete tool input reaches the stream (as built: a new `ToolInput` turn event, see Comments) and the TUI and terminal still pass their tests

## Blocked by

None - can start immediately.

## Comments

- 2026-10-01: filed with ADR 0015. tau-host's current NDJSON events (`start`, `text`, `tool`, `tool_result`, `notice`, `approval`, `done`, `error`) move to this protocol in 185.
- 2026-10-01: done (c8598c0, 772597d, 63ca7a5, 5979148).
  - **Changes from the spec above:**
    - The input does not ride on `ToolUseStarted`, because that event arrives while the model still streams the input. A new turn event, `ToolInput(tool_use_id, tool, input)`, comes from the SDK's `message` event once the reply is complete, before the tool runs or asks for approval. On the wire this is `tool_use` (no input) followed by `tool_input`.
    - `throttled` carries `delay_seconds`, and `notice` carries only `text`, which is what tau-core has.
    - A widget's `id` is its `render_ui` tool use id, so there is no separate `tool_use` field.
    - `tool_result.status` is `ok`, `error` or `rejected`, as the tier gate records it.
  - **Python:** `tau_core.turn_protocol` (imported by name), with `frame`, `encode`, `turn_event_body`, `approval_body`, `approval_decided`, `guard_body`, `widget_body`, `error_body`, `turn_started` and `history_blocks`. `ToolInput` and `tool_inputs_of` are exported from `tau_core`.
  - **Vectors:** `packages/tau-core/scripts/make_turn_vectors.py` writes `cloud/shared/turn/vectors.json`, and pytest fails when the file is stale.
  - **TypeScript:** `cloud/shared/turn/index.ts` has the types, `parseEvent`, `parseBlock`, `readEvents` and `LineSplitter`. Vitest runs it in workerd and Node.
  - **For 178:** buffer the framed events per turn and serve `after=` from the buffer. Read history with `store.list_messages(session_id, "tau")` plus `read_events`.
