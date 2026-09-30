# Slash commands

A line that starts with `/` is a slash command. The channel handles it and the model never sees it. The specification (names, aliases, arguments, help keys) is `tau_core.commands`; `tau chat` and `tau tui` implement the same thirteen commands with the same wording, so the two never drift (the Telegram channel offers the subset that makes sense in a chat).

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
| `/settings` | `/ayarlar`, `/ayar` | `[key value]` | show the bootstrap config (roles, credential status, language, profile, context, files) or change one value; the TUI opens its settings screen |
| `/quit` | `/çık`, `/cik`, `/exit` | – | leave |

`/exit` is an alias of `/quit`; hints always show `/quit`.

## Output of each command

Examples are in the `en` chrome; `tr` has the same lines translated.

### `/help`

```text
Commands:
  /help                  list the commands
  /tools                 registered tools with their tier and description
  /sessions              list the 10 most recent earlier sessions
  /resume [n|id]         resume the most recent earlier session, the n-th of the last listing, or an id
  /new                   start a fresh session
  /session               current session id, title, message count and store
  /compact [focus]       summarize this session into a new one and continue there (the old one is kept)
  /clear                 clear the screen; the session continues
  /status                profile, session, model, context, tools, language, versions and hub
  /model [role]          show the model roles, or switch this session to one
  /lang en|tr            switch the UI language for this run
  /settings [key value]  show the settings, or change one (language, profile, model, set NAME)
  /quit                  leave
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
Model: brain → proxy · brain
Context: sliding, window 60 · 2 messages in memory
Tools: 2 registered · 1 need approval (tier 2)
UI language: en
Versions: tau-core 0.3.1 · tau-tui 0.3.1
Hub: hub is not running (nothing answers on http://127.0.0.1:7877/health)
Budget: brain $0.42 of $15.00 per 1mo (resets 01.10.2026 03:00); fast $0.03 of $1.00 per 1d (resets 01.10.2026 03:00); local $0.00 of $0.50 per 1d (resets 01.10.2026 03:00)
```

The model line names the provider and model id (for the proxy, the model group) and says when a direct role's `fallback` is in use; it never prints a key. The budget line appears when a role goes through the LiteLLM proxy: what each role's key spent in its period, read from the proxy ([Model proxy and budgets](../guides/model-proxy.md)). The hub line is the `tau doctor` probe (one second, information only). In the TUI `/status` is an info card.

### `/model [role]`

```text
Model role: brain (proxy)
Roles in tau.toml:
  brain  proxy · current
  fast   proxy
  local  proxy
```

`/model fast` rebuilds the agent on the **same** session with that role: the new agent is built first, so a failed build (unknown role, missing credentials, unavailable provider) changes nothing and prints why. The role is written to the session's metadata, so `/resume` and `--resume` come back on it. `tau chat --role` pins a role for the run and wins over the stored one.

### `/lang en|tr`

The confirmation is already in the new language: `/lang tr` answers `Arayüz dili: tr.` and `/lang en` answers `UI language: en.`. Without an argument: `Usage: /lang en|tr (current: en).` The persona's reply language is unaffected.

### `/settings [key value]`

Without an argument, the bootstrap config as the files hold it:

```text
Settings · ~/.tau
Model roles:
  brain  proxy · brain · credentials ok
  fast   proxy · fast · credentials ok
  local  proxy · local · credentials ok
UI language: en · profile: home
Context: sliding, window 60 · max_turns 12 · max_total_tokens none
Files:
  tau.toml            ~/.tau/tau.toml · present
  .env                ~/.tau/.env · present
  .env.example        ~/.tau/.env.example · present
  persona/persona.md  ~/.tau/persona/persona.md · present
  persona/user.md     ~/.tau/persona/user.md · present
Change: /settings language en|tr · /settings profile NAME · /settings model ROLE PROVIDER MODEL_ID · /settings set NAME · /settings clear NAME. The TUI (`tau tui`) has an editor: /settings or F10. `tau init --force` rewrites tau.toml from the template.
```

The credential status per role reads `credentials ok`, `no credentials needed`, `missing X, Y`, `missing X, Y · fallback anthropic in use` or `provider not available: …`; no value is ever printed.

In the terminal the setters write the files through `tau_core.settings` (comments in `tau.toml` survive, `.env` stays at mode `0600`) and reload:

| Form | Effect |
|---|---|
| `/settings language en\|tr` | `[ui] language` in `tau.toml`; the chrome switches at once (`Settings saved.` then, already in the new language, `Arayüz dili: tr.`) |
| `/settings profile NAME` | `TAU_PROFILE` in `.env`; the agent is rebuilt on the same session (`Settings saved; model reloaded.`) |
| `/settings model ROLE PROVIDER MODEL_ID` | provider and model id of a role (its `max_tokens` and `fallback` are kept); rebuilds. A planned provider (one a later issue builds; none right now) is refused unless the role already names it: `Not saved: tau.toml: [models.roles.brain] provider '…' is not supported yet (issue …); available: anthropic, bedrock, fake, ollama, proxy.` |
| `/settings set NAME` | asks `Value for NAME (not echoed): ` with a hidden prompt, writes `NAME` to `.env` (surrounding whitespace stripped), exports it to the running process and rebuilds (`NAME set in .env.`); an empty or blank value changes nothing |
| `/settings clear NAME` | removes `NAME` from `.env` and the process (`NAME removed from .env.` / `NAME is not in .env.`) |

A value the config refuses is answered with `Not saved: <reason>` and nothing is written (`tau.toml` is checked before the write); a file that saved but whose agent cannot be rebuilt says `Settings saved, but the agent could not be rebuilt: <reason>` and the current agent goes on. Anything else prints the usage line.

In the TUI `/settings [section]` opens the settings screen (F10 does the same), on the named section when one is given (`roles`, `credentials`, `interface`, `agent`, `doctor`, `files`). The screen is described in [First run](../getting-started/first-run.md#in-the-interface-tau-tui). It is refused while a turn is busy.

## Terminal versus TUI

| | `tau chat` | `tau tui` |
|---|---|---|
| While a turn runs | commands cannot be typed; the REPL does one thing at a time | `/new`, `/resume`, `/compact`, `/clear`, `/model <role>`, `/settings` wait for the turn (a toast says so); `/status` and `/model` answer any time |
| `/settings` | prints the report; the setters write the files | opens the settings screen (also F10) |
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
