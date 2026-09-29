# 059 · Export a logging helper from tau-core's public API

Status: done
Type: AFK
Layer: L1 · Agent
Packages: tau-core, tau-tui
Blocked by: none

## What to build

Channels outside tau-core (tau-tui now, Telegram and voice later) need the same log file (`<data_dir>/logs/tau.log`) that `tau chat` uses. Today the only helper is `tau_core.logs.configure_logging`, which is not re-exported from `tau_core`, so tau-tui re-implements a `FileHandler` in `tau_tui.cli.file_logging` and hardcodes `tau.log`.

Add `configure_logging` (or a small context manager that also removes its handlers) to `tau_core.__all__`, document it in the tau-core README, then switch tau-tui to it and mute the stderr handler while a full-screen UI owns the terminal.

## Acceptance criteria

- [x] A logging helper is part of `tau_core.__all__` and documented in the tau-core README
- [x] tau-tui uses it; `tau_tui.cli.file_logging` and the hardcoded file name are gone
- [x] While the TUI runs nothing is written to stderr; the file log still receives records
- [x] Tests in both packages

## Blocked by

None - can start immediately.

## Comments

- 2026-09-29: proposed by the agent that closed #008.
- 2026-09-29: absorbed by 063 (premium TUI), closed when 063 closes. 063 uses tau-core's logging helper if it is exported by then; otherwise it keeps the local one and this issue stays open under 063's note.
- 2026-09-29: tau-core side done by 065: `configure_logging(logs_dir, verbose=False, console=False|True)` and `reset_logging` are exported from `tau_core` and documented under README "Logging"; `console=False` keeps stderr silent for a full-screen UI while the file log still receives every record (`tests/test_logs.py`). The tau-tui criteria stay with 063.
- 2026-09-29: 063 kept the local `tau_tui.cli.file_logging` (it now also detaches the `tau` group's stderr handler while the UI runs, with a test). tau-core exported `configure_logging`/`reset_logging` in the same wave; switching tau-tui to them and removing the local helper is the remaining step.
- 2026-09-29: the CLI path is now covered end to end (`test_cli.py`: `TAU_LANG`/`--profile`/`--resume` reach `build_app`, the UI runs behind a stub, the log file under `<data_dir>/logs/tau.log` receives the records, an unwritable directory never raises). Switching to `tau_core.configure_logging` is still the remaining step.
- 2026-09-29: done (orchestrator): `configure_logging`/`reset_logging` exported from tau_core (065); tau_tui.cli now calls `configure_logging(logs_dir, console=False)` and the local `file_logging` is gone; tests in packages/tau-core/tests/test_logs.py and packages/tau-tui/tests/test_cli.py.
