# 154 · `tau init` asks for the provider key

Status: ready-for-agent
Type: AFK
Layer: L9 · Cloud mode and the tau network
Packages: tau-core
Blocked by: –

## What to build

[ADR 0013](../../docs/adr/0013-hosted-taus-handles-and-public-pages.md) §7. `tau init` on a machine without credentials asks for the provider (`anthropic` | `openai` | `gemini`), then the key with hidden input. It checks the key with one small request (`--no-check` skips it) and writes it to `<home>/.env`, created with mode `0600` or appended to without touching other lines. `--yes` keeps today's behaviour (ask nothing, fall back to `fake`). The key never appears in output, argv or logs.

## Acceptance criteria

- [ ] Interactive run without credentials: provider prompt, hidden key prompt, check, `.env` written `0600`, `tau.toml` roles use that provider
- [ ] An existing `<NAME>_API_KEY` in `.env` is kept; a new one is appended; nothing else in `.env` changes
- [ ] `--no-check` skips the request; a failed check explains itself and writes nothing
- [ ] Tests with a fake prompt and a fake checker; no network; the i18n table has the prompt texts (en, tr)
- [ ] `docs/getting-started` and `docs/reference/cli.md` (+ `.tr.md` twins) show the new first run

## Blocked by

None.

## Comments

- 2026-09-30: filed with ADR 0013.
