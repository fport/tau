# 017 · Tier-2 approvals with Telegram inline buttons

Status: in-progress
Type: AFK
Layer: L3 · Access and data
Packages: tau-core
Blocked by: 006, 014

## What to build

The approval interface for Telegram, handled entirely by the hub's polling loop (014). A tier-2 call from a Telegram conversation sends a message with inline "Approve / Reject" buttons (labels from the message table, so the UI language applies) showing tool, arguments and effect; the `callback_query` arrives through the same `getUpdates` loop, is checked against the `chat_id` allowlist and resolves the pending call on the hub. Nothing sits between Telegram and the hub, so the button press is a first-party approval (ADR 0006 §5). Unanswered approvals time out as rejected, and the message is edited to show the outcome and lose its buttons.

First slice: an asynchronous `Approver` for the Telegram channel that awaits a future resolved by the callback inside the same hub process (the turn stays open while the user decides, bounded by the timeout). 068 moves this onto the Strands interrupt mechanism so a pending approval survives a hub restart; this issue leaves the seam ready for it (pending request id, tool, arguments, effect, expiry and the Telegram message id stored together).

## Acceptance criteria

- [ ] A tier-2 call from a Telegram conversation shows inline buttons with tool, arguments and effect
- [ ] Approve runs the tool once; reject or timeout returns the tier gate's refusal text; the message is edited to show the outcome
- [ ] Callbacks from non-allowlisted users, or for unknown or expired requests, are acknowledged with `answerCallbackQuery`, have no effect and are logged
- [ ] Every decision is recorded in the session as an agent event
- [ ] Tier 2 is never auto-approved, in code or in tests (fake Bot API plus the `tau_core.testing` fakes)

## Blocked by

- [006 · Tool permission tiers with approval and a loop guard](../L1-agent/006-tool-permission-tiers.md)
- [014 · Telegram channel by direct polling: `getUpdates` loop on the hub → agent → reply](014-telegram-relay-tracer-bullet.md)

## Comments

- 2026-09-29: rewritten for ADR 0006 (private-first): the callback is handled by the hub's own polling loop instead of a Worker/Durable Object, which is what makes the button a trusted approval; 068 is the restart-safe, interrupt-based follow-up.
