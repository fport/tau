# 015 · Hub startup status report on Telegram

Status: ready-for-agent
Type: AFK
Layer: L3 · Access and data
Packages: tau-core
Blocked by: 014

## What to build

When the hub starts, or restarts after a crash, it sends one status report to the allowlisted Telegram chat through the polling channel (014): which machine is the hub, restart reason, live nodes, today's spend per role, pending approvals, last backup. Sources whose layer does not exist yet show as n/a.

## Acceptance criteria

- [ ] Starting the hub produces exactly one status report
- [ ] After a crash the report includes the crash reason recorded by #009
- [ ] Missing sources render as n/a, not as errors
- [ ] Short, in the UI language, Jarvis tone

## Blocked by

- [014 · Telegram channel by direct polling: `getUpdates` loop on the hub → agent → reply](014-telegram-relay-tracer-bullet.md)

## Comments

- 2026-09-29: rewritten for ADR 0006 (private-first): unchanged in substance, the report now goes out through the hub's own `sendMessage` call instead of the relay; "last backup" (018) added to the sources.
