# Slash commands

A line that starts with `/` is a slash command. The channel handles it and the model never sees it. The specification (names, aliases, arguments, help keys) is `tau_core.commands`; `tau chat` and `tau tui` implement the same twelve commands with the same wording, so the two never drift.

- Canonical names are English and are the only ones shown in hints and menus.
- Turkish aliases are accepted forever and never shown.
- Matching is case-insensitive (`str.casefold`): `/Resume 2` and `/ARAÇLAR` work.
- The argument is everything after the first space, stripped.
- An unknown command prints `Unknown command: /x. Commands: /help, /tools, …`.

## The commands

| Command | Aliases | Argument | Effect |
|---|---|---|---|
| `/help` | `/yardım`, `/yardim`, `/?` | – | list the commands with one-line help |
| `/tools` | `/araçlar`, `/araclar` | – | registered tools with their tier and description |
| `/sessions` | `/oturumlar` | – | the 10 most recent earlier sessions with messages, numbered, newest first, never the current one |
| `/resume` | `/devam` | `[n]` or `[id]` | resume the most recent earlier session; the n-th of the last `/sessions` listing (without a listing, of the one it would print now); or the session with that id |
| `/new` | `/yeni` | – | start a fresh session; the current one stays on record |
| `/session` | `/oturum` | – | current session id, title, message count and store |
| `/compact` | `/özet`, `/ozet` | `[focus]` | summarize this session with its own model and continue in a new session seeded with the summary; the old session is kept and the two are linked |
| `/clear` | `/temizle`, `/cls` | – | clear the screen (terminal) or the transcript (TUI); the session and the agent go on |
| `/status` | `/durum` | – | profile, session, model, context, tools, UI language, versions, hub |
| `/model` | `/rol` | `[role]` | list the roles of `tau.toml` with the current one marked, or switch this session to a role |
| `/lang` | `/dil` | `en` or `tr` | switch the UI language for this run |
| `/quit` | `/çık`, `/cik`, `/exit` | – | leave |

`/exit` is an alias of `/quit`; hints always show `/quit`.

## Output of each command

Examples are in the `en` chrome; `tr` has the same lines translated.

### `/help`

```text
Commands:
  /help             list the commands
  /tools            registered tools with their tier and description
  /sessions         list the 10 most recent earlier sessions
  /resume [n|id]    resume the most recent earlier session, the n-th of the last listing, or an id
  /new              start a fresh session
  /session          current session id, title, message count and store
  /compact [focus]  summarize this session into a new one and continue there (the old one is kept)
  /clear            clear the screen; the session continues
  /status           profile, session, model, context, tools, language, versions and hub
  /model [role]     show the model roles, or switch this session to one
  /lang en|tr       switch the UI language for this run
  /quit             leave
```

### `/tools`

```text
Tools (2):
  current_time  tier 0 · read — Returns the current date and time in the Europe/Istanbul time zone.
  demo_physical_action  tier 2 · physical, needs approval — Demo tool that simulates a physical action (tier 2, asks for approval on every call).
```

Tier labels: `read`, `digital write, logged`, `physical, needs approval`.

### `/sessions` and `/resume`

```text
Recent sessions:
 1. 20260929-173826-f949  29.09.2026 17:38  terminal  Merhaba tau (2 messages)
 2. 20260929-120000-abcd  29.09.2026 12:00  tui       Salon lambası açık mı? (14 messages)
```

`/resume` → `Resuming: <title> · <id> (<n> messages loaded).` Errors: `No earlier session to resume.`, `Session not found: <id>.`, `There is no session <n> in the list (1-<count>).`, `You are already in this session: <id>.`, and `Could not open the session: <error>` (a session recorded under a different `[agent] context` mode is the usual cause; see [Sessions and compaction](sessions.md)).

### `/new` and `/session`

`/new` → `New session: <id>.`

```text
Session: 20260929-173826-f949
Title: Merhaba tau
Messages: 2
Store: file (~/.local/share/tau/sessions)
```

### `/compact [focus]`

```text
Compacting 14 messages…
Compacted 14 messages into a summary. New session 20260929-181200-7c1e; the previous session 20260929-120000-abcd is kept.
<the summary, dimmed>
```

`focus` is appended to the summarizer's instructions as `Focus on: …`. Failures (`Compaction failed: <error>`) leave the current session running; nothing is written. In the TUI the summary runs in a worker: the chrome is busy, read-only commands still answer, Esc cancels (`Compaction cancelled; the session continues.`).

### `/clear`

Terminal: an ANSI clear, the ready banner again, then `Screen cleared; the session continues (<n> messages kept).` TUI: the transcript, welcome card and info cards are emptied. Nothing on disk changes; `/resume` or `--resume` show the history again.

### `/status`

```text
Profile: home
Session: 20260929-173826-f949 · Merhaba tau · 2 messages stored · role brain
Model: brain → anthropic (fallback; bedrock has no credentials) · claude-sonnet-5
Context: sliding, window 60 · 2 messages in memory
Tools: 2 registered · 1 need approval (tier 2)
UI language: en
Versions: tau-core 0.2.0 · tau-tui 0.2.0
Hub: hub is not running (nothing answers on http://127.0.0.1:7877/health)
```

The model line names the provider and model id and says when the fallback is in use; it never prints a key. The hub line is the `tau doctor` probe (one second, information only). In the TUI `/status` is an info card.

### `/model [role]`

```text
Model role: brain (anthropic)
Roles in tau.toml:
  brain  bedrock (fallback anthropic) · current
  fast   bedrock (fallback anthropic)
  local  ollama
```

`/model fast` rebuilds the agent on the **same** session with that role: the new agent is built first, so a failed build (unknown role, missing credentials, unavailable provider) changes nothing and prints why. The role is written to the session's metadata, so `/resume` and `--resume` come back on it. `tau chat --role` pins a role for the run and wins over the stored one.

### `/lang en|tr`

`UI language: tr.` / `Arayüz dili: tr.` Without an argument: `Usage: /lang en|tr (current: en).` The persona's reply language is unaffected.

## Terminal versus TUI

| | `tau chat` | `tau tui` |
|---|---|---|
| While a turn runs | commands cannot be typed; the REPL does one thing at a time | `/new`, `/resume`, `/compact`, `/clear`, `/model <role>` wait for the turn (a toast says so); `/status` and `/model` answer any time |
| Menu | none; `/help` lists | typing `/` in an empty composer opens a fuzzy menu (`↑↓` pick, Tab complete, Enter run, Esc close) |
| Session picker | `/sessions` + `/resume n` | the same, plus ctrl+r / F2 and the sidebar at ≥ 140 columns |
| `/clear` | clears the screen | clears the transcript |

## In code

```python
from tau_core import SLASH_COMMANDS, command_hint, resolve_command, t

resolve_command("/Devam 2")   # ("resume", "2"); None for "/x" or plain text
command_hint()                # "/help, /tools, /sessions, /resume, /new, ..."
t("session.not_found", "tr", session="x")   # "Oturum bulunamadı: x."
```

Every string a person reads comes from `tau_core.i18n`, keyed and per language; plugins add their own keys with `register_messages`.

## On Telegram

The [Telegram](../guides/telegram.md) channel resolves the same specification with the same wording: `/help`, `/tools`, `/sessions`, `/resume`, `/new`, `/session`, `/status`, `/model`, `/compact` and `/lang` work, Turkish aliases included. `/start` (what Telegram sends when you open the bot) and a bare `/` show the help, and `/help@your_bot` works. The hub sets these commands as the bot's menu for each allowed chat (`setMyCommands` with a chat scope), with the help texts in the UI language; `/lang` sets the menu again in the new language. An unknown command lists only the commands that work on Telegram. The rest (`/clear`, `/quit` and any command that edits credentials) answer that they are not available on Telegram. `/lang` switches the language of that chat until the hub restarts.
