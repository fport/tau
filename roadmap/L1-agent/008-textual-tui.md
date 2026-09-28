# 008 · Textual TUI with chat and live event pane

Status: ready-for-agent
Type: AFK
Layer: L1 · Agent
Packages: tau-tui
Blocked by: 004

## What to build

`tau tui` opens a Textual interface that is usable over SSH from Termius: a chat pane and a live event pane (tool calls with tier and approval result, errors). Tier-2 approvals appear as an in-TUI dialog.

## Acceptance criteria

- [ ] Usable at 80x24 and in Termius on a phone over mosh
- [ ] Replies stream into the chat pane; the event pane shows tool calls with tier and approval result
- [ ] Tier-2 approvals are handled inside the TUI
- [ ] `tau-tui` is its own distribution and uses only the public API of `tau-core`
- [ ] Tests use Textual's pilot/snapshot harness

## Blocked by

- [004 · Tracer bullet: `tau chat` answers in the Jarvis persona](004-tau-chat-tracer-bullet.md)

## Comments
