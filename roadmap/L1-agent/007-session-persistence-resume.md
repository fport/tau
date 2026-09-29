# 007 · Session persistence and `/devam` resume

Status: done
Type: AFK
Layer: L1 · Agent
Packages: tau-core
Blocked by: 004

## What to build

Conversations are recorded as sessions — messages, tool calls, approvals — through a pluggable session store. The first backend writes local files. `/devam` lists recent sessions and resumes one with full context. The store interface must allow the D1 backend (#018) without touching callers.

## Acceptance criteria

- [x] Quit and restart `tau chat`; `/devam` resumes the last session with context intact
- [x] Session records include tool calls and approval decisions
- [x] The backend is chosen by config; the file backend is just one implementation
- [x] Nothing is deleted automatically (retention: keep everything)
- [x] Tests cover record and resume

## Blocked by

- [004 · Tracer bullet: `tau chat` answers in the Jarvis persona](004-tau-chat-tracer-bullet.md)

## Comments

### 2026-09-29 · done (agent)

Sessions are now recorded to files and resumed with `/devam`. `FileSessionStore`
(`tau_core/sessions/file.py`) implements the whole `SessionStore` interface under
`TAU_DATA_DIR/sessions/<session id>/` (`session.json`, `meta.json`, append-only `events.jsonl`,
`agents/tau/agent.json`, `agents/tau/messages/000000.json`, ...) with atomic writes (temp file,
fsync, `os.replace`), `0700`/`0600` permissions, symlink refusal and id validation. It is
registered as `file` in `SESSION_BACKENDS` (dropped from `PLANNED_BACKENDS`) and the repo's
`tau.toml` uses it; `test_config` keeps `memory`. `/devam`, `/devam <n|id>`, `tau chat --resume
[ID]`, `/yeni` and `/oturum` work. `uv run ruff check . && uv run ruff format --check . &&
uv run pytest -q` is green (116 tests, offline).

Criteria notes: quit/restart/resume is covered in-process with `CliRunner` and `FakeModel`
(the second run's model call carries the first run's messages); tool calls (every tier) and
approval decisions (approved, scripted-rejected, default-rejected) are asserted in the raw
`events.jsonl`; "nothing deleted" is enforced (no delete method, `create_message` never
overwrites, a truncated event line stays on disk) and tested by checking that the file set
only grows.

Commits:
- `docs(roadmap): start 007`
- `feat(core): add the file session store and make it the default`
- `feat(core): resume sessions with /devam, /yeni and /oturum`
- `docs: document session files and /devam, refine ADR 0003`
- `docs(roadmap): close 007`

Deviations from the shared brief: message files are numbered from `000000.json` because
Strands' message ids start at 0; `test_cli.py` (004's file) had to change its one placeholder
assertion (`Henüz yok (issue 007).` ×3) to the new behaviour; invalid session ids raise
`InvalidSessionId`, a `ConfigError` subclass, so `tau chat --session ../x` exits 2 with a
Turkish message without touching `chat()`. The module docstring of `channels/terminal.py`
still calls the three commands placeholders and `NOT_YET_SESSIONS` is now unused; both sit
outside the three bodies 007 owned and can go in a later cleanup.

For later issues:
- Every `tau chat` start creates a session directory (Strands' `RepositorySessionManager`
  creates the session when the agent is built). Empty sessions are kept and hidden from
  `/devam`, which also never lists the current session. Resuming rewrites `channel`/`profile`
  meta (via `build_agent`), so the resumed session moves to the top and shows the last channel.
- 008: `open_session_store(config)` gives the TUI the same store; `list_sessions()` and
  `read_events()` are enough for a session picker and an event replay.
- 018: implement `cloud` as a client of the tau-cloud Worker API behind the same interface
  (ADR 0003 refinement); `tests/test_sessions.py` runs the store contract parametrized over
  backends, so adding the cloud store to its `store` fixture (with a fake Worker) reuses it.
