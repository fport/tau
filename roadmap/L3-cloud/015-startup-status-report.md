# 015 · Hub startup status report on Telegram

Status: ready-for-agent
Type: AFK
Layer: L3 · Cloud
Packages: tau-core
Blocked by: 014

## What to build

When the hub starts, or restarts after a crash, it sends one status report to Telegram: which machine is the hub, restart reason, live nodes, today's spend per role, pending approvals. Sources whose layer does not exist yet show as n/a.

## Acceptance criteria

- [ ] Starting the hub produces exactly one status report
- [ ] After a crash the report includes the crash reason recorded by #009
- [ ] Missing sources render as n/a, not as errors
- [ ] Short, Turkish, Jarvis tone

## Blocked by

- [014 · Telegram relay tracer bullet: webhook → Worker → Durable Object → hub → reply](014-telegram-relay-tracer-bullet.md)

## Comments
