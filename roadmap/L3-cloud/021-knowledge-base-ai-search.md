# 021 · Knowledge base: markdown → R2 → AI Search with `kb_search`

Status: ready-for-agent
Type: AFK
Layer: L3 · Cloud
Packages: cloud/tau-cloud, tau-core
Blocked by: 014

## What to build

Markdown files from the KB source are synced to a private R2 bucket indexed by Cloudflare AI Search. A `kb_search` tool queries it through the Worker. tau can also write new KB notes as a tier-1 action.

## Acceptance criteria

- [ ] A new markdown file becomes searchable after the next index cycle
- [ ] `kb_search` returns snippets citing file and section
- [ ] The bucket is private; no public URLs
- [ ] Sync is a single idempotent command

## Blocked by

- [014 · Telegram relay tracer bullet: webhook → Worker → Durable Object → hub → reply](014-telegram-relay-tracer-bullet.md)

## Comments
