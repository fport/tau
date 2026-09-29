# 086 · TauBar follows the UI language setting

Status: needs-triage
Type: AFK
Layer: L4 · Interface
Packages: apps/taubar, tau-core
Blocked by: 024

## What to build

TauBar's menu and window are English only. Every other channel takes its UI chrome from the `tau_core.i18n` message table (`[ui] language`, `TAU_LANG`), and CLAUDE.md forbids Turkish strings outside that table, so TauBar cannot simply grow a `tr` column of its own. Decide how TauBar gets its strings (for example an exported JSON of the table that TauBar bundles or reads from the tau checkout, or the hub's control API serving the table) and which language setting it follows.

## Acceptance criteria

- [ ] TauBar's menu and window show Turkish chrome when `[ui] language = "tr"` and English by default
- [ ] Every TauBar string lives in the `tau_core.i18n` table (or a file generated from it); none is hard-coded in Rust or TypeScript
- [ ] A missing key falls back to English instead of failing

## Blocked by

- [024 · TauBar v0: tray app with sleep modes](024-taubar-sleep-modes.md)

## Comments

- 2026-09-30: found while building 024 and 084, which ship English only.
