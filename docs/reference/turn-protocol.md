# Turn protocol

The turn protocol is how the web app talks to a tau ([ADR 0015](../adr/0015-web-app-agentic-chat.md) §1). There are two backends:

- the hub's `tau-web` service, where the Strands agent runs inside the hub;
- tau-host, where the TypeScript loop runs in a Durable Object.

Both stream the same events and serve the same history, so the app does not care which one answers.

| Half | Where |
|---|---|
| Python | `tau_core.turn_protocol`: event bodies, framing and history blocks |
| TypeScript | `cloud/shared/turn`: types, the validator (`parseEvent`, `parseBlock`) and the NDJSON reader (`readEvents`) |
| Vectors | `cloud/shared/turn/vectors.json`, written by `packages/tau-core/scripts/make_turn_vectors.py`. Both halves test against it, and pytest fails when the file is stale |

## Framing

A turn streams as **NDJSON** over a streaming `fetch` response (`Content-Type: application/x-ndjson`). The rules:

- Each line is one compact JSON object in UTF-8:

  ```json
  {"v":1,"seq":0,"type":"turn","turn":"t-1","session":"20261001-080000-abcd"}
  ```

- `v` is the protocol version, `1`.
- `seq` counts from `0` within a turn, without gaps. A client that re-attaches gets every event after the last `seq` it saw.
- `type` is one of the event types below.
- Extra fields may appear in later versions. Clients ignore what they do not know.
- Text is never HTML. The app renders `text` deltas as Markdown, without raw HTML.

## Events

| `type` | Fields | When |
|---|---|---|
| `turn` | `turn`, `session` | First event of every turn |
| `text` | `delta` | A piece of the reply |
| `reasoning` | `delta` | A piece of the model's extended thinking |
| `tool_use` | `id`, `tool`, `tier` (`0`–`2` or `null`) | The model started a tool call. Its input may still be streaming |
| `tool_input` | `id`, `tool`, input fields | The call's complete input, before the tool runs or asks for approval |
| `tool_progress` | `id`, `tool`, `message` | A streaming tool reported progress |
| `tool_result` | `id`, `tool`, `status`, `summary`, `approval` | The call finished |
| `approval` | `request`, `tool`, `tier`, `effect`, input fields, `expires_at` | A tier-2 call waits for the owner |
| `approval_decided` | `request`, `decision` | How that approval ended |
| `widget` | `id`, `title`, `html` | A widget from `render_ui` |
| `throttled` | `delay_seconds` | The provider throttled the call, and the SDK retries after this many seconds |
| `notice` | `text` | A line for the owner, in the UI language |
| `guard` | `action`, … | The owner guard: a refused turn or a step-up's progress |
| `end` | `stop_reason` | Last event of every turn |
| `error` | `message` | The backend failed outside the agent. An `end` follows |

### Field values

- **`status`** of `tool_result` is one of:
  - `ok`;
  - `error` (the tool failed);
  - `rejected` (refused before it ran: by the tier gate, the owner or the guard).
- **`approval`** says how a tier-2 call got through, or why it did not: `approved`, `rejected`, `timeout`, `exempt` (a routine), `locked` or `null`.
- **`stop_reason`** is one of tau-core's `STOP_REASONS`: `end_turn`, `limit_turns`, `limit_total_tokens`, `max_tokens`, `cancelled`, `interrupt`, `error`, `busy`, `locked`.
- **`decision`** is `approved`, `rejected` or `timeout`.
- **`expires_at`** is in Unix seconds, or `null`.
- **`effect`** is the tool's declared effect, for example `physical`.
- **The widget's `id`** is the id of its `render_ui` tool use.

### Input fields

`tool_input`, `approval` and the history's `tool` blocks carry a tool's input in one of two forms:

- `{"input": {...}, "truncated": false}` when its JSON fits in 8192 bytes (`INPUT_LIMIT`);
- `{"input": null, "preview": "<first 8192 characters of the JSON>", "truncated": true}` otherwise.

A widget's HTML travels in its own `widget` event, not in `tool_input`.

### Order

A tool call streams as:

1. `tool_use`
2. `tool_input`
3. `approval` and `approval_decided`, for tier 2 only. `guard` events can come between them, during the step-up.
4. `tool_progress`, zero or more times
5. `tool_result`

A `render_ui` call adds a `widget` event before its `tool_result`. Text, reasoning and other tool calls can come between these steps.

## Example

```json
{"v":1,"seq":0,"type":"turn","turn":"t-1","session":"20261001-080000-abcd"}
{"v":1,"seq":1,"type":"tool_use","id":"u1","tool":"lamp_set","tier":2}
{"v":1,"seq":2,"type":"tool_input","id":"u1","tool":"lamp_set","input":{"name":"desk","on":true},"truncated":false}
{"v":1,"seq":3,"type":"approval","request":"a1","tool":"lamp_set","tier":2,"effect":"physical","input":{"name":"desk","on":true},"truncated":false,"expires_at":1790841900.0}
{"v":1,"seq":4,"type":"approval_decided","request":"a1","decision":"approved"}
{"v":1,"seq":5,"type":"tool_result","id":"u1","tool":"lamp_set","status":"ok","summary":"desk lamp is on (simulated)","approval":"approved"}
{"v":1,"seq":6,"type":"text","delta":"The desk lamp is on."}
{"v":1,"seq":7,"type":"end","stop_reason":"end_turn"}
```

## History

`GET <base>/sessions/<id>` returns `{"session": {...}, "blocks": [...]}`. Blocks are listed oldest first, and each has `at`, the ISO 8601 time it was recorded, or `null` when the store kept none.

| `type` | Fields |
|---|---|
| `user` | `text` |
| `assistant` | `text` (Markdown; consecutive text blocks of one reply are joined) |
| `reasoning` | `text` |
| `tool` | `id`, `tool`, `tier`, input fields, `status` (`ok`, `error`, `rejected` or `null`), `summary`, `approval`, `duration_ms` |
| `widget` | `id`, `title`, `html` (a `render_ui` call with a valid input) |
| `notice` | `text` |

How the blocks are built:

- **Messages first.** The session's messages are the truth.
- **Events add details.** The recorded agent events supply the tier, status, approval, summary and duration of each call.
- **Notices.** They come from `notice` events and are placed by time, so they appear only when the messages have timestamps.
- **Orphaned results.** A tool result whose call is not in the history becomes a `tool` block with `tool: "?"`.

## Routes

Every backend serves these under its base path: `/api` on the hub, `/api/host` on tau-host.

| Route | Answer |
|---|---|
| `GET <base>/capabilities` | `{"backend": "hub" \| "host", "language", "pages": [...], "protocol": 1}`. `pages` names the optional pages, for example `routines`, `tasks`, `devices`, `toolbox`, `subs`, `net` and `guard` |
| `POST <base>/turns` with `{"session"?: id, "text"}` | The NDJSON stream of a new turn. Without `session`, a new session starts |
| `GET <base>/turns/<turn>?after=<seq>` | The rest of a running or just-finished turn, from `after + 1` |
| `POST <base>/turns/<turn>/cancel` | `204`. The turn ends with `end` and `stop_reason: "cancelled"` |
| `POST <base>/approvals/<request>` with `{"decision": "approved" \| "rejected"}` | `204`, or `409` once decided or expired |
| `GET <base>/sessions` | `{"sessions": [{id, title, channel, created_at, updated_at, message_count}]}`, newest first |
| `GET <base>/sessions/<id>` | `{"session": {...}, "blocks": [...]}` |

### Rules for every backend

- **The turn is independent of the tab.** A turn runs in the backend whether or not anyone reads it. A dropped connection does not stop it.
- **Re-attaching.** The backend keeps a running turn's events at least until a few minutes after `end`.
- **Approvals.** They are answered only through the approval route, by an authenticated owner: a paired device on the hub, a signed-in owner on tau-host. Nothing approves on its own.
- **Validation.** The backend validates its output against this spec, and the app refuses lines that do not parse (`ProtocolError`).

Authentication (paired devices on the hub, the GitHub session on tau-host) belongs to each backend, not to this protocol: see issues 178 and 185.
