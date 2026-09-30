# 172 · Telegram pairing without looking up a chat id

Status: done
Type: AFK
Layer: L4 · Interface
Packages: tau-core
Blocked by: 169

## What to build

[ADR 0014](../../docs/adr/0014-one-installer-and-onboarding.md) §5.

- `tau telegram pair` (and a `tau setup` step) takes the bot token at a hidden prompt, stores it in `.env` and shows a one-time code.
- The hub's Telegram service accepts that code from the first chat that sends it within 10 minutes, and stores that chat as the owner's.
- It then answers only there, as today.
- Other chats get nothing, as today.

## Acceptance criteria

- [x] Pairing works end to end against a fake Bot API; wrong or expired codes are refused
- [x] `docs/guides/telegram` (EN + TR) leads with pairing; the chat-id path stays as the manual way

## Comments

- 2026-10-01: filed with ADR 0014.
- 2026-10-01: done. Built in parallel with 169, whose `telegram` feature calls it. As built:
  - **Commands** (`tau_core.channels.telegram_cli`, entry point `telegram`): `tau telegram pair [--json]` and `tau telegram status [--json]`. The token comes from a hidden prompt, or with `--json` from one stdin line `{"token": "..."}` (`null` or `""` keeps the token `.env` has). It is checked with one `getMe` and written to `<home>/.env` with `set_credential` (that line replaced or appended, the rest kept, mode 0600). It never reaches argv, the output or a log. `--json` prints one event per line: `note`, `bot`, `code`, `waiting`, `paired` or `error` with a stable `reason`. The protocol is in `docs/reference/cli.md#tau-telegram`.
  - **The code** (`tau_core.channels.telegram_pairing`): 8 characters from an alphabet without look-alikes, drawn with `secrets`, shown as `ABCD-EFGH` with the deep link `https://t.me/<bot>?start=<code>`. It is valid 10 minutes and works once. It is stored only as salted PBKDF2-SHA256 in `TAU_DATA_DIR/telegram/pairing.json` (0600), and every change happens under an `flock`. Only a private chat can pair. A wrong, group or expired code gets no answer and stores nothing, and 10 wrong codes void it. A match sets `TELEGRAM_ALLOWED_CHAT_IDS` to that chat (replacing the list; the command reports how many chats lost access), and the chat gets "Paired".
  - **Who accepts it: whoever polls, and only one process polls.** With a hub running, the command calls the new protected `POST /telegram/reload`. `TelegramService.reload()` re-reads the token and the allowlist from `.env` first, since the hub loaded `.env` into its environment at start. It also picks up the code, restarts the poller only when the token or the allowlist changed, and polls with an empty allowlist while a code waits. `_take` accepts `/start <code>` before the allowlist check, registers the command menu for the chat and needs no restart. The command then only watches the record and the hub's `/health`. Without a hub, the command long-polls `getUpdates` itself from `TAU_DATA_DIR/telegram/offset`, writes the offset back and stops right after the pairing update, so the rest stays with Telegram for the hub. Messages of chats that stay allowed go to `inflight.json`. A 409 makes it look for a hub that started meanwhile. A hub without the route that still polls (an older version) is reported as `hub_conflict` instead of fighting over updates.
  - **Hub side**: `/status` `telegram` gains `pairing`. The poller goes idle again when a code runs out with no chat allowed. An inflight replay now drops chats that are no longer allowed. `tau doctor`'s empty-allowlist warning points to `tau telegram pair`.
  - **Guard (ADR 0008)**: a paired chat is an identified channel with `guard=None`, so with the guard active the command asks for admission first (label `telegram-pair`) and stops, asking nothing, while tau is locked. `/guard lock` from Telegram is unchanged.
  - **For 169's `telegram` feature**: run `tau telegram pair` on the terminal (it inherits the TTY). The app's wizard pipes `{"token": ...}` into `tau telegram pair --json` and relays the events. `tau telegram status --json` → `paired` / `token` tells whether the feature is set up.
  - Tests: `packages/tau-core/tests/test_telegram_pairing.py`. They run on the FakeBotApi, and one runs a real assembled hub with its signed control route. Docs: `docs/guides/telegram(.tr).md` lead with pairing and keep the chat-id path as the manual way. Also updated: `docs/reference/cli(.tr).md`, `environment.md`, `components.md`, the tau-core README and both `.env.example` files. `README.md` and `getting-started/build-your-own-tau` still show the manual path; that is left for 175.
