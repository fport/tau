# Talk to tau

Two channels run in the terminal today. `tau chat` is a line-based REPL: one prompt, streamed replies, tool lines, approvals on stdin. `tau tui` is a full Textual interface: markdown replies, tool cards, a live events pane, a session picker and a modal approval dialog. They share the same slash commands, the same session store and the same tier gate, so you can start in one and `/resume` in the other.

| | `tau chat` | `tau tui` |
|---|---|---|
| Best for | scripts, slow links, a quick question | daily use, the phone, long sessions |
| Replies | streamed plain text | streamed markdown |
| Tool calls | dim lines | cards with tier, approval, duration and result |
| Approvals | `Approve? [y/N]` on stdin | modal dialog with **Approve** / **Reject** |
| Agent events | in the log file only | live pane, replayed on `/resume` |
| Cancel a turn | Ctrl-C | Esc |
| Leave | `/quit`, Ctrl-D | `/quit`, Ctrl+Q |
| Needs a TTY | no | yes |

Both read the same config and stop with exit code 2 before anything opens when the config is broken or a `--resume ID` is unknown. Missing credentials stop `tau chat` the same way; `tau tui` opens on its settings screen instead, and with no config at all it opens a setup screen ([First run](first-run.md#in-the-interface-tau-tui)).

## `tau chat`

```sh
tau chat                      # new session on the brain role
tau chat --resume             # continue the most recent earlier session
tau chat --resume ID          # continue that session
tau chat --session ID         # start with this session id
tau chat --role fast          # pin a role for the whole run
tau --lang tr chat            # Turkish chrome
```

```text
tau ready. Profile: home, session: 20260929-173826-f949. Commands: /help, /tools, /sessions, /resume, /new, /session, /compact, /clear, /status, /model, /lang, /quit (Ctrl-D also quits).
you> Merhaba tau
tau> Merhaba. Nasıl yardımcı olabilirim?
you> /session
Session: 20260929-173826-f949
Title: Merhaba tau
Messages: 2
Store: file (~/.local/share/tau/sessions)
```

The REPL does one thing at a time: a command never overlaps a turn. Ctrl-C during a turn cancels it at the next safe point and prints `Interrupted.`; Ctrl-C at the prompt leaves.

### Approvals on the terminal

A tier-2 call blocks the turn and asks on stdin:

```text
⚠️  Approval needed (tier 2)
  Tool: demo_physical_action
  Arguments: {"action": "turn on the desk lamp"}
  Effect: Demo: simulates a physical action; no real device moves.
  Approve? [y/N]
```

- `y`, `yes`, `e` or `evet` approves, in either UI language.
- Anything else rejects: `n`, Enter, Ctrl-D, a typo.
- There is no timeout on the terminal; the prompt waits for you.
- A rejection does not end the turn. The model reads `The user did not approve this action` as the tool result and answers.

## Slash commands

A line that starts with `/` is a command. The channel handles it; the model never sees it. The thirteen canonical names are English; Turkish aliases (`/devam`, `/çık`, `/özet`, `/ayarlar`, …) keep working but are never shown.

| Command | What it does |
|---|---|
| `/help` | list the commands with one-line help |
| `/tools` | registered tools with their tier and description |
| `/sessions` | the 10 most recent earlier sessions, numbered |
| `/resume`, `/resume n`, `/resume id` | resume the most recent earlier session, the n-th of the last listing, or an id |
| `/new` | start a fresh session; the current one stays on record |
| `/session` | current session id, title, message count and store |
| `/compact [focus]` | summarize this session with its own model and continue in a new session seeded with the summary; the old one is kept |
| `/clear` | clear the screen; the session and the agent go on |
| `/status` | profile, session, model, context, tools, UI language, versions, hub |
| `/model [role]` | list the roles of `tau.toml`, or switch this session to one; `/resume` remembers it |
| `/lang en`, `/lang tr` | switch the UI language for this run |
| `/settings [key value]` | show the settings (roles, credential status, language, profile, context, files); in the terminal `/settings language tr`, `/settings profile NAME`, `/settings model ROLE PROVIDER MODEL_ID`, `/settings set NAME` (hidden prompt) and `/settings clear NAME` change one; in the TUI it opens the settings screen |
| `/quit` | leave; `/exit` is an alias |

```text
you> /status
Profile: home
Session: 20260929-173826-f949 · Merhaba tau · 2 messages stored · role brain
Model: brain → anthropic (fallback; bedrock has no credentials) · claude-sonnet-5
Context: sliding, window 60 · 2 messages in memory
Tools: 2 registered · 1 need approval (tier 2)
UI language: en
Versions: tau-core 0.2.0 · tau-tui 0.2.0
Hub: hub is not running (nothing answers on http://127.0.0.1:7877/health)
```

`/status` names the model per role and whether the fallback is in use, never a key. The [slash command reference](../reference/slash-commands.md) has the aliases and the exact wording of every notice.

## `tau tui`

```sh
tau tui                       # new session
tau tui --resume              # continue the most recent earlier session
tau tui --resume ID
tau tui --profile travel
tau --home /path/to/root --lang tr tui
```

The interface is one row of chrome at the top and at most four at the bottom, so 80x24 over mosh on a phone stays usable. The header shows the profile, the session id, the role, the tool count and the UI language; the composer is a rounded box that grows from one to five lines; the hint bar names the keys that matter right now.

```text
 τ tau  home · 20260929-120000-abcd                                  brain · en
 › Salon lambası açık mı? Açıksa kapat.
 ● get_light_state(room="salon")                                  tier 0 · 38ms
   ⎿  {"on": true, "brightness": 80}
 ● set_light(room="salon", on=false)                  tier 2 · approved · 412ms
   ⎿  Light turned off
 τ Salon lambası kapatıldı.
   • Önceki durum: açık, %80 parlaklık
 ✓ Worked for 4s · 2 tool calls · ctrl+o expand
╭──────────────────────────────────────────────────────────────────────────────╮
│ ❯ Type a message…                                                            │
╰──────────────────────────────────────────────────────────────────────────────╯
 ? shortcuts · / commands · ctrl+j newline                          ctrl+q quit
```

Glyphs, one cell each and no emoji: `›` you · `τ` tau · `●` finished tool call · `○` running or waiting for approval · `⎿` result line · `✻` busy · `✓ ◆ ✗` turn footer (finished / needs you or limit / error) · `▸` notice · `❯` prompt.

### Layout by screen size

The TUI picks a layout from the terminal size. Width bands: **phone** below 60 columns, **narrow** 60–99, **wide** 100–139, **ultra** 140 and up. Height bands: **short** below 20 rows, **mid**, **tall** 30 and up.

| Terminal | What you get |
|---|---|
| 50x24 (phone, Termius over mosh) | The header drops the session id (`/session` shows it), tool badges move to the result line, the composer has no border, hints read `^j`, the welcome card shows the 16-column mark, replies stream as plain text and settle into markdown when the segment ends, the approval dialog is full width with stacked buttons. |
| 80x24 (narrow) | The layout above. `ctrl+e` or F4 swaps the transcript for the events log in the same body; Esc returns. |
| 80x30 (narrow, tall) | An 8-row events strip under the transcript. |
| 100x30 (wide) | The events pane docks on the right (34 columns); `ctrl+e` hides it. |
| 160x45 (ultra) | A read-only session sidebar on the left (28 columns); clicking a row resumes. Events pane 40 columns. |
| under 20 rows (short) | No hint row, the welcome mark is hidden, the composer grows to two rows. |

### Keys

| Key | Effect |
|---|---|
| Enter | send, or accept the highlighted menu row |
| ctrl+j | newline (shift+enter too where the terminal delivers it) |
| Esc | close the menu · cancel the running turn · leave the events view · scroll back to the bottom |
| ctrl+e / F4 | events: toggle the column (≥ 100 cols) or the view (< 100 cols) |
| ctrl+r / F2 | session picker (Enter resumes, `n` new, Esc closes) |
| ctrl+n | new session |
| ctrl+t / F3 | `/tools` |
| ctrl+o / F6 | expand or collapse the cards of the last turn: arguments as JSON and the full result |
| PageUp / PageDown, F7 / F8 | scroll the transcript; PageUp at the top of a folded history loads 20 older turns |
| F9 | back to the bottom |
| F10 | settings screen (`/settings`); inside it `ctrl+s` or F2 saves, Esc closes |
| ↑ / ↓ | recall sent prompts; navigate the menu while it is open |
| `?` or F1 | help (only in an empty composer) |
| ctrl+q | quit (ctrl+c copies a selection; without one it only says how to quit) |

Typing `/` into an empty composer opens a fuzzy menu of the thirteen commands: `↑↓` pick, Tab completes, Enter runs, Esc closes. A command typed in full runs as typed even if the menu has not caught up with a burst of keys, so `/session` never runs `/sessions`.

While tau answers, the composer keeps your text and a toast says so. `/new`, `/resume`, `/compact`, `/clear`, `/model <role>` and `/settings` wait for the current turn; `/status` and `/model` without an argument answer any time.

### Approvals in the TUI

A tier-2 call opens a translucent dialog over the chat: tool, effect, the arguments as pretty JSON, **Approve** and **Reject**.

- `y` or `e` approves; `n`, `h` or Esc rejects. Focus starts on **Reject**, so Enter rejects. Tab moves between the two buttons.
- `y`/`e` and **Approve** only work half a second after the dialog opens; the hint reads `(arming…)` meanwhile. Keys you were typing into the chat cannot approve by accident.
- Anything other than an explicit approval rejects: a dialog closed another way, a cancelled wait, an app that is no longer running.
- Behind the dialog the tool card reads `○ set_light(…)` and `⎿ ◆ waiting for your approval`; the composer border and the header `τ` turn Flare.

### Terminal knobs

| Setting | Effect |
|---|---|
| `TAU_TUI_ASCII=1` | ASCII vocabulary and box borders for terminals without the block characters |
| `TAU_TUI_PLAIN_STREAM=1` | stream every reply as plain text and parse the markdown once per segment |
| `TEXTUAL_ANIMATIONS=none` | no header motion |
| `TEXTUAL_COLOR_SYSTEM` / `--ansi` | the 16-colour `tau-ansi` theme |

Live markdown streaming needs at least 60 columns. While the TUI runs, details go to `<TAU_DATA_DIR>/logs/tau.log`; the chat shows a short notice instead of a traceback.

## The UI language

```sh
tau --lang tr chat
tau --lang tr tui
```

`--lang` sets the chrome for one run; it is exported as `TAU_LANG`, so the TUI, the terminal and their approval prompts agree. `/lang en` or `/lang tr` switches it inside a session; `/settings language tr` (or the **Interface** section of the TUI's settings screen) writes it to `tau.toml` for good. The persona keeps answering in whatever language you write.

## Where things end up

- Sessions: `<TAU_DATA_DIR>/sessions/<id>/`, one directory each, kept forever. [Sessions and compaction](../reference/sessions.md).
- Log: `<TAU_DATA_DIR>/logs/tau.log`, `INFO` and up with tracebacks; tier-1 and tier-2 tool calls with their arguments and approval.
- Nothing else. No telemetry, no cloud copy unless you set up [backups](../guides/backups.md).
