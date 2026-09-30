# 154 · `tau init` asks for the provider key

Status: done
Type: AFK
Layer: L9 · Cloud mode and the tau network
Packages: tau-core
Blocked by: –

## What to build

[ADR 0013](../../docs/adr/0013-hosted-taus-handles-and-public-pages.md) §7. `tau init` on a machine without credentials asks for the provider (`anthropic` | `openai` | `gemini`), then the key with hidden input. It checks the key with one small request (`--no-check` skips it) and writes it to `<home>/.env`, created with mode `0600` or appended to without touching other lines. `--yes` keeps today's behaviour (ask nothing, fall back to `fake`). The key never appears in output, argv or logs.

## Acceptance criteria

- [x] Interactive run without credentials: provider prompt, hidden key prompt, check, `.env` written `0600`, `tau.toml` roles use that provider
- [x] An existing `<NAME>_API_KEY` in `.env` is kept; a new one is appended; nothing else in `.env` changes
- [x] `--no-check` skips the request; a failed check explains itself and writes nothing
- [x] Tests with a fake prompt and a fake checker; no network; the i18n table has the prompt texts (en, tr)
- [x] `docs/getting-started` and `docs/reference/cli.md` (+ `.tr.md` twins) show the new first run

## Blocked by

None.

## Comments

- 2026-09-30: filed with ADR 0013.
- 2026-09-30: done. As built (`tau_core.builder`):
  - Order: an existing `tau.toml` without `--force` is refused before any question; the UI language is asked first (still the English "UI language" prompt), then, only when no credentials are in the environment or `<home>/.env`, the provider (`anthropic` | `openai` | `gemini`, default `anthropic`) and the key with hidden input, in that language (`init.*` keys of the message table, en + tr). Credentials that are found keep today's behaviour and message. `--provider anthropic|openai|gemini` without its key asks only the key; `bedrock` and `fake` never ask. `--yes` asks nothing (the old fake fallback).
  - An empty key skips: `tau.toml` is written for the provider and a notice names the variable to add. A key with whitespace, quotes or control characters is refused before the check.
  - `check_provider_key(provider, key, *, opener=None, timeout=10) -> KeyCheck(code, status, error)`: one `GET` of the model list (Anthropic `/v1/models?limit=1` with `x-api-key` and `anthropic-version`, OpenAI `/v1/models` with `Authorization: Bearer`, Gemini `/v1beta/models?pageSize=1` with `x-goog-api-key`); the key only in a header, redirects never followed. `code` is `ok`, `refused` (401/403), `http` or `unreachable`. It runs before `init_home`; a failure prints `init.key.refused|http|unreachable` on stderr, writes nothing and exits 1. `--no-check` skips it. Tests replace the checker through the click context object (`obj={"init_key_check": fake}`).
  - `write_env_key(home, name, value) -> bool`: a new `.env` is created `0600` (`O_CREAT|O_EXCL`); an existing one is set to `0600` first, then the line is appended (after a newline if missing) without touching other lines; an empty `NAME=` line is filled in place; a name with a value is kept (`False`, `init.key.kept`). Names: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`. The value never reaches output, logs or exception texts.
  - `init_home` is unchanged (the TUI setup screen still calls it); the key is written after it succeeds. Tests: `packages/tau-core/tests/test_init_key.py`.
