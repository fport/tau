# 019 · Settings as data with live reload and `/settings`

Status: ready-for-agent
Type: AFK
Layer: L3 · Cloud
Packages: cloud/tau-cloud, tau-core
Blocked by: 014

## What to build

Runtime settings — active profile, ambient configuration, budgets, retention, notification preferences — live in a D1 table. Changes are pushed to the hub through the relay and applied without restart. `/settings` on Telegram shows and changes them.

## Acceptance criteria

- [ ] `/settings` lists settings; a change takes effect on the hub within seconds
- [ ] Settings are validated against a schema; invalid values are rejected with an explanation in the UI language
- [ ] The hub keeps working with cached settings while offline
- [ ] Every change is recorded in an audit trail

## Blocked by

- [014 · Telegram relay tracer bullet: webhook → Worker → Durable Object → hub → reply](014-telegram-relay-tracer-bullet.md)

## Comments

- 2026-09-29: reworded `/ayar` → `/settings` (Turkish alias `/ayar` stays accepted, see 062).
