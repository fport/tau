# 013 · Create the Telegram bot and record the allowed chat id

Status: done
Type: HITL
Layer: L3 · Access and data
Packages: -
Blocked by: none

## What to build

The Telegram identity the private-first topology needs (ADR 0006): a bot the hub polls directly (014) and the allowlist of chats it answers. The Cloudflare token and the backup bucket moved to 081.

Steps for the user:

1. Telegram: create the bot with BotFather (`/newbot`) and store the token as `TELEGRAM_BOT_TOKEN` in the local `.env`. Leave privacy mode on; the bot only needs direct messages.
2. Find your own `chat_id` (send the bot a message, then open `https://api.telegram.org/bot<token>/getUpdates`, or ask `@userinfobot`) and store it as `TELEGRAM_ALLOWED_CHAT_IDS` (comma-separated; one id for now).
3. Add both variable names with an example value to `.env.example`; real values stay in the gitignored `.env`.

## Acceptance criteria

- [x] Telegram bot created with BotFather; `TELEGRAM_BOT_TOKEN` in the local `.env`
- [x] The user's own `chat_id` recorded as `TELEGRAM_ALLOWED_CHAT_IDS`
- [x] `.env.example` lists both variable names with an example value; nothing real is committed

## Blocked by

None - can start immediately.

## Comments

- 2026-09-29: rewritten for ADR 0006 (private-first). Before: a token for Workers, Durable Objects, D1, R2, Vectorize, AI Search and Workers AI plus a `workers.dev` subdomain. Now: Tunnel, Access, zone DNS and R2 only; the bot is polled directly by the hub (014), so no webhook secret exists.
- 2026-09-29: Telegram half done. Bot created with BotFather, privacy mode left on and group joins disabled (`/setjoingroups`); `getMe` and `getWebhookInfo` confirm both and that no webhook is set. `TELEGRAM_BOT_TOKEN` and `TELEGRAM_ALLOWED_CHAT_IDS` (read from `getUpdates` after a `/start`) are in the local `.env`; their names with example values are in `.env.example` and the `tau init` template. The example `[component.telegram]` table in `tau.toml` now shows `poll_timeout_seconds` instead of a variable name 014 does not use. Still open: the Cloudflare token (step 3), the R2 bucket and its token (step 4) and their `.env.example` names. 014 only needs the Telegram half.
- 2026-09-29: split. The Cloudflare token and the R2 bucket (old steps 3 and 4 and their criteria) moved to 081; 013 is the Telegram half and is done, so 014 is unblocked. 018 and 076 point at 081 now. The file keeps its old slug so links stay stable.
