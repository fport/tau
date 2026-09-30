# Telegram

Telegram is tau's channel for when you are away from the terminal: you write from your phone and the hub replies. The channel is a hub service in tau-core, so it runs whenever `tau hub run` (or the launchd/systemd service) runs. This page covers creating the bot, pairing your chat with it (no chat id to look up), starting the channel and what it does.


## Why the hub polls, and no server sits in between

The first design routed Telegram through a Cloudflare Worker and a Durable Object. [ADR 0006](../adr/0006-private-first-topology.md) dropped that: a relay would hold both your conversation and the approval path on public infrastructure, and a bug or a leaked token there would reach your home.

Instead the hub calls Telegram's `getUpdates` itself, outbound, in a loop. Consequences:

- **No webhook, no public URL, no inbound port.** The hub only makes outgoing HTTPS requests to `api.telegram.org`. It deletes any webhook on start, since Telegram refuses `getUpdates` while one is set.
- **Nothing between Telegram and the hub can forge an approval.** A button press arrives as a callback through the same poll, and the hub checks who pressed, in which chat, and that the request is still waiting before it does anything.
- **Offline is fine.** While the hub is down, Telegram keeps updates for about a day; the hub catches up when it starts. There is no "tau is offline" auto-reply.
- **A chat id allowlist on the hub** drops every message from anyone but you before the agent sees it. Strangers get no answer at all, so the bot does not even confirm it is alive.

## 1. Create the bot with BotFather

1. Open Telegram and start a chat with [@BotFather](https://t.me/botfather).
2. Send `/newbot`.
3. Answer with a display name (anything) and a username: 5–32 characters, must end in `bot`, must be unused (for example `deniz_tau_bot`).
4. BotFather replies with the **token**, a string like `110201543:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw`. Treat it as a password.

Recommended while you are there:

- `/setjoingroups` → your bot → **Disable**. Nobody can add the bot to a group; it only needs your direct messages.
- Leave privacy mode (`/setprivacy`) at its default, enabled.
- `/setdescription` and `/setuserpic` for a nicer chat header, if you like.

## 2. Pair your chat

```sh
tau telegram pair
```

It asks for the token from BotFather (hidden; nothing shows while you paste), checks it with Telegram and shows a one-time code:

```text
Checking the token with Telegram...
Telegram knows the bot as @deniz_tau_bot.
wrote TELEGRAM_BOT_TOKEN to ~/.tau/.env (mode 0600)
Open t.me/deniz_tau_bot in Telegram and send: /start K7QM-X2PA
Or in one tap: https://t.me/deniz_tau_bot?start=K7QM-X2PA
The code works once, for 10 minutes (until 14:32). Waiting for it; Ctrl-C cancels.
The running hub takes the code.
```

Tap the link on your phone and press **Start**, or open the bot and send `/start K7QM-X2PA` yourself. The bot answers "Paired", and the command ends:

```text
Paired with Deniz @deniz. tau answers only this chat on Telegram from now on.
```

What happened:

- **The token** went into `<TAU_HOME>/.env` as `TELEGRAM_BOT_TOKEN`. Only that line is added or replaced; the file keeps its other lines and mode `0600`. Enter at the prompt keeps the token `.env` already has, which is how you re-pair.
- **Your chat** became `TELEGRAM_ALLOWED_CHAT_IDS`, the allowlist the channel checks. Re-pairing replaces it, and the command says how many chats lost access.
- **Who took the code.** With a running hub, the command asks it (the signed `POST /telegram/reload` on the local control API) to read `.env` and the code again; the hub's own poll loop accepts the code and answers from then on, with no restart. Without a hub, the command polls Telegram itself, from the hub's saved position, and stops right after your code, so the hub later starts where it left off. Either way only one process polls the bot, and nothing but your machine and `api.telegram.org` is involved.

The code rules:

- 8 characters without look-alikes (no `0`/`O`, `1`/`I`/`L`), from a cryptographic random source, case and dashes ignored.
- Valid for 10 minutes and works once. While the command waits it lives only as a salted hash in `TAU_DATA_DIR/telegram/pairing.json`, and the command removes it when it stops; Ctrl-C withdraws it.
- Only a private chat can pair, never a group. A wrong or expired code gets no answer and changes nothing, like any stranger's message. After 10 wrong codes the code stops working.

`tau telegram status` shows whether a token is set (and the bot's name), whether a chat is paired, whether a code waits and what the hub's poller does. It never prints the token or a chat id. The setup wizard of the Mac app runs the same command with `--json` (see the [CLI reference](../reference/cli.md#tau-telegram)).

!!! note "With the owner guard"
    A paired chat talks to tau without the [owner guard](guard.md): the allowlist identifies you. So on a guarded Mac, `tau telegram pair` runs only while tau is unlocked (`tau guard verify`).

## 3. Or: set the chat id by hand

The manual way, for example for [cloud mode](cloud-mode.md), where both values become the spine's secrets instead of `.env` lines. Put the token into `<TAU_HOME>/.env` first (below), open your bot in Telegram, press **Start** and send one more message. Then ask the Bot API for the pending updates:

```sh
curl -s "https://api.telegram.org/bot<token>/getUpdates" | python3 -m json.tool
```

Look for `"chat": {"id": 123456789, ...}` inside the first `message`. That number is your **chat id**. For a private chat it is your own Telegram user id and it never changes.

!!! tip
    An empty `"result": []` means the message has not arrived yet or the bot has not been started. Press **Start** in the chat, send one more message and ask again. Do this before the hub's Telegram channel runs: once it polls, it takes the updates itself.

Both values are secrets and personal; they go into `<TAU_HOME>/.env` and nowhere else:

```sh
TELEGRAM_BOT_TOKEN=110201543:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw
TELEGRAM_ALLOWED_CHAT_IDS=123456789
```

`TELEGRAM_ALLOWED_CHAT_IDS` takes several ids separated by commas; one is enough for you alone. The `.env.example` that `tau init` writes already lists both names, so `tau doctor` stays quiet about them. A hub that already runs reads the file again on its next start (`tau hub stop`, then `tau hub run`).

## 4. Start it

If you paired while the hub ran, it already answers. Otherwise:

```sh
tau doctor        # ok   telegram: configured (1 allowed chat); polls while the hub runs
tau hub run       # or `tau hub install` for the launchd service
```

Optional knobs live in `tau.toml`:

```toml
[component.telegram]
poll_timeout_seconds = 50    # how long one getUpdates waits on Telegram's side
backoff_max_seconds = 60     # cap of the backoff after network errors
approval_timeout_seconds = 300   # an unanswered approval counts as "not approved"
```

Write to your bot. The reply comes from the hub, and `tau doctor` now shows `polling as @your_bot`. `curl -s http://127.0.0.1:7877/status` has a `telegram` key with the poller state (`polling`, `retrying`, `failed`), the time of the last poll, the last error and how many updates it handled and dropped. It never shows the token or a chat id.

Without a token, or without an allowed chat and no pairing code waiting, the channel starts idle and logs one line; the hub runs on either way. `/status` also says `pairing: true` while a code of `tau telegram pair` waits.

## 5. What the channel does

- **Text in, text out.** Your message becomes a turn in a session tagged `channel = "telegram"`; the reply is sent back to the same chat, formatted from the model's Markdown (bold, code, links) and split when it is longer than Telegram's 4096 characters. "typing…" shows while tau thinks. Photos, voice notes and stickers get a short "text only for now" note.
- **Your conversation survives restarts.** Each chat keeps its current session across hub restarts (`TAU_DATA_DIR/telegram/chats.json`). The poll offset (`offset`) and the messages still being worked on (`inflight.json`) are saved as they change, so a restart neither answers a message twice nor skips one; a message whose turn was cut off by a stop runs again.
- **Slash commands.** `/help`, `/tools`, `/sessions`, `/resume`, `/new`, `/session`, `/status`, `/model`, `/compact` and `/lang` work as in the terminal, with the same wording and the Turkish aliases. The hub registers them as the bot's command menu (`setMyCommands`) when it starts, so typing `/` in Telegram lists them with their help text in the UI language; the menu is set for your chat only, so strangers who open the bot see none. See [Slash commands](../reference/slash-commands.md#on-telegram).
- **Network trouble.** When the connection drops, the poller backs off (1 s, 2 s, 4 s, … up to a minute) and reconnects; the hub stays up. A token the Bot API rejects stops the poller until the next hub start (`tau doctor` shows `fail`).
- **Approvals with inline buttons.** A tier-2 call (a physical action, or activating a tool tau wrote) sends a message with the tool, its arguments and its effect, and two buttons, **Approve** and **Reject**, labelled in the UI language. Approve runs the tool once; Reject, or no answer within five minutes (`approval_timeout_seconds`), is "not approved" and tau tells you so. The message is then edited to show the outcome and loses its buttons. Only a press by you (your id in `TELEGRAM_ALLOWED_CHAT_IDS`) on a request that is still waiting counts; everything else is ignored and logged. Messages you send while an approval waits are answered after it. If the hub restarts while an approval waits, the request is cancelled and asked again after the restart.

Planned:
- **Startup status report** (issue 015). When the hub starts or restarts it sends one short message: version, profile, last crash if any.
- **Voice notes** (issue 026), transcribed **on the hub**, not by a cloud speech API. See [Voice](voice.md).

## Security notes

- The bot token lets its holder read your messages to the bot and reply as the bot. It does not reach the hub, its files or the approval path. Rotate it with `/revoke` in BotFather if you suspect a leak, and update `.env`.
- Anyone can find and message a bot by its username; the allowlist is what keeps strangers out of your agent. Never put anyone else's chat id there.
- Pairing needs the code your terminal shows. It is useless once used or after 10 minutes, a wrong one is never answered, and the bot confirms nothing to a stranger who guesses.
- Credentials are never set from Telegram: commands that edit the configuration answer that they are not available on this channel.
- Text from Telegram is untrusted input to the agent, like everything else. That is why writes are tier 2 or sandboxed and why approvals never come from the model.
