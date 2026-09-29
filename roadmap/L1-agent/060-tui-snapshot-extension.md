# 060 · Pin or fix the snapshot file extension for tau-tui snapshots

Status: done
Type: AFK
Layer: L1 · Agent
Packages: tau-tui
Blocked by: none

## What to build

pytest-textual-snapshot 1.0.0 with syrupy 6.x writes snapshots as `.raw` instead of `.svg` (it sets `_file_extension`, which syrupy 6 no longer reads). tau-tui commits `tests/__snapshots__/test_app/test_empty_app_snapshot.raw`, and the test globs `test_empty_app_snapshot.*` to cope.

Either pin syrupy/pytest-textual-snapshot to a combination that writes `.svg`, or accept `.raw`, and document the choice. If an upgrade switches the extension, re-run `uv run pytest packages/tau-tui --snapshot-update` and delete the stale file.

## Acceptance criteria

- [x] Exactly one snapshot file per snapshot test, with the chosen extension, and the test no longer needs a glob
- [x] The choice and the re-generation command are in `packages/tau-tui/README.md`
- [x] The snapshot contains no home-directory or temp-directory paths (existing check kept)

## Blocked by

None - can start immediately.

## Comments

- 2026-09-29: proposed by the agent that closed #008.
- 2026-09-29: absorbed by 063 (premium TUI), closed when 063 closes. Decision: keep `.raw`, pin the extension (no glob), note the choice and the re-generation command in the tau-tui README.
- 2026-09-29: done inside 063: `.raw` kept and pinned in `packages/tau-tui/tests/test_snapshots.py` (seven snapshots, one file each, no glob; the old `test_app` snapshot was deleted), README section "Development" documents the choice and `--snapshot-update`.
- 2026-09-29: twelve snapshots now (welcome 80x24/50x24/tr, chat, busy, approval, menu, picker, wide, ultra, events 50x24, short 80x18), each checked for the fixed session id and the absence of home/temp paths; README lists them.
- 2026-09-29: three snapshots regenerated after the review fixes (chat: fence + rejected card; wide: busy chrome; ultra: fence), still one `.raw` per test, the session-id and no-path checks unchanged; README lists what each pins.
- 2026-09-29: done (orchestrator): shipped inside 063: `.raw` kept, one file per snapshot test without a glob, README documents `--snapshot-update` and the path check.
