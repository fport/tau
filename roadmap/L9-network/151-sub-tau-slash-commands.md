# 151 · Sub-taus from `tau chat`, the TUI and Telegram: `/sub NAME …`

Status: needs-triage
Type: AFK
Layer: L9 · Cloud mode and the tau network
Packages: tau-core, tau-tui, tau-sub
Blocked by: 149

## What to build

A slash command that talks to a sub-tau from any channel, for example `/sub coach how was my week?`, or `/coach …` as a shortcut. It needs tau-core's command table and the channels. Approvals stay on the channel.

## Acceptance criteria

- [ ] `/sub NAME text` works in the terminal, the TUI and Telegram; the answer comes from the sub-tau's session

## Blocked by

- [149 · Sub-taus](149-sub-taus.md)

## Comments

- 2026-09-30: filed with ADR 0012.
