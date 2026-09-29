# Telegram

Telegram will be tau's channel when you are away from the terminal: text from your phone, replies from the hub, and approval buttons for tier-2 calls. This page has the two things you can do today (create the bot, find your chat id) and describes how the hub will use them.

!!! info "Planned (roadmap issues 014 and 017)"
    The Telegram channel does not exist in the current packages. Issue 014 adds the channel as a hub service that **polls Telegram directly**; issue 017 adds approvals through inline buttons. The bot and chat id steps below are [issue 013](https://github.com/fport/tau/blob/main/roadmap/L3-cloud/013-telegram-bot-and-cloudflare-token.md), a human task, and are safe to do now.

## Why the hub polls, and no server sits in between

The first design routed Telegram through a Cloudflare Worker and a Durable Object. [ADR 0006](../adr/0006-private-first-topology.md) dropped that: a relay would hold both your conversation and the approval path on public infrastructure, and a bug or a leaked token there would reach your home.

Instead the hub calls Telegram's `getUpdates` itself, outbound, in a loop. Consequences:

- **No webhook, no public URL, no inbound port.** The hub only makes outgoing HTTPS requests to `api.telegram.org`.
- **Nothing between Telegram and the hub can forge an approval.** A button press arrives as a callback from your chat, and the hub checks the chat id before it does anything.
- **Offline is fine.** While the hub is down, Telegram keeps updates for about a day; the hub catches up when it starts. There is no "tau is offline" auto-reply (a tiny optional Worker may add it later).
- **A `chat_id` allowlist on the hub** drops every message from anyone but you before the agent sees it.

## 1. Create the bot with BotFather

1. Open Telegram and start a chat with [@BotFather](https://t.me/botfather).
2. Send `/newbot`.
3. Answer with a display name (anything) and a username: 5–32 characters, must end in `bot`, must be unused (for example `deniz_tau_bot`).
4. BotFather replies with the **token**, a string like `110201543:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw`. Treat it as a password.

Optional but sensible while you are there:

- `/setprivacy` → your bot → **Disable** only if you plan to add the bot to groups and want it to read all messages. For a one-to-one chat with yourself, leave the default.
- `/setdescription` and `/setuserpic` for a nicer chat header.

## 2. Find your chat id

Send any message to your new bot in Telegram, then ask the Bot API for the pending updates:

```sh
curl -s "https://api.telegram.org/bot<token>/getUpdates" | python3 -m json.tool
```

Look for `"chat": {"id": 123456789, ...}` inside the first `message`. That number is your **chat id**. For a private chat it is your own Telegram user id and it never changes.

!!! tip
    An empty `"result": []` means the message has not arrived yet or the bot has not been started. Press **Start** in the chat and send one more message.

## 3. Store both in `.env`

Both values are secrets and personal; they go into `<TAU_HOME>/.env` and nowhere else:

```sh
TELEGRAM_BOT_TOKEN=110201543:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw
TELEGRAM_CHAT_ID=123456789
```

`tau doctor` compares the names in `.env` with `.env.example` and warns about names it does not know. Add the two names, with placeholder values, to your `.env.example` so the check stays green:

```sh
# Telegram (planned channel, issues 014 and 017)
# TELEGRAM_BOT_TOKEN=110201543:AAxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
# TELEGRAM_CHAT_ID=123456789
```

!!! note
    The variable names above are the ones the roadmap uses today. Issue 014 fixes the final names and the `[component.telegram]` table in `tau.toml`; this page will be updated when the channel ships.

## 4. What the channel will do

- **Text in, text out.** Your message becomes a turn in a session tagged `channel = "telegram"`; the reply is sent back to the same chat. `/sessions` and `/resume` work from Telegram the same way they do in the terminal.
- **Allowlist.** Messages and button callbacks from any chat id other than yours are ignored before the agent is involved.
- **Approvals with inline buttons** (issue 017). A tier-2 call sends a message with the tool, its arguments and its effect, and two buttons: **Approve** and **Reject**, labelled in the UI language. Approve runs the tool; reject, or a timeout, returns a clean refusal that the model reads. Every decision is recorded in the session like a terminal approval.
- **Startup status report** (issue 015). When the hub starts or restarts it sends one short message: version, profile, last crash if any.
- **Voice notes** (issue 026). A voice note is transcribed **on the hub**, not by a cloud speech API, and reaches the agent as text marked as voice. See [Voice](voice.md).

## Security notes

- The bot token lets its holder read your messages to the bot and reply as the bot. It does not reach the hub, its files or the approval path. Rotate it with `/revoke` in BotFather if you suspect a leak, and update `.env`.
- Anyone can find and message a bot by its username; the allowlist is what keeps strangers out of your agent. Never set the allowlist to "everyone".
- Text from Telegram is untrusted input to the agent, like everything else. That is why writes are tier 2 or sandboxed and why approvals never come from the model.
