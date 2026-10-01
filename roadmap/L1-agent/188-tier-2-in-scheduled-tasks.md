# 188 · Tier-2 steps in scheduled tasks wait for the owner's approval

Status: needs-triage
Type: AFK
Layer: L1 · Agent
Packages: tau-routines, tau-core
Blocked by: 182

## What to build

In 182, a tier-2 call inside a scheduled task is refused. Some tasks would be better if the step waited instead. An example: "at 22:00, if the forecast says rain, ask me whether to close the blinds".

Sketch:

- The run pauses on the tier-2 call. The approval reaches the owner on a trusted channel (the web app's approval card, Telegram's inline buttons) and expires after `[routines] task_approval_minutes`.
- The run resumes or is refused.
- This is the out-of-process approval path of 068.

Decide before building:

- whether the guard's step-up applies, given that the run itself opted out;
- how long a paused run may hold its session;
- what the model reads when the approval expires.

## Acceptance criteria

- [ ] Decision recorded (an ADR 0015 amendment or a new ADR); nothing is auto-approved and the tier-2 rule holds

## Blocked by

- [182 · Scheduled tasks](182-scheduled-tasks.md)

## Comments

- 2026-10-01: filed with ADR 0015. Related: 068 (interrupt-based approvals for out-of-process channels).
