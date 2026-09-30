# 147 · The docs site in English and Turkish

Status: done
Type: AFK
Layer: L9 · Cloud mode and the tau network
Packages: docs
Blocked by: none

## What to build

The docs site becomes bilingual through `mkdocs-static-i18n`, with the suffix layout: `page.md` is English and `page.tr.md` its Turkish twin. English is the default and the fallback, and a language switcher sits in the header.

These pages get Turkish twins: `index.md`, every page of `getting-started/` and `guides/`, and `reference/cli.md` and `reference/tau-toml.md` where time allows. ADRs, issues and the other reference pages stay English, reached through the fallback. The site's nav labels are translated.

## Acceptance criteria

- [x] `mkdocs build --strict` passes with the plugin; `/tr/` serves the Turkish pages and falls back to English for untranslated ones
- [x] The Turkish pages are faithful to the English ones, with commands, paths and code unchanged
- [x] The docs dependency group has the plugin; CI's strict build keeps working

## Blocked by

None - can start immediately.

## Comments

- 2026-09-30: opened at the owner's request.
- 2026-09-30: done.
  - Commits: edb677c..3b8ce9e (plugin, nav translations, 27 Turkish twins); e6f0b96 relocks with mkdocs-static-i18n 1.3.1.
  - Translated: the home page, all of getting-started and guides, and the cli, tau-toml, slash-commands and threat-model references. ADRs, the architecture page, contributing and the other reference pages fall back to English.
  - Checks: every section link in both languages resolves (headings that other pages link to keep their English link targets); code blocks and the verified markers are identical to English.
  - Search covers both languages in one index.
