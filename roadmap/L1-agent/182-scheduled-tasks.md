# 182 · Scheduled tasks: agent turns on a clock with a tool allowlist and a per-run cap

Status: ready-for-agent
Type: AFK
Layer: L1 · Agent
Packages: tau-routines, tau-core
Blocked by: 181

## What to build

"Every morning at 08:00, summarise what happened overnight" runs as a turn with nobody present ([ADR 0015](../../docs/adr/0015-web-app-agentic-chat.md) §4).

**The model.**

- A task is `{id, name, trigger, prompt, role, tools, max_usd_per_run, notify, enabled, approved_hash}`.
  - It uses the same triggers as 181.
  - `role` is `brain` or `fast` (default `fast`).
  - `tools` is an allowlist, empty by default. Tier-2 tools cannot be allowlisted.
  - `max_usd_per_run` defaults to 0.10.
  - `notify` is a subset of `["app", "telegram"]`, default `["app"]`.
- Tasks live next to routines in `TAU_DATA_DIR/routines/`.
- They are managed through `tau task add|list|pause|resume|remove|log|run-now`, the `schedule_task` tool (tier 2) and the app (184).

**Registration.** Registration is one tier-2 approval showing the full definition. Editing the prompt, role, tools, cap or trigger asks again, as in 181.

**A run.**

- `build_agent` is called with `channel="schedule"` and `guard=None`, the second new entry in the repo rule's allowlist. It also gets the task's tool allowlist and the `RefusingApprover` with a note: "Tier-2 actions do not run inside scheduled tasks; register a routine instead."
- Every run opens a new session with `task_id` and `run` in its metadata.
- A hook checks the run's spend after every model call and stops the turn with a notice when `max_usd_per_run` is reached. The role's own budget and `degrade_to` apply as for any call.
- The final reply is the run's result:
  - with `app` in `notify`, it lands in the web app's inbox, sessions with channel `schedule`;
  - with `telegram`, it is sent through the Telegram service when it runs.
- A run that finds the previous run still going is skipped and logged.

**`run-now`.** It runs a task immediately with the same rules, for testing a new task.

## Acceptance criteria

- [ ] A registered task runs at its time as a new `schedule` session with its own prompt, role and allowlisted tools only (test with `FakeModel` and a fake clock)
- [ ] A tier-2 call inside a run is refused with the note; no approval prompt appears anywhere
- [ ] A run stops at `max_usd_per_run` with a notice; spend is recorded against the role
- [ ] Editing the prompt re-asks for approval; allowlisting a tier-2 tool is refused at registration
- [ ] The repo rule allows `guard=None` in exactly the scheduled-turn file; `test_repo_rules.py` passes
- [ ] The result reaches Telegram when asked (fake Telegram API) and shows under the `schedule` channel in `/api/sessions`

## Blocked by

- [181 · Routines on a clock](../L5-mesh/181-routines-on-a-clock.md)

## Comments

- 2026-10-01: filed with ADR 0015. 047 (the overnight queue) builds on this. Waiting for the owner's approval on a tier-2 step instead of refusing it is 188.
