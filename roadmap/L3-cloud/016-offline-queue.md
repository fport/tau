# 016 · Offline queue: "tau is offline" reply and flush on reconnect

Status: wontfix
Type: AFK
Layer: L3 · Access and data
Packages: cloud/tau-cloud
Blocked by: 014

## What to build

If no hub is connected, the relay answers once per burst that tau is offline (in the UI language, Jarvis tone) and queues the messages durably. When the hub reconnects, queued messages are delivered in order and answered.

## Acceptance criteria

- [ ] Hub stopped → a Telegram message gets the offline reply
- [ ] Hub started → queued messages are processed in order
- [ ] The queue survives Durable Object eviction
- [ ] Reconnects never process a message twice

## Blocked by

- [014 · Telegram channel by direct polling: `getUpdates` loop on the hub → agent → reply](014-telegram-relay-tracer-bullet.md)

## Comments

- 2026-09-29: wontfix under ADR 0006 (private-first). There is no relay any more: the hub polls Telegram directly (014) and Telegram itself keeps undelivered updates for about a day, so nothing is lost while the hub is offline and the queue is unnecessary. The "tau is offline" auto-reply is dropped with it; if it is ever wanted, a tiny optional Worker that only answers while the hub is down (and holds no data) can be filed as a new issue. The body above is kept as history.
