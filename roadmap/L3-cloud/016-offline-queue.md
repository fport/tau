# 016 · Offline queue: "tau is offline" reply and flush on reconnect

Status: ready-for-agent
Type: AFK
Layer: L3 · Cloud
Packages: cloud/tau-cloud
Blocked by: 014

## What to build

If no hub is connected, the relay answers once per burst that tau is offline (Turkish, Jarvis tone) and queues the messages durably. When the hub reconnects, queued messages are delivered in order and answered.

## Acceptance criteria

- [ ] Hub stopped → a Telegram message gets the offline reply
- [ ] Hub started → queued messages are processed in order
- [ ] The queue survives Durable Object eviction
- [ ] Reconnects never process a message twice

## Blocked by

- [014 · Telegram relay tracer bullet: webhook → Worker → Durable Object → hub → reply](014-telegram-relay-tracer-bullet.md)

## Comments
