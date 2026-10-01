# 184 · The app's control pages: routines, tasks, devices, the toolbox and sub-taus

Status: ready-for-agent
Type: AFK
Layer: L4 · Interface
Packages: apps/web, tau-web, tau-routines, tau-sub
Blocked by: 179, 181, 182, 183

## What to build

The pages that turn the chat into a control centre ([ADR 0015](../../docs/adr/0015-web-app-agentic-chat.md) §4–6). Each page appears only when `capabilities` reports its service.

**Routines.**

- A list of routines, each with its trigger in words, tool, arguments, next firing, last result and an enabled toggle.
- A form builds a new one: pick a trigger, then a tool from the catalog, then fill its arguments from the tool's input schema.
- Saving goes through the same tier-2 approval as every other path. The card appears in the page, and nothing is saved before Approve.
- The log shows fired, missed and failed firings.

**Tasks.** A list and a form (name, trigger, prompt, role, tool allowlist without tier 2, cap, notify), with the same approval on save. "Run now" and the run history link to each run's session.

**Inbox.** Results of scheduled tasks and routine failures, newest first. Unread items are marked.

**Devices.**

- One card per `DeviceSource` device, with a "simulated" badge where it applies and its state updating live.
- A switch on the card calls the device's tool without a model turn. The call goes through a `TierGate` with the web channel's guard and `WebApprover`, so tier 2 asks as always. It is recorded as a `tool_call` event in a `web` session titled "Devices". There is no side door around the gate.

**Toolbox.**

- The tool catalog: name, tier, description, package, and whether it is enabled.
- Enabling and disabling edits `[components] tools.disabled` through tau-core's config editor. The page says a change takes effect on the next session.
- Once 034 lands, pending tools tau wrote are listed here, and their approval card shows the full source.

**Sub-taus.**

- A list and editor for persona, about, role, tool allowlist, public, web, `web_daily` and starters, through tau-sub's public API. Allowlisting a tier-2 tool shows that each call will still ask.
- "Draft with the brain" uses `draft_sub`.
- Opening a sub-tau's chat starts a session on its channel (`sub:<name>`) in the web app.

## Acceptance criteria

- [ ] "Lamp on at 07:00 on weekdays" can be created from the Routines page with one approval and then fires (end-to-end test with a fake clock against a hub running tau-routines and tau-sim)
- [ ] A task created in the Tasks page runs on "Run now" and its result appears in the Inbox
- [ ] The desk lamp card switches the simulated lamp only after an approval; its state updates live
- [ ] Disabling a tool in the Toolbox removes it from the next session's `/tools`
- [ ] A sub-tau created and edited in the app is the same file `tau sub` sees; chatting with it runs its allowlist only
- [ ] Every page hides itself when its service is not installed; every string exists in `en` and `tr`

## Blocked by

- [179 · The web app](179-web-app-chat.md)
- [181 · Routines on a clock](../L5-mesh/181-routines-on-a-clock.md)
- [182 · Scheduled tasks](../L1-agent/182-scheduled-tasks.md)
- [183 · A simulated lamp](../L5-mesh/183-simulated-lamp.md)

## Comments

- 2026-10-01: filed with ADR 0015.
