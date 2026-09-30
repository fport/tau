# 147 · The docs site in English and Turkish

Status: in-progress
Type: AFK
Layer: L9 · Cloud mode and the tau network
Packages: docs
Blocked by: none

## What to build

The docs site becomes bilingual through `mkdocs-static-i18n`, with the suffix layout: `page.md` is English and `page.tr.md` its Turkish twin. English is the default and the fallback, and a language switcher sits in the header.

These pages get Turkish twins: `index.md`, every page of `getting-started/` and `guides/`, and `reference/cli.md` and `reference/tau-toml.md` where time allows. ADRs, issues and the other reference pages stay English, reached through the fallback. The site's nav labels are translated.

## Acceptance criteria

- [ ] `mkdocs build --strict` passes with the plugin; `/tr/` serves the Turkish pages and falls back to English for untranslated ones
- [ ] The Turkish pages are faithful to the English ones, with commands, paths and code unchanged
- [ ] The docs dependency group has the plugin; CI's strict build keeps working

## Blocked by

None - can start immediately.

## Comments

- 2026-09-30: opened at the owner's request.
