# 013 · Create the Telegram bot and a scoped Cloudflare API token

Status: ready-for-human
Type: HITL
Layer: L3 · Cloud
Packages: -
Blocked by: none

## What to build

Create the external identities the relay needs.

## Acceptance criteria

- [ ] Telegram bot created with BotFather; token stored in the local `.env`
- [ ] The user's Telegram `chat_id` recorded for the allowlist
- [ ] Cloudflare API token scoped to Workers, Durable Objects, D1, R2, Vectorize, AI Search and Workers AI (no global key)
- [ ] `workers.dev` subdomain chosen

## Blocked by

None - can start immediately

## Comments
