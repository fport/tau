# 017 · Tier-2 approvals with Telegram inline buttons

Status: ready-for-agent
Type: AFK
Layer: L3 · Cloud
Packages: cloud/tau-cloud, tau-core
Blocked by: 006, 014

## What to build

Implement the approval interface for Telegram. A tier-2 call sends a message with inline "✅ Approve / ❌ Reject" buttons (labels from the message table, so the UI language applies) showing tool, arguments and effect; the button callback resolves the pending call on the hub. Unanswered approvals time out as rejected.

## Acceptance criteria

- [ ] A tier-2 call from a Telegram conversation shows inline buttons with tool, arguments and effect
- [ ] Approve runs the tool; reject or timeout returns a clean refusal
- [ ] Callbacks from non-allowlisted users are ignored
- [ ] Every decision is recorded in the session

## Blocked by

- [006 · Tool permission tiers with approval and a loop guard](../L1-agent/006-tool-permission-tiers.md)
- [014 · Telegram relay tracer bullet: webhook → Worker → Durable Object → hub → reply](014-telegram-relay-tracer-bullet.md)

## Comments
