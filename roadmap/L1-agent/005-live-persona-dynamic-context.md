# 005 · Live persona files and dynamic context in the system prompt

Status: done
Type: AFK
Layer: L1 · Agent
Packages: tau-core
Blocked by: 004

## What to build

The system prompt is assembled on every turn from `persona/persona.md`, `persona/user.md` and a dynamic context block: current time (Europe/Istanbul), active profile, live nodes and today's budget. Sources whose layer does not exist yet are shown as unknown. Editing a persona file takes effect on the next turn without a restart.

## Acceptance criteria

- [x] Editing `persona.md` mid-conversation changes the next reply without restart
- [x] Dynamic context shows time, active profile, and explicit "unknown" for sources not yet available
- [x] Persona encodes the Jarvis rules: Turkish, polite, dry humor, ≤2 sentences for notifications and voice, no jokes in approval requests
- [x] Unit tests cover prompt assembly and reload

## Blocked by

- [004 · Tracer bullet: `tau chat` answers in the Jarvis persona](004-tau-chat-tracer-bullet.md)

## Comments

### 2026-09-29 · done (agent)

Finalized the persona on top of the 004 code. `uv run ruff format --check . && uv run ruff check . && uv run pytest -q` is green (118 tests, 48 of them in `tests/test_persona.py`, all offline). A scripted `tau chat` with the fake provider and the tracked `persona.md` + `user.example.md` copied into a temporary `TAU_HOME` starts and answers.

Criteria notes: the mid-conversation edit is verified through `build_agent` + `FakeModel` (a reply that echoes the first prompt line changes after `persona.md` is edited, on the same agent and history), and also inside one turn (an edit during a tool loop reaches the next model call). "Unknown" is rendered as `bilinmiyor`; an empty node list is `yok`. The Jarvis rules are checked phrase by phrase against the tracked `persona.md`.

Commits:
- `docs(roadmap): start 005`
- `feat(core): keep the last good persona and merge context sources safely`
- `feat(core): finalize the Jarvis persona and the user.md template`
- `test(core): cover prompt assembly, persona reload and dynamic context`
- `docs(core): document the persona and refine ADR 0004`
- `docs(roadmap): close 005`

Additions beyond the shared brief (§7 signatures unchanged):
- HTML comments (`<!-- ... -->`) in persona files are stripped before the model sees them; `user.example.md` keeps its copy instructions in one, so a copied `user.md` does not tell the model its facts are examples. Files are read as UTF-8 with an optional BOM.
- An empty `user.md` counts as missing (`user=None`, "siz"). An empty or undecodable `persona.md` on the first read raises `ConfigError` (`Persona dosyası boş: …` / `Persona dosyası okunamadı: …`) like a missing one; later the last good `persona.md`/`user.md` is kept. `PersonaHook` keeps the previous prompt if assembly raises.
- Context source output is normalized: unknown keys ignored, `None` = unknown, `nodes` coerced to `list[str]` (a bare string becomes one node), `budget` to `str`; a source that raises or returns a non-mapping is skipped. Every such problem is logged once until it clears (the terminal shows warnings).
- `TIMEZONE` falls back to a fixed UTC+3 named `Europe/Istanbul` when tzdata is missing; a naive clock is taken as Istanbul time. `PersonaLoader.persona_path`/`user_path` properties exist.
- The commit footer is `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` (the session's own model), and bookkeeping commits use the `roadmap` scope as 004 did.

For the next issues:
- 011 (budgets): pass `build_agent(context_sources=[lambda: {"budget": "<Turkish text>"}])`; the source runs before every model call, so return a cached value (no LiteLLM round trip per call). `None` renders `bilinmiyor`.
- 032/033 (nodes): same with `{"nodes": [...]}`; `[]` renders `yok`, which the model reads differently from `bilinmiyor`.
- Voice (026, 031) and notifications: the "≤2 sentences" rule needs the model to know the channel, which is not in the dynamic context yet (`build_agent` gets `channel` but does not pass it to `default_context_factory`). Proposed as a follow-up issue.
- ruff 0.16 also formats fenced `python` blocks inside Markdown files (READMEs); run `uv run ruff format .` after editing a README section with code.
- `build_agent` reads `clock` for the session id too; tests with a ticking clock should pass `session_id=...`.
