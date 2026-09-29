# 013 · Create the Telegram bot and a Cloudflare token scoped to Tunnel, Access and R2

Status: ready-for-human
Type: HITL
Layer: L3 · Access and data
Packages: -
Blocked by: none

## What to build

The two external identities the private-first topology needs (ADR 0006): a Telegram bot the hub polls directly, and a Cloudflare API token that can only manage the Tunnel, the Access policy, the DNS records for the tau hostname and the backup bucket. No Workers, D1, Vectorize or AI Search permissions: nothing in Cloudflare holds personal data.

Steps for the user:

1. Telegram: create the bot with BotFather (`/newbot`) and store the token as `TELEGRAM_BOT_TOKEN` in the local `.env`. Leave privacy mode on; the bot only needs direct messages.
2. Find your own `chat_id` (send the bot a message, then open `https://api.telegram.org/bot<token>/getUpdates`, or ask `@userinfobot`) and store it as `TELEGRAM_ALLOWED_CHAT_IDS` (comma-separated; one id for now).
3. Cloudflare: in the account that will hold the domain (022), create an API token limited to: Cloudflare Tunnel (edit), Access apps and policies (edit), DNS for the tau zone (edit; narrow it to the zone once 022 is done), R2 (edit). Store it as `CLOUDFLARE_API_TOKEN` and the account id as `CLOUDFLARE_ACCOUNT_ID` in `.env`.
4. R2: create a private bucket for the encrypted backups (018) and an R2 API token (S3 access key and secret) limited to that bucket. Store the bucket name as `TAU_BACKUP_BUCKET` and the credentials as `TAU_BACKUP_S3_ACCESS_KEY_ID` / `TAU_BACKUP_S3_SECRET_ACCESS_KEY`.
5. Add every new variable name with an example value to `.env.example`; real values stay in the gitignored `.env`.

## Acceptance criteria

- [x] Telegram bot created with BotFather; `TELEGRAM_BOT_TOKEN` in the local `.env`
- [x] The user's own `chat_id` recorded as `TELEGRAM_ALLOWED_CHAT_IDS`
- [ ] Cloudflare API token scoped to Tunnel, Access, zone DNS and R2 only; no Workers, D1, Vectorize, AI Search permissions and no global key
- [ ] A private R2 bucket for backups and a bucket-limited R2 API token exist; names and credentials in `.env`
- [ ] `.env.example` lists every new variable name with an example value; nothing real is committed

## Blocked by

None - can start immediately (the token's DNS scope is narrowed to the tau zone after 022).

## Comments

- 2026-09-29: rewritten for ADR 0006 (private-first). Before: a token for Workers, Durable Objects, D1, R2, Vectorize, AI Search and Workers AI plus a `workers.dev` subdomain. Now: Tunnel, Access, zone DNS and R2 only; the bot is polled directly by the hub (014), so no webhook secret exists.
- 2026-09-29: Telegram half done. Bot created with BotFather, privacy mode left on and group joins disabled (`/setjoingroups`); `getMe` and `getWebhookInfo` confirm both and that no webhook is set. `TELEGRAM_BOT_TOKEN` and `TELEGRAM_ALLOWED_CHAT_IDS` (read from `getUpdates` after a `/start`) are in the local `.env`; their names with example values are in `.env.example` and the `tau init` template. The example `[component.telegram]` table in `tau.toml` now shows `poll_timeout_seconds` instead of a variable name 014 does not use. Still open: the Cloudflare token (step 3), the R2 bucket and its token (step 4) and their `.env.example` names. 014 only needs the Telegram half.
