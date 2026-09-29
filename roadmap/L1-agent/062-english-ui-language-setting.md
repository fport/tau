# 062 · English UI with a per-installation language setting

Status: in-progress
Type: AFK
Layer: L1 · Agent
Packages: tau-core, tau-tui
Blocked by: none

## What to build

Every piece of UI chrome tau shows the user (slash commands, labels, pane titles, key hints, notices, the approval dialog, CLI help) is Turkish and hardcoded across the terminal channel, the TUI and the CLI. Make English the canonical language of the UI and route all chrome through one small message table with a per-installation language setting, so the terminal REPL and the TUI never drift and a Turkish UI stays one setting away.

- `tau_core.i18n`: `Language = Literal["en", "tr"]`, `LANGUAGES`, `DEFAULT_LANGUAGE = "en"`, `MESSAGES` (dotted, stable keys such as `chat.ready`, `chat.unknown_command`, `session.not_found`, `approval.title`, `tier.0`, `notice.turn_limit`, `tui.placeholder`), `t(key, language, /, **kwargs)` formatting with `str.format` (unknown key → `KeyError`; a language missing the key falls back to English), `register_messages(mapping)` for plugins.
- Config: `[ui] language = "en"` parsed into `UiConfig`, validated against `LANGUAGES` (`ConfigError` otherwise); env `TAU_LANG` wins over the file; `tau --lang tr ...` exports `TAU_LANG` like `--profile`; `/lang en|tr` switches for the current run only.
- `tau_core.commands`: `SlashCommand(name, aliases, argument, help_key)`, `SLASH_COMMANDS`, `resolve_command(line) -> (name, argument) | None` (casefold match after stripping `/`), `command_hint(language)`. Canonical names with Turkish aliases accepted forever but never shown in hints: `/help` (`/yardım`, `/yardim`, `/?`), `/tools` (`/araçlar`, `/araclar`), `/sessions` (`/oturumlar`), `/resume [n|id]` (`/devam`), `/new` (`/yeni`), `/session` (`/oturum`), `/lang en|tr` (`/dil`), `/quit` (`/çık`, `/cik`, `/exit`). `/resume` with no argument resumes the most recent earlier session without listing; `/sessions` prints the numbered listing. Handlers stay per channel; the two `_turkish_lower` helpers are deleted.
- Text the model reads is fixed English: system-prompt scaffolding (`## User`, `## Now`), dynamic-context labels (`Date and time`, `Profile`, `Host role`, `Live nodes`, `Budget today`), `unknown` / `none`, the no-user-file sentence, English weekday names, gate texts (`refusal_text`, `unknown_tool_text`), built-in tool descriptions and `effect` strings, test personas, the `FakeModel` default reply.
- Errors raised before `Config` exists (`ConfigError`, `MissingCredentials`, `InvalidSessionId`, `UntieredToolError`, hub lock / launchctl errors, control-API JSON errors, `tau hub status` lines) are plain English without lookup; every "The message is Turkish" docstring goes.
- Notices appended to history (`turn_limit_text`, `model_error_text`, and the max-tokens / cancelled / throttled / overflow notices from 064) go through the table using `config.ui.language`.
- Approval answers accept both languages regardless of setting: terminal `y`/`yes`/`e`/`evet` approve, anything else rejects; TUI keys `y` and `e` approve, `n`, `h` and Esc reject; the arming delay stays.
- Profile values renamed: `ev` → `home`, `seyahat` → `travel`, `spor` → `sport`; `DEFAULT_PROFILE = "home"`; `.env.example`, `CONTEXT.md`, docs and tests follow.
- Persona: `persona/persona.md` body stays Turkish but its language rule becomes adaptive (default Turkish, answer in the user's language, keep code and technical terms as they are) and its references to the prompt headings and the unknown marker use the English names; HTML comments in `persona.md` and `user.example.md` and the example facts in `user.example.md` become English.

## Acceptance criteria

- [ ] `tau_core.i18n` exists with `t`, `Language`, `LANGUAGES`, `DEFAULT_LANGUAGE`, `MESSAGES`, `register_messages`; an unknown key raises `KeyError`, a missing translation falls back to English; a test asserts every key has an `en` entry
- [ ] `Config.ui.language` is read from `[ui] language`, validated against `LANGUAGES`, overridden by `TAU_LANG`; `tau --lang tr` exports it; `/lang en|tr` switches the current run in both channels
- [ ] `tau_core.commands` exports `SlashCommand`, `SLASH_COMMANDS`, `resolve_command`, `command_hint`; both channels resolve commands through it; every Turkish alias in the table still works and never appears in hints
- [ ] Unknown command → `Unknown command: /{name}. Commands: /help, /tools, /sessions, /resume, /new, /session, /lang, /quit` (Turkish equivalent under `tr`)
- [ ] `/resume` without an argument resumes the most recent earlier session and says which; `/sessions` prints the numbered listing
- [ ] Every string the model reads (prompt headings, context labels, `unknown`/`none`, weekday names, gate texts, tool descriptions, effects, `FakeModel` default reply) is English, verified by tests on `FakeModel.calls[i].system_prompt`
- [ ] Pre-config errors and `tau hub status` output are plain English; no docstring says the message is Turkish
- [ ] Approval input accepts `y`/`yes`/`e`/`evet` in the terminal and `y`/`e` (approve), `n`/`h`/Esc (reject) in the TUI under both languages; the arming delay is unchanged
- [ ] Profiles are `home`/`travel`/`sport` everywhere (`DEFAULT_PROFILE`, `.env.example`, `CONTEXT.md`, package READMEs, tests); the old values are not accepted
- [ ] `persona/persona.md` carries the adaptive language rule and the English heading names; comments in `persona.md` and `user.example.md` are English
- [ ] Public API exports `t`, `Language`, `LANGUAGES`, `UiConfig` (via `Config`), `SlashCommand`, `SLASH_COMMANDS`, `resolve_command`, `command_hint`; `CONTEXT.md` gains "UI language" and "Slash command"
- [ ] `uv run pytest -q`, `uv run ruff check .` and `uv run ruff format --check .` are green

## Blocked by

None - can start immediately. 063 (premium TUI) and 064 (Strands pass) build on the message table and the command spec.

## Comments

- 2026-09-29: opened by the 2026-09-29 wave on the user's request (English UI, premium TUI, Strands audit, plug-and-play setup). Spec: wave decisions sections 1-3.
