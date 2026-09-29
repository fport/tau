# 061 · Verify `tau tui` from the phone over mosh (Termius)

Status: done
Type: HITL
Layer: L1 · Agent
Packages: tau-tui
Blocked by: none

## What to build

Issue #008 checked the TUI at 80x24 and at 50 columns in a local pseudo-terminal, but nobody has used it from the phone yet. Open the Termius session (`tau-attach`, see `infra/remote/README.md`), run `uv run tau tui` inside tmux over mosh, and try the whole flow with the fake provider or real credentials.

## Acceptance criteria

- [x] Header, chat pane, event pane and input are all readable in portrait on the phone
- [x] A reply streams into the chat pane and its tool calls appear in the event pane
- [x] A tier-2 approval dialog can be answered with `e` / `h` from the phone keyboard
- [x] Ctrl+Q (or `/quit`) exits cleanly and the tmux window survives
- [x] Any surprise is recorded under `## Comments` of #008 or as a new issue

## Blocked by

None - needs the user's phone.

## Comments

- 2026-09-29: opened while closing the L1 wave; the "in Termius on a phone over mosh" half of #008's first criterion was verified only in a local 80x24 and 50-column pseudo-terminal.
- 2026-09-29: first run from the phone. Two surprises, both fixed or documented: (1) `tau tui` started a stale `uv tool install` (tau-core/tau-tui 0.2.0 in `~/.local/bin`, first on `PATH`) instead of the checkout; `uv run tau tui` runs the checkout, and the phone guide's troubleshooting now says so. (2) The TUI was black and white: `tau.tmux.conf` forced `RGB` for every `xterm-256color` client, and Termius over mosh drops 24-bit colour escapes (256 colours come through; `TEXTUAL_COLOR_SYSTEM=256` brought the colours back). The override is gone, so tmux maps to 256 colours for the phone; the guide has a troubleshooting entry. The remaining criteria are still open.
- 2026-09-29: done. The user ran `uv run tau tui` in Termius over mosh in portrait: the layout is readable, replies stream, the tier-2 dialog answers to `e` / `h` from the phone keyboard and `/quit` leaves the tmux window alive. The two surprises are recorded above (fix in 0d3da7b).
