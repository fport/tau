# 006 · Tool permission tiers with approval and a loop guard

Status: ready-for-agent
Type: AFK
Layer: L1 · Agent
Packages: tau-core
Blocked by: 004

## What to build

Every tool declares a tier: 0 read, 1 digital write, 2 physical action or self-written code. Tier 0 runs freely, tier 1 runs and is logged, tier 2 waits for an approval through a channel-agnostic approval interface. The terminal channel implements it as a prompt showing tool, arguments and expected effect. A per-turn tool-iteration guard stops runaway loops. Leave a hook so registered routines (#037) can be exempt from per-call approval.

## Acceptance criteria

- [ ] A tool without a declared tier cannot be registered
- [ ] A tier-2 call in `tau chat` shows an approval prompt; rejecting returns a clean refusal to the model
- [ ] Every tier-1 and tier-2 call is logged with arguments, result summary and approval decision
- [ ] Approval is an interface that other channels (Telegram #017, TauBar #025) can implement
- [ ] The iteration guard is configurable; hitting it ends the turn with a Turkish explanation
- [ ] Tests cover each tier path and the guard

## Blocked by

- [004 · Tracer bullet: `tau chat` answers in the Jarvis persona](004-tau-chat-tracer-bullet.md)

## Comments
