# 014 · Telegram channel by direct polling: `getUpdates` loop on the hub → agent → reply

Status: done
Type: AFK
Layer: L3 · Access and data
Packages: tau-core
Blocked by: 013

## What to build

The first external channel, end to end and without a middleman (ADR 0006 §2). A `tau.hub_services` component `telegram` in tau-core (`tau_core.channels.telegram`, entry point `telegram = "tau_core.channels.telegram:make_service"`, contract in ADR 0005) runs a `getUpdates` long-poll loop inside `tau hub run`: outbound HTTPS only, no webhook, no Worker, no Durable Object, no inbound port. Each update from an allowlisted `chat_id` becomes one turn of that chat's session (`build_agent(channel="telegram")`, so the session metadata and the dynamic context (054) say `telegram`); the reply goes back with `sendMessage`. Anything from another chat is dropped and logged, never answered, so the bot does not confirm its existence to strangers.

- Configuration: `TELEGRAM_BOT_TOKEN` and `TELEGRAM_ALLOWED_CHAT_IDS` from `.env` (013); `[component.telegram]` for `poll_timeout_seconds` and similar knobs. Without a token the service starts idle, logs one line and reports `telegram: {configured: false}` in `/status`; it never fails the hub.
- Polling: `deleteWebhook` on start (Telegram refuses `getUpdates` while a webhook is set), long poll with a server-side timeout, the `offset` persisted under `TAU_DATA_DIR/telegram/offset` so a restart neither re-processes nor skips updates, exponential backoff on network errors, `allowed_updates` limited to `message` and `callback_query` (the latter for 017).
- Conversation: a chat keeps its current session across hub restarts (`TAU_DATA_DIR/telegram/chats.json`: chat id → session id). `/help`, `/new`, `/sessions`, `/resume`, `/session`, `/status`, `/model`, `/compact` and `/lang` resolve through `tau_core.commands` exactly as in the terminal; unknown commands get the shared hint. `sendChatAction typing` while a turn runs; replies longer than 4096 characters are split; markup Telegram would reject falls back to plain text.
- Tier 2 before 017 lands: a `RefusingApprover` rejects with the tier gate's refusal text plus one sentence pointing at a trusted channel (TUI, TauBar). Nothing is ever auto-approved.
- One consumer per token: Telegram hands each update to one `getUpdates` caller; the hub lock already guarantees one hub per machine, and the RPi5 handover (048) stops the old poller before the new one starts.
- Tests use a fake Bot API in `tau_core.testing` (no network): allowlist, offset persistence, command dispatch, message splitting, idle start without a token.

## Acceptance criteria

- [x] A message from the allowlisted chat gets a Jarvis reply on Telegram; the session's metadata records `channel = "telegram"`
- [x] Messages from any other chat are dropped and logged; the bot never replies to them
- [x] No webhook is set, no inbound port is opened and no Cloudflare resource is involved; `/status` and `tau doctor` show the poller state
- [x] A hub restart neither re-processes nor loses updates (offset persisted; fake Bot API test)
- [x] Network loss → reconnect with backoff; the hub stays up while the poller is down
- [x] Slash commands from `tau_core.commands` work on Telegram with the terminal's wording; Turkish aliases accepted, never shown
- [x] A tier-2 call from Telegram is refused with a pointer to a trusted channel until 017 lands; no auto-approval in code or tests
- [x] Without a token the service starts idle and the hub runs on; the tau-core README documents `[component.telegram]` and the `.env` names

## Blocked by

- [013 · Create the Telegram bot and record the allowed chat id](013-telegram-bot-and-cloudflare-token.md)

## Comments

- 2026-09-29: rewritten for ADR 0006 (private-first). Before: webhook → `tau-cloud` Worker → Durable Object → authenticated WebSocket to the hub → reply, with `cloud/tau-cloud` as a package. Now: the hub polls `getUpdates` directly as a `tau.hub_services` component; no Worker, no inbound port. It lives in tau-core next to the terminal channel; if it ever needs dependencies of its own it moves to a `tau-telegram` distribution behind the same entry point. 009 (hub daemon) and 058/065 (hub services) are done, so only 013 blocks it. The file keeps its old slug so links stay stable.
- 2026-09-29: done. `tau_core.channels.telegram` is a `tau.hub_services` component (`telegram = "tau_core.channels.telegram:make_service"`): `getMe`, `deleteWebhook` and `setMyCommands` on start, then a `getUpdates` long poll through `urllib` in a daemon thread, so a poll in flight never delays the hub's exit and tau-core gains no dependency. Offset and `chats.json` under `TAU_DATA_DIR/telegram/` (files `0600`); network errors back off 1, 2, 4 … s up to `[component.telegram] backoff_max_seconds` (60), sends retry on network errors and 429, a 401 stops the poller and the hub runs on. Commands resolve through `tau_core.commands` with the terminal's i18n keys; `/clear`, `/quit` and configuration commands answer `telegram.unavailable`; `/start` and a bare `/` show the help; the command menu is set per allowed chat (`scope: chat`), never for strangers. Replies go out as HTML converted from Markdown with a plain-text fallback, split at 4096 UTF-16 units. Tier 2: `RefusingApprover` plus a new optional `refusal_note` on approvers that the tier gate appends to the text the model reads (`approval.py`); nothing auto-approves. `tau doctor` has a `telegram` line (config from `.env`, poller state from `/status`); `tau_core.testing.FakeBotApi` is the offline Bot API (29 tests in `test_telegram.py`). Verified live with the user's bot: replies, the tier-2 refusal with the pointer to the TUI / `tau chat`, `channel = "telegram"` in the session metadata, a hub restart that kept the session and did not answer old updates again. The dynamic context still says the channel only after 054. Commits: 9a9f3a7, 4185a52, 9c341a4.
