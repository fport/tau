# 101 · Contact requests and network messages reach the owner in the TUI, TauBar and Telegram

Status: needs-triage
Type: AFK
Layer: L9 · Cloud mode and the tau network
Packages: tau-net, tau-core, tau-tui
Blocked by: 093

## What to build

tau-net logs contact requests and network exchanges. For now the owner sees them only through `tau net contacts` and `tau net log`. This issue brings them to the owner's channels:

- A contact request shows up as a notice with **Accept** / **Block**: Telegram inline buttons, a TUI dialog, later TauBar.
- A network exchange that ended in `[no reply]` ("needs your owner") is forwarded to the owner.

Accepting from a channel counts as a trusted decision only on the channels ADR 0006 §5 trusts.

## Acceptance criteria

- [ ] A contact request produces a Telegram message with Accept/Block buttons (allowlisted chats only); pressing Accept has the same effect as `tau net accept`
- [ ] The TUI shows pending requests and recent network exchanges
- [ ] A `[no reply]` network turn forwards the last incoming message to the owner

## Blocked by

- [093 · tau-net](093-tau-net.md)

## Comments

- 2026-09-30: filed with ADR 0007.
