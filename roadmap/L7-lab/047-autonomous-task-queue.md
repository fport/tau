# 047 · Autonomous overnight task queue with its own budget

Status: ready-for-agent
Type: AFK
Layer: L7 · Lab
Packages: tau-core
Blocked by: 011, 019

## What to build

The user queues a long-running task ("bu gece şunu araştır"); tau works on it autonomously within its own budget key and time window, saves results to KB/memory, and reports back in the morning.

## Acceptance criteria

- [ ] Tasks can be queued, listed and cancelled from Telegram
- [ ] The queue has its own budget key and stops when it is exhausted
- [ ] Results are saved and summarized in a report message

## Blocked by

- [011 · Hard budgets per role with graceful degradation](../L2-models/011-hard-budgets.md)
- [019 · Settings as local data with live reload and `/settings`](../L3-cloud/019-settings-as-data.md)

## Comments
- 2026-09-29: rewritten for ADR 0006 (private-first): results go to the local KB and memory (020/021); the queue's settings live in the local settings file (019).
- 2026-10-01: builds on the scheduled tasks of [182](../L1-agent/182-scheduled-tasks.md) ([ADR 0015](../../docs/adr/0015-web-app-agentic-chat.md) §4). A queued task is a one-off scheduled task with its own budget, and its report lands in the web app's inbox and on Telegram.
