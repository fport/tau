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
- [019 · Settings as data with live reload and `/ayar`](../L3-cloud/019-settings-as-data.md)

## Comments
