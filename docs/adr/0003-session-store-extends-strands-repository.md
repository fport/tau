# 0003 · The session store extends the Strands session repository

- Status: accepted (first version, issue 004; refined by issue 007 and issue 018)
- Date: 2026-09-29

## Context

Sessions are kept forever and resumed with `/devam`. Strands Agents already persists messages
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
