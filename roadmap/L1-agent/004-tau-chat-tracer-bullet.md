# 004 · Tracer bullet: `tau chat` answers in the Jarvis persona

Status: done
Type: AFK
Layer: L1 · Agent
Packages: tau-core
Blocked by: none

## What to build

The thinnest end-to-end path through the agent. `tau chat` starts a REPL; each message goes through `build_agent(profile)` built on Strands Agents; the system prompt comes from the persona files; the model is resolved from the `brain` role through config; the reply comes back in Turkish in the Jarvis persona. This slice also establishes the uv workspace, the first independently publishable package (`tau-core`, import `tau_core`), the `tau` CLI entry point, the `tau.tools` entry-point group for plugins, a fake model for tests, and CI.

## Acceptance criteria

- [x] `uv run tau chat` holds a multi-turn conversation in Turkish
- [x] Without credentials it exits with a clear Turkish message naming the missing variables
- [x] Roles map to provider + model id in a config file; no model id is hardcoded in code
- [x] Bedrock and Anthropic are selectable by config only
- [x] `build_agent(profile)` has no hub-specific assumptions and runs in isolation
- [x] A tool shipped by another installed distribution is discovered through the `tau.tools` entry point (test plugin)
- [x] `uv build` produces a standalone `tau-core` wheel with its own README and version
- [x] Tests run offline with a fake model; GitHub Actions runs lint and tests
- [x] Commands in `CLAUDE.md` updated

## Blocked by

None - can start immediately

## Notes

Do not add `litellm` as a Python dependency — the proxy arrives in #010 as a container.

## Comments

### 2026-09-29 · done (agent)

Built the uv workspace (Python 3.12, `uv.lock` committed), `tau-core` 0.1.0 and a `tau-tui` skeleton, CI, ADRs 0001-0004 and the docs updates. `uv sync --all-packages --group dev && uv run ruff check . && uv run ruff format --check . && uv run pytest -q` is green (70 tests, offline); `uv build --package tau-core` gives a wheel whose METADATA carries the README and version 0.1.0.

Criteria notes: the multi-turn Turkish conversation is verified offline with the `fake` provider (CLI tests drive a scripted two-turn chat and a tier-2 approval through stdin); a live Bedrock/Anthropic run waits for the credentials of 003. The CI workflow is written and was replayed locally in a clean clone; it has not run on GitHub yet (nothing pushed).

Commits:
- `docs(roadmap): start 004`
- `chore: set up the uv workspace, CI and ignores`
- `feat(core): add config, model roles, tiers, persona and session base`
- `feat(core): add build_agent, TauAgent streaming and tool plugins`
- `feat(core): add the tau CLI and the terminal chat channel`
- `feat(tui): add the tau-tui package skeleton`
- `docs: add ADRs 0001-0004, glossary terms and Python commands`
- `fix(core): give tau-core commands Turkish help option text`
- `docs: show the uv commands for the first agent slice in the README`
- `docs(roadmap): close 004`

Deviations from the shared brief: `Decision` is a `StrEnum` (same values, still a `str`); ruff excludes `docs/` and `roadmap/` (pre-existing standalone scripts); pytest uses `--import-mode=importlib` so test files in different packages may share names; the missing-credentials message puts `Örnek isimler .env.example dosyasında.` on its own line; the role's Strands `agent_id` is `"tau"`; after a model error `TauAgent` appends the notice as an assistant message so the history stays user/assistant alternating (persisted through `MessageAddedEvent`).

For the next issues:
- 005: `persona.py` already works (mtime+size reload, dynamic block, `default_context_factory`, `ContextSource`); `persona/persona.md` is a first Jarvis draft. `PersonaLoader.read()` raises `ConfigError` when `persona.md` is missing on first read; `build_agent` builds the first system prompt eagerly so a missing persona fails at startup.
- 006: `TierGate`/`TierHook`/`TerminalApprover` live in `approval.py`; `AutoRejectApprover` is there too (re-exported by `tau_core.testing`). The gate serializes approval prompts with an `asyncio.Lock`, fails closed on unknown tools (`error` event, `where="tier_gate"`), on approver exceptions and on failing exemptions. The `approval` event's `channel` is `approver.name`; `ApprovalRequest.channel` is the conversation channel. `TerminalApprover(input_func=...)` has a `pending` flag the REPL uses to exit without hanging on Ctrl-C. Add `timeout_seconds` in `TierGate.check`. `test_agent.py::test_loop_guard` already covers the guard once.
- 007: implement `sessions/file.py`, register `"file"` in `SESSION_BACKENDS` (and drop it from `PLANNED_BACKENDS`), flip `tau.toml`. Fill only `cmd_devam`/`cmd_yeni`/`cmd_oturum` in `channels/terminal.py`; call `state.agent.close()` before replacing `state.agent` (it unsubscribes the old store sink). `ReplState` also has `role` and `running`. Messages live under agent id `tau` (`AGENT_ID` in `agent.py`); `SessionStore.event_sink` ignores events stamped with another session id; `MemorySessionStore` is the reference implementation.
- 008: `build_agent(events=bus, approver=..., channel="tui", clock=..., session_id=...)`; `TauAgent.stream()` yields the TurnEvents; the event pane subscribes to the same `EventBus`. `test_config(tmp_path)` writes `tmp_path/home` and `tmp_path/data`. The `fake` provider accepts scripted replies in `tau.toml` (`[models.roles.brain.params] replies = ["...", { tool = "name", input = {...} }]`). Global `--home`/`--profile` reach every subcommand as `TAU_HOME`/`TAU_PROFILE`.
- 009: `hub/cli.py` is a placeholder group (`run|status|stop|install|uninstall|systemd-unit`) using `tau_core.cli.help_option()`. `Config.hub`, `hub_dir` and `logs_dir` exist; `tau_core.logs.configure_logging(logs_dir, verbose=...)` routes logs to `<data_dir>/logs/tau.log` with terminal warnings only. `python -m tau_core` works for launchd's `ProgramArguments`.

- 2026-09-29: first GitHub Actions run on `main` is green (run 36549651048) after pinning `astral-sh/setup-uv` to `v10.2.0`; no floating `v10` tag exists.
