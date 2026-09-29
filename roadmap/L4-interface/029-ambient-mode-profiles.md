# 029 · Ambient mode: off by default, switchable profiles

Status: ready-for-agent
Type: AFK
Layer: L4 · Interface
Packages: tau-core, apps/taubar
Blocked by: 011, 019, 025

## What to build

Ambient mode is off by default. The user switches it on or off, or picks a profile (home / travel / sport), with `/ambient` on Telegram or from TauBar. When on, events are pre-filtered by rules and triaged by the `fast` role ("worth notifying?"); worthwhile ones become a short notification. Each profile defines the events it listens to, the notification channel, its own daily budget and an optional morning brief.

## Acceptance criteria

- [ ] Ambient off → events cause no LLM calls (verified via spend)
- [ ] `/ambient travel` switches the profile and TauBar reflects it
- [ ] Triage uses the `fast` role with its own budget key; exhausting it turns ambient off with a notification
- [ ] Profiles are settings; editing them needs no code change
- [ ] The startup status report and routines keep working regardless of ambient state

## Blocked by

- [011 · Hard budgets per role with graceful degradation](../L2-models/011-hard-budgets.md)
- [019 · Settings as data with live reload and `/settings`](../L3-cloud/019-settings-as-data.md)
- [025 · TauBar status panel: hub, nodes, spend, approvals](025-taubar-status-panel.md)

## Comments

- 2026-09-29: profile names are `home` / `travel` / `sport` (renamed by 062; the old `ev`/`seyahat`/`spor` values are not accepted).
