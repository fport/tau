# 027 · Claude Code "waiting for you" notification on Telegram

Status: ready-for-agent
Type: AFK
Layer: L4 · Interface
Packages: tau-core
Blocked by: 014

## What to build

A Claude Code Notification hook posts an event to the hub's local API; the hub sends a short Telegram message ("Claude Code seni bekliyor — <repo>, <reason>") so the user can jump in through Termius. Rate-limited per session.

## Acceptance criteria

- [ ] The hook is documented and installable into the user's Claude Code settings
- [ ] Permission prompts and idle prompts both produce a message within seconds
- [ ] Rate limiting prevents spam and is configurable
- [ ] If the hub is down, the hook fails silently and does not block Claude Code

## Blocked by

- [014 · Telegram channel by direct polling: `getUpdates` loop on the hub → agent → reply](../L3-cloud/014-telegram-relay-tracer-bullet.md)

## Comments
- 2026-09-29: rewritten for ADR 0006 (private-first): unchanged in substance; the message goes out through the hub's own Telegram polling channel (014), not a relay.
