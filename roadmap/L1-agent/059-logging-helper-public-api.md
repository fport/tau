# 059 · Export a logging helper from tau-core's public API

Status: in-progress
Type: AFK
Layer: L1 · Agent
Packages: tau-core, tau-tui
Blocked by: none

## What to build

Channels outside tau-core (tau-tui now, Telegram and voice later) need the same log file (`<data_dir>/logs/tau.log`) that `tau chat` uses. Today the only helper is `tau_core.logs.configure_logging`, which is not re-exported from `tau_core`, so tau-tui re-implements a `FileHandler` in `tau_tui.cli.file_logging` and hardcodes `tau.log`.

Add `configure_logging` (or a small context manager that also removes its handlers) to `tau_core.__all__`, document it in the tau-core README, then switch tau-tui to it and mute the stderr handler while a full-screen UI owns the terminal.

## Acceptance criteria

- [ ] A logging helper is part of `tau_core.__all__` and documented in the tau-core README
- [ ] tau-tui uses it; `tau_tui.cli.file_logging` and the hardcoded file name are gone
- [ ] While the TUI runs nothing is written to stderr; the file log still receives records
- [ ] Tests in both packages

## Blocked by

None - can start immediately.

## Comments

- 2026-09-29: proposed by the agent that closed #008.
- 2026-09-29: absorbed by 063 (premium TUI), closed when 063 closes. 063 uses tau-core's logging helper if it is exported by then; otherwise it keeps the local one and this issue stays open under 063's note.
