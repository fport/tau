# 056 · Session index for fast listing once sessions number in the thousands

Status: ready-for-agent
Type: AFK
Layer: L1 · Agent
Packages: tau-core
Blocked by: none

## What to build

`FileSessionStore.list_sessions` reads every session directory (`session.json`, `meta.json` and a directory listing each) and then sorts by `updated_at`. That is fine for hundreds of sessions, but with "keep everything" retention and a new session record on every `tau chat` start (Strands' `RepositorySessionManager` creates it as soon as the agent is built, even when no message follows) it grows without bound.

Add an append-only or atomically rewritten index file inside the store (id, created_at, updated_at, channel, profile, title, message_count), rebuilt from the directories when it is missing or stale, so `/sessions` and `/resume` stay instant. Callers stay the same (ADR 0003 already names this seam). Consider creating the session record lazily on the first message so empty sessions stop accumulating.

## Acceptance criteria

- [ ] `list_sessions()` reads one index file on the hot path and returns the same result as today
- [ ] A missing, stale or corrupt index is rebuilt from the session directories; nothing is ever deleted
- [ ] Empty sessions (no messages) either are not created or stay hidden from `/sessions` and `/resume`
- [ ] A test with a few thousand generated sessions shows the listing well under a second

## Blocked by

None - low priority; measure first.

## Comments

- 2026-09-29: proposed by the agent that closed #007, together with its note about empty session directories.
- 2026-09-29: triaged → ready-for-agent, low priority: benchmark `list_sessions()` with a few thousand generated sessions first and only build the index if the listing is measurably slow. The "create the session record lazily" half changes `RepositorySessionManager` behaviour, so coordinate it with the outcome of 064 and 071.
