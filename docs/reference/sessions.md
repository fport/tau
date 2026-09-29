# Sessions and compaction

A **session** is one recorded conversation: its messages, its agent events (tool calls, approval decisions, turn limits, errors) and its metadata. Sessions are kept forever; nothing in tau deletes one. `/sessions` lists them, `/resume` continues one, `/compact` carries a long one forward as a summary in a *new* session. The design is [ADR 0003](../adr/0003-session-store-extends-strands-repository.md).

## Backends

`[sessions] backend` in `tau.toml` picks the store:

| Backend | Where | Notes |
|---|---|---|
| `memory` | the process | tests and throwaway runs; the code default when the key is absent |
| `file` | `TAU_DATA_DIR/sessions/<id>/` | the default in the shipped `tau.toml` |
| a `tau.sessions` component | wherever it says | see [Components and plugins](components.md) |

The `cloud` backend the first design planned (sessions in Cloudflare D1) is retired by [ADR 0006](../adr/0006-private-first-topology.md): the file store on the hub is the record, and the cloud only holds [encrypted backups](../guides/backups.md).

## File layout

One directory per session. Ids are `YYYYMMDD-HHMMSS-xxxx` in UTC, for example `20260929-153012-3f9a`.

```text
<TAU_DATA_DIR>/sessions/20260929-153012-3f9a/
├── session.json                    the Strands session record; its updated_at orders /sessions
├── meta.json                       channel, profile, title, role, compaction links
├── events.jsonl                    one agent event per line, append-only
└── agents/tau/
    ├── agent.json                  Strands agent state (including the conversation manager's state)
    └── messages/
        ├── 000000.json             one file per message, in order
        └── 000001.json
```

- JSON files are replaced atomically (temp file, fsync, rename). Directories are `0700`, files `0600`.
- Symlinks are never followed; ids must be plain names (letters, digits, `.`, `_`, `-`, starting with a letter or digit), so `tau chat --session ../x` ends with a notice, not a traceback.
- **Nothing is deleted.** The store has no delete method, `create_message` refuses to overwrite an existing message, and a crash-truncated event line is skipped on read but left on disk.
- A session opened and closed without a message stays on disk but is not listed.

## Metadata keys

`meta.json` is a flat object. Keys written by tau today:

| Key | Written when | Meaning |
|---|---|---|
| `channel` | the agent is built on the session | `terminal`, `tui`; later `telegram`, `voice`, … The last channel used. |
| `profile` | the agent is built | the active profile at that time |
| `title` | the first user message arrives | the first user message, cut to 60 characters |
| `role` | the agent is built, and on `/model` | the model role the session last ran on; `/resume` comes back on it |
| `compacted_to` | `/compact` | on the **old** session: the id of the summary session |
| `compacted_from` | `/compact` | on the **new** session: the id it summarizes |

Resuming rewrites `channel`, `profile` and `role`, so a resumed session moves to the top of the listing.

## Listing and resuming

- `/sessions` lists the 10 most recent earlier sessions that have messages, newest first, never the current one: `n. id  date  channel  title (N messages)`.
- `/resume` resumes the most recent one; `/resume n` the n-th of the last listing (without a listing, of the one `/sessions` would print now); `/resume <id>` that id. `tau chat --resume [ID]` and `tau tui --resume [ID]` do the same at start-up.
- Resuming rebuilds the agent on the stored session, so Strands restores `agent.messages`; the TUI renders the history (user rows, markdown replies, tool cards with the recorded duration, approval and result) and replays the stored agent events into the events pane before live ones.
- The TUI keeps the last 40 turns live; older ones fold into one line and PageUp at the top pages them in, 20 at a time.

## The context window

The store keeps every message; the **model** sees a window. `[agent] context` picks it:

| Mode | The model sees | Strands manager |
|---|---|---|
| `sliding` (default) | the last `window_size` messages (60) | `SlidingWindowConversationManager` |
| `summarize` | a summary of the older messages plus the last `window_size` verbatim | `SummarizingConversationManager` |

The manager's state (how many messages it dropped) is saved with the session, so a resumed agent restores the same window. `/status` shows `Context: sliding, window 60 · 14 messages in memory`.

!!! warning "The mismatch message"
    A session remembers the manager it was recorded with, and Strands refuses to restore it under the other one. After changing `context`, an earlier session fails to open, in `tau chat --resume`, `tau tui --resume`, `/resume` and the TUI's picker alike, with:

    ```text
    Session <id> was recorded with a different [agent] context setting; set it back to sliding or start a new session
    ```

    The current session is kept and nothing is written. Set the value back to open the old session, or start fresh.

When a conversation no longer fits the model's context window at all, the turn ends with `The conversation no longer fits the model's context window; start a new session with /new.` That is the moment for `/compact`.

## Compaction: `/compact [focus]`

Compaction is how a long conversation goes on without its whole history while every session stays on record. It is never a rewrite of an existing session.

1. tau runs a throwaway Strands agent on the session's **own model** over a copy of the messages, with no tools, no hooks and no session manager, so the tier gate is not involved and the live agent is untouched. The system prompt asks for a continuation summary: facts about the user, decisions, open tasks, tool results that still matter, and the language the user writes in. `focus` is appended as `Focus on: …`.
2. A **new session** is opened whose history starts with a two-message **seed**: a user message `Summary of the previous conversation (session <id>):` plus the summary, and the assistant's `Understood. I will continue from this summary.` The seed goes through the SDK's own append path, so it is part of the session and survives `--resume`.
3. The new session's metadata gets the old `title` and `compacted_from = <old id>`; the old session gets `compacted_to = <new id>` and keeps every message. `/sessions` lists both.
4. The channel prints `Compacted N messages into a summary. New session <new>; the previous session <old> is kept.` and the summary. `N` is what was summarized: the messages in memory, which the window may have trimmed below the stored count.

An empty history, a failed model call or an empty reply fail with `Compaction failed: …` and nothing changes. In the TUI the summary runs in a worker: the chrome is busy (`✻ Summarizing…`), `/status` still answers, turns and session switches are refused, Esc cancels with `Compaction cancelled; the session continues.`

## Repair turns

tau never appends to the history by hand. When a turn leaves the history *dangling* (a failed model call, the loop guard or token budget after a tool result, a cancel around tool execution, a session restored after a crash, or an assistant message with a `toolUse` and no result because the hub died while an approval was pending), the **next** turn sends a two-message prompt: an assistant notice with the last notice in parentheses (or `The previous turn did not finish.` for a crash-restored session), then your new message. Both go through the SDK, so roles keep alternating and the store gets tracking ids like every other message.

## Stop reasons

Every turn ends with a `TurnEnd(stop_reason)`; the channels turn some into notices:

| Stop reason | What happened | You see |
|---|---|---|
| `end_turn` | the model finished | – |
| `limit_turns` | `[agent] max_turns` model calls were used; the last call's tools still ran | `I reached the tool-call limit for this turn (N turns). I stopped; tell me if you want me to continue.` |
| `limit_total_tokens` | `[agent] max_total_tokens` reached | `I reached the token budget for this turn. …` |
| `max_tokens` | the reply hit the provider's output limit; the partial reply is kept | `The reply hit the length limit; say so if you want me to continue.` |
| `cancelled` | Ctrl-C or Esc stopped the turn at the next safe point | `Turn cancelled.` |
| `interrupt` | a hook kept interrupting; tau cleared the SDK's interrupt state | `A tool asked for an interrupt this channel cannot answer; it was refused.` |
| `error` | the model call failed, or the context overflowed | `Model call failed: …` / the overflow notice above |
| `busy` | another invocation held the agent; nothing ran | `I am still answering the previous turn.` |

## Agent events

`events.jsonl` holds one JSON object per line. Kinds today: `tool_call` (every call of every tier: tool, tier, arguments, status, result summary, approval, duration, tool use id), `approval` (every tier-2 question and its decision), `turn_limit`, `notice` and `error` (with `where`: `model`, `context`, `interrupt` or `tier_gate`). Turn events (`TextDelta`, `ToolUseStarted`, …) are what a channel renders live and are not stored.

## Logs

`<TAU_DATA_DIR>/logs/tau.log` receives `INFO` and up with tracebacks from every channel and from `tau hub run`. The terminal also prints `WARNING`s to stderr (`INFO` with `-v`); the TUI keeps stderr silent while it owns the screen.
