# 172 · Telegram pairing without looking up a chat id

Status: ready-for-agent
Type: AFK
Layer: L4 · Interface
Packages: tau-core
Blocked by: 169

## What to build

[ADR 0014](../../docs/adr/0014-one-installer-and-onboarding.md) §5.

- `tau telegram pair` (and a `tau setup` step) takes the bot token at a hidden prompt, stores it in `.env` and shows a one-time code.
- The hub's Telegram service accepts that code from the first chat that sends it within 10 minutes, and stores that chat as the owner's.
- It then answers only there, as today.
- Other chats get nothing, as today.

## Acceptance criteria

- [ ] Pairing works end to end against a fake Bot API; wrong or expired codes are refused
- [ ] `docs/guides/telegram` (EN + TR) leads with pairing; the chat-id path stays as the manual way

## Comments

- 2026-10-01: filed with ADR 0014.
