# 186 · Scheduled tasks for hosted taus on Durable Object alarms

Status: ready-for-agent
Type: AFK
Layer: L9 · Cloud mode and the tau network
Packages: cloud/host, apps/web
Blocked by: 182, 185

## What to build

Hosted and own-host taus get the scheduled tasks of 182, run by the `Tau` Durable Object ([ADR 0015](../../docs/adr/0015-web-app-agentic-chat.md) §7). They get no routines and no devices (ADR 0013).

**Storage.** A `tasks` table and a `task_runs` table in the `Tau` object. They hold the same fields as 182, except `notify`, which is `app` only.

**The alarm.**

- The existing alarm multiplexer runs the tasks. It already takes the minimum over approval expiry, thread TTL and the universe report, and it gains the next due task.
- After every run it computes the next firing again.
- Times follow the owner's time zone setting, which is new and defaults to UTC.

**Registration.** Registration is a tier-2 approval through the existing approval flow, with the full definition on the card. Editing asks again.

**A run.**

- A run is a headless turn with the task's prompt and role. Its tools are those hosted taus have that are tier 0 or 1, filtered by the task's allowlist. Tier 2 is refused with the same note as 182.
- It stops at `max_usd_per_run` and the monthly budget.
- The result is a new session, shown in the app's Inbox.

**The app.** The Tasks and Inbox pages of 184 work with the `host` backend.

## Acceptance criteria

- [ ] A task registered on a hosted tau runs at its time through the alarm and its result appears in the Inbox (workerd test with a fake clock and the fake provider)
- [ ] Approval expiry and the universe report still fire on time with tasks scheduled (test)
- [ ] Tier 2 is refused inside a run; the per-run cap and the monthly budget stop it
- [ ] Registration and edits go through the approval card

## Blocked by

- [182 · Scheduled tasks](../L1-agent/182-scheduled-tasks.md)
- [185 · tau-host runs the web app](185-tau-host-runs-the-web-app.md)

## Comments

- 2026-10-01: filed with ADR 0015.
