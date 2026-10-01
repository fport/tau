# 068 · Interrupt-based tier-2 approvals for out-of-process channels

Status: needs-triage
Type: AFK
Layer: L3 · Access and data
Packages: tau-core
Blocked by: 017

## What to build

Today a tier-2 approval blocks inside `TierHook` while an in-process `Approver` (terminal, TUI) answers. For channels where the answer arrives later and possibly from another process (Telegram buttons in 017, TauBar, a hub restart in between), the Strands SDK offers a cleaner mechanism: `BeforeToolCallEvent.interrupt(name, reason=...)` stops the event loop with `stop_reason == "interrupt"`, the pending interrupts are exposed on the result, and the next `stream_async([{"interruptResponse": {"interruptId": ..., "response": ...}}])` resumes exactly where the tool call was; the interrupt state is persisted by `RepositorySessionManager`, so it survives a hub restart.

Move the out-of-process approval path onto this mechanism: `TierHook` raises an interrupt instead of awaiting when the active `Approver` declares itself asynchronous; the channel (the Telegram polling loop of 014, TauBar in 025, the web UI in 074) stores the interrupt id with the pending request, and the button callback resumes the agent with the response. 064 already makes tau refuse unknown interrupts safely; this issue makes approvals use them on purpose. The in-process approvers keep their blocking behaviour.

## Acceptance criteria

- [ ] An asynchronous `Approver` makes `TierHook` interrupt the turn; `TauAgent.stream()` ends with `TurnEnd(stop_reason="interrupt")` and exposes the pending approval (tool, arguments, effect, interrupt id)
- [ ] Resuming with an approve response runs the tool once; a reject response returns the tier gate's refusal text; a timeout resumes as rejected
- [ ] A hub restart between the interrupt and the answer does not lose the pending approval (session store round-trip test)
- [ ] Terminal and TUI approvers are unchanged; tier 2 is still never auto-approved, in code or in tests
- [ ] 017's Telegram buttons use this path; every decision is recorded in the session

## Blocked by

- [017 · Tier-2 approvals with Telegram inline buttons](017-telegram-approvals.md)

## Comments

- 2026-09-29: filed as a follow-up of the Strands-correctness pass (064). SDK mechanism (strands-agents 1.57.1): `BeforeToolCallEvent.interrupt` + `interruptResponse` resume; state persisted by `RepositorySessionManager`.
- 2026-09-29: rewritten for ADR 0006 (private-first): the out-of-process channels are the hub's own Telegram polling loop (014), TauBar (025) and the web UI (074); no relay or Worker holds a pending approval. Packages narrowed to tau-core; the spec is otherwise unchanged and still waits for triage.
- 2026-10-01: the web UI is now tau-web's in-hub `WebApprover` (178). Its approval is awaited inside the hub, not in another process. Paused tier-2 steps in scheduled tasks (188) are the next out-of-process case.
