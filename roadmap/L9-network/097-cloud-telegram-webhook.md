# 097 · Telegram in cloud mode through a webhook on the spine, so the container can sleep

Status: needs-triage
Type: AFK
Layer: L9 · Cloud mode and the tau network
Packages: cloud/spine, tau-cloud, tau-core
Blocked by: 094

## What to build

In cloud mode the Telegram poller runs inside the container, so the spine's cron keeps the container awake around the clock. That costs memory time all month. A webhook path would let the container sleep instead:

1. Telegram posts updates to the spine (`/telegram/<secret path>`, checked with `X-Telegram-Bot-Api-Secret-Token`).
2. The spine stores the update in D1 and wakes the container.
3. The container's Telegram channel reads updates from the spine instead of `getUpdates`, through the same code path and a different source.

ADR 0006 §2 forbids a webhook in local mode. This path exists only in cloud mode, where the spine already hosts the brain.

## Acceptance criteria

- [ ] With the webhook on, `KEEP_AWAKE=0` works: a message wakes the container and gets an answer
- [ ] Inline-button approvals still work, and only from allowlisted chats
- [ ] Local mode is unchanged (direct polling, no webhook)

## Blocked by

- [094 · tau-cloud](094-tau-cloud.md)

## Comments

- 2026-09-30: filed with ADR 0007.
