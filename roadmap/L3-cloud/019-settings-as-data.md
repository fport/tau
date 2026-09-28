# 019 · Settings as data with live reload and `/ayar`

Status: ready-for-agent
Type: AFK
Layer: L3 · Cloud
Packages: cloud/tau-cloud, tau-core
Blocked by: 014

## What to build

Runtime settings — active profile, ambient configuration, budgets, retention, notification preferences — live in a D1 table. Changes are pushed to the hub through the relay and applied without restart. `/ayar` on Telegram shows and changes them.

## Acceptance criteria

- [ ] `/ayar` lists settings; a change takes effect on the hub within seconds
- [ ] Settings are validated against a schema; invalid values are rejected with a Turkish explanation
- [ ] The hub keeps working with cached settings while offline
- [ ] Every change is recorded in an audit trail

## Blocked by

- [014 · Telegram relay tracer bullet: webhook → Worker → Durable Object → hub → reply](014-telegram-relay-tracer-bullet.md)

## Comments
