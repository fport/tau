# 061 · Verify `tau tui` from the phone over mosh (Termius)

Status: ready-for-human
Type: HITL
Layer: L1 · Agent
Packages: tau-tui
Blocked by: none

## What to build

Issue #008 checked the TUI at 80x24 and at 50 columns in a local pseudo-terminal, but nobody has used it from the phone yet. Open the Termius session (`tau-attach`, see `infra/remote/README.md`), run `uv run tau tui` inside tmux over mosh, and try the whole flow with the fake provider or real credentials.

## Acceptance criteria

- [ ] Header, chat pane, event pane and input are all readable in portrait on the phone
- [ ] A reply streams into the chat pane and its tool calls appear in the event pane
- [ ] A tier-2 approval dialog can be answered with `e` / `h` from the phone keyboard
- [ ] Ctrl+Q (or `/çık`) exits cleanly and the tmux window survives
- [ ] Any surprise is recorded under `## Comments` of #008 or as a new issue

## Blocked by

None - needs the user's phone.

## Comments

- 2026-09-29: opened while closing the L1 wave; the "in Termius on a phone over mosh" half of #008's first criterion was verified only in a local 80x24 and 50-column pseudo-terminal.
