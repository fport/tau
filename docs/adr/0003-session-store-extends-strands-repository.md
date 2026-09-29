# 0003 · The session store extends the Strands session repository

- Status: accepted (first version, issue 004; refined by issue 007; issue 018 adds the cloud backend)
- Date: 2026-09-29

## Context

Sessions are kept forever and resumed with `/resume`. Strands Agents already persists messages
and agent state through `SessionRepository` + `RepositorySessionManager` (restores
`agent.messages` on start, appends every message), but it has no way to list sessions, no
place for tau's agent events (tool calls, approvals, turn limits, errors) and no session
metadata (channel, profile, title). The first backend writes local files; a later one stores
sessions in D1 behind the tau-cloud Worker.

## Decision

- **`SessionStore(SessionRepository, ABC)`** is the only interface callers use. It adds
  `list_sessions(limit)`, `append_event` / `read_events` (agent events), `write_meta` /
  `read_meta` and `event_sink(session_id)` (an `EventBus` subscriber).
- `build_agent(session_store=...)` wires Strands' `RepositorySessionManager` to the store,
  writes `channel` and `profile` metadata and subscribes the store to the agent's event bus;
  `TauAgent.stream` writes the title (the first user message, 60 characters).
- Backends are a registry, **`SESSION_BACKENDS: dict[str, Callable[[Config], SessionStore]]`**,
  chosen by `[sessions].backend` in `tau.toml`: `memory` (issue 004), `file` (issue 007),
  `cloud` (issue 018). Callers never import a backend class to choose it.
- The `cloud` backend talks **only to the tau-cloud Worker API**. The hub never holds D1
  credentials and never calls the D1 REST API directly.
- Nothing is deleted automatically; retention is "keep everything" until a setting says
  otherwise.

## Consequences

- Any Strands feature built on `SessionRepository` keeps working with every tau backend.
- A new backend implements the nine repository methods plus the five tau extras.

## Refinement (issue 007, 2026-09-29)

- **File backend.** `FileSessionStore` keeps one directory per session under
  `TAU_DATA_DIR/sessions/`: `session.json` (the Strands session record, whose `updated_at` is
  refreshed on every write and orders the listing), `meta.json`, an append-only
  `events.jsonl` and `agents/<agent_id>/{agent.json, messages/000000.json, ...}`. It is the
  default in the repo's `tau.toml`; tests keep `memory`.
- **Why not Strands' `FileSessionManager`.** It is a session manager and repository in one,
  has `delete_session`, and offers no listing, events or metadata. tau keeps its own store
  behind `SessionStore` and mirrors only its write discipline: temp file in the same
  directory, fsync, `os.replace`; no reading or writing through symlinks.
- **Keep everything, enforced.** The store has no delete method, `create_message` refuses to
  overwrite an existing message (two writers on one session fail loudly instead of losing a
  message), and a crash-truncated event line is skipped on read but left on disk. A session
  that was opened and closed without a message stays on disk; `/sessions` does not list it.
- **Private by default.** Directories are `0700`, files `0600`. Session and agent ids must be
  plain names (letters, digits, `.`, `_`, `-`, starting with a letter or digit); anything else
  raises `InvalidSessionId`, a `ConfigError`, so `tau chat --session ../x` ends with a notice
  in the UI language instead of a traceback.
- **Listing cost.** `list_sessions` reads every session directory (two small JSON files and a
  directory listing each). That is fine at personal scale; if it ever is not, an index file
  can be added inside the store without touching callers.
- **Resume semantics.** `/sessions` lists earlier sessions that have messages, newest first,
  and never the current one; `/resume [n|id]` resumes the most recent one, the n-th of the
  last listing or an id. Resuming rebuilds the agent with `build_agent(session_id=...)`, so
  Strands restores `agent.messages`. Rebuilding writes the channel and profile again, so a
  resumed session moves to the top of the list and its `channel` is the last one used.
- **Cloud backend (issue 018).** It is an HTTP client of the tau-cloud Worker API, registered
  as `cloud` in `SESSION_BACKENDS` and implementing the same interface. The hub authenticates
  to the Worker only; it never holds D1 credentials and never calls the D1 REST API.
  Endpoints, pagination and offline behaviour are decided in 018 and stay behind
  `SessionStore`.

## Amended (2026-09-29, issues 062 and 064)

- Commands are the English canonical names: `/sessions` lists, `/resume [n|id]` resumes
  (`/devam` and `/oturumlar` stay as aliases). `InvalidSessionId` is raised before Config exists
  and is plain English; the notice the channel prints is in the UI language.
- **The store keeps everything, the model sees a window.** `[agent] context = "sliding" |
  "summarize"` (default `sliding`, `window_size = 60`) picks Strands'
  `SlidingWindowConversationManager` or `SummarizingConversationManager`. The session store
  still records every message; only the messages sent to the model are windowed. The SDK's
  `context_manager="auto"`/`"agentic"` modes are not used because they register untiered SDK
  tools that the tier gate would refuse.
