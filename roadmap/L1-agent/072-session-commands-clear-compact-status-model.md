# 072 · Session commands: /clear, /compact, /status and /model in both channels

Status: done
Type: AFK
Layer: L1 · Agent
Packages: tau-core, tau-tui
Blocked by: none

## What to build

Four slash commands shared by `tau chat` and `tau tui` through the `tau_core.commands` spec, with the same wording in both channels and Turkish aliases that are accepted but never shown:

- `/clear` (`/temizle`, `/cls`): the screen is emptied, nothing else. The terminal emits an ANSI clear and prints the ready banner again; the TUI removes every transcript widget (turns, welcome card, info cards, the fold) and resets its live-turn bookkeeping. The session and the agent go on; `--resume` shows the history again. Refused in the TUI while a turn is still mounting widgets.
- `/compact [focus]` (`/özet`, `/ozet`): Claude-Code-style compaction that respects "sessions are kept forever". `tau_core.compaction.summarize` runs a throwaway Strands `Agent` on the agent's own model over a deep copy of the history (no tools, no hooks, no session manager), then a **new** session is opened with `build_agent(seed_messages=...)`: a user message carrying the summary and an assistant acknowledgement, persisted by the SDK on creation so they survive `--resume`. The old session stays untouched; both are linked through `compacted_from` / `compacted_to` and the new one inherits the title. Failures (`CompactionError`, `MissingCredentials`, `ConfigError`) leave the current agent unchanged.
- `/status` (`/durum`): a read-only report allowed while busy: profile, session (id, title, stored message count, role), model (role → provider, fallback in use, model id; never a key), context mode and window with the in-memory count, tools (registered, tier 2), UI language, versions, hub reachability (the `tau doctor` probe, 1 s, information only).
- `/model [role]` (`/rol`): without an argument the roles of `tau.toml` with the current one marked; with one, the agent is rebuilt on the **same** session with that role and `role` is written to the session's metadata. `/resume`, `tau chat --resume` and `tau tui --resume` honour the stored role unless `--role` / `build_app(role=...)` pinned one.

The command menu of the TUI grows to twelve rows and shows every row at 80x24.

## Acceptance criteria

- [x] `SLASH_COMMANDS` lists `compact`, `clear`, `status`, `model` with their aliases and help keys; `help_lines` and the unknown-command hint include them; `/exit` stays an alias of `/quit`
- [x] Every new chrome string has an `en` and a natural `tr` template in `tau_core.i18n` (TUI-only wording in `tau_tui/strings.py`, no collisions)
- [x] `/clear` in the terminal emits `\x1b[2J\x1b[H` and the ready banner; in the TUI the transcript is empty except the notice, the session and agent are unchanged, and it is refused while busy
- [x] `summarize` uses the agent's model over a copy of the history without tools and raises `CompactionError` for an empty history, a failed call or an empty reply; `seed_messages` has the documented shape; a seed survives a `FileSessionStore` round trip and `--resume`
- [x] `/compact` in both channels opens a new session seeded with the summary, links both sessions in their metadata, keeps the old session intact, prints the notice and the summary, and `/sessions` still lists compacted sessions
- [x] `/status` prints the documented lines in both languages and runs while busy in the TUI
- [x] `/model fast` switches the same session to the role, persists `meta.role`, updates the TUI header; `/model nope` and busy switches are refused; a failed build keeps the current agent; `/resume` and `--resume` pick the stored role up unless pinned
- [x] The TUI menu shows twelve rows with none hidden at 80x24 (scrolls in the `-short` band), `/co` completes to `/compact `, the menu snapshot is regenerated and free of local paths
- [x] READMEs, `CONTEXT.md` ("Compaction") and this issue updated; `uv run ruff check . && uv run ruff format . && uv run pytest -q` green

## Blocked by

None.

## Comments

- 2026-09-29: opened and done in one pass (uncommitted work of the session-commands wave). New modules `tau_core/compaction.py` and `tau_core/status.py`; `build_agent(seed_messages=...)` and `TauAgent.role`; terminal handlers in `channels/terminal.py`; TUI flows `TauApp.clear_screen`, `compact_session`, `switch_model` and `switch_session(role=...)`; `agent_factory(session_id, *, role, seed_messages)`; `CommandMenu` max-height 14 (border-box) with a `-short` cap. SDK facts relied on (strands-agents 1.57.1): `RepositorySessionManager.initialize` persists `agent.messages` of a new session on creation, `Agent.__init__` fires `AgentInitializedEvent` synchronously, `callback_handler=None` is the null handler, `AgentResult.__str__` joins the text blocks, the default sliding window only trims at the end of an invocation. Tests: `packages/tau-core/tests/test_compaction.py`, `test_status.py`, `test_terminal_commands.py`; `packages/tau-tui/tests/test_commands.py`.
- 2026-09-29: review fixes, one regression test each. TUI compaction runs in a worker (`TauApp._run_compaction`, group `compact`): the chrome stays responsive, `✻ Summarizing…` busy row, Esc sets the SDK cancel signal (`summarize(cancel_signal=...)` → `CompactionCancelled`). The summarizer sends the repair pair after a trailing `toolUse` too (`tau_core.agent.dangling` shared). `build_agent` records `role` in the session meta on every open and `record_compaction` copies it, so `/new` and `/compact` sessions resume on their role. A session recorded under another `[agent] context` raises `SessionContextMismatch` (a `ConfigError`) with one sentence in every path (`tau chat --session/--resume`, `tau tui --resume`, `/resume`, picker, sidebar); note added to `tau.toml`, the template and the README. The hub check never raises (`http.client` errors → `warn`). `resolve_model` tags instances with `tau_provider`/`tau_fallback_of`, so entry-point providers report correctly. Nits: `/clear` has its own busy toast, the README's `/model` wording matches the build-then-close order, `TauAgent.carry_over` keeps the pending repair across `/model`, `record_compaction` writes the old session first so the new one stays newest in `/sessions`.
