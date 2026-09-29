# tau-tui

The [Textual](https://textual.textualize.io/) terminal interface for tau: replies stream in as
markdown, tool calls are cards with their tier, approval and result, agent events show in a live
pane, tier-2 calls ask in a modal dialog, and the brand's τ mark opens every new session. One row
of chrome at the top, at most four at the bottom, so 80x24 over mosh on a phone stays usable.

It is its own distribution (`tau-tui`, import `tau_tui`), uses only the public API of `tau-core`
and plugs into the `tau` command through the `tau.commands` entry point (`tui`):

```sh
pip install tau-tui          # or, in this repo: uv sync --all-packages --group dev
tau tui                      # new session
tau tui --resume             # continue the most recent earlier session
tau tui --resume ID          # continue a given session
tau --home /path/to/tau --lang tr tui --profile travel
```

Configuration comes from `tau.toml` and `.env` like every other channel (`TAU_HOME`,
`TAU_DATA_DIR`, `TAU_PROFILE`, `TAU_LANG`). Missing credentials, a broken config or an unknown
session end the command with a plain English message and exit code 2 before the interface opens.
The chrome (hints, labels, notices, the approval dialog) follows `[ui] language` (`en` or `tr`);
`/lang` switches it for one run.

## Layout

Four bands by width (`-phone` < 60 cols, `-narrow` 60–99, `-wide` 100–139, `-ultra` ≥ 140) and
three by height (`-short` < 20 rows, `-mid`, `-tall` ≥ 30). The header is one row, the composer a
rounded box of one to five text rows, the hint bar one row.

80x24 (`-narrow`), idle after a two-tool turn:

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

100x30 (`-wide`): the events pane docks on the right (34 cols; 40 at `-ultra`), `ctrl+e` hides
it. 160x45 (`-ultra`): a read-only session sidebar (28 cols) on the left; clicking a row resumes.

```text
 τ tau  home · 20260929-120000-abcd                          brain · 7 tools · en
 › Salon lambası açık mı? Açıksa kapat.          │ Events · 5
 ● get_light_state(room="salon")   tier 0 · 38ms │ 12:00:01 ● get_light_state
   ⎿  {"on": true, "brightness": 80}             │          tier 0 · ok · 38ms
 τ Salon lambası kapatıldı.                      │ 12:00:02 ◆ approval set_light
                                                 │          tier 2 → approved (tui)
```

80x30 (`-narrow -tall`): an 8-row events strip under the transcript. Below 100 cols `ctrl+e` /
F4 swaps the transcript for the events log in the same body; the composer stays live and Esc
returns to the chat.

50x24 (`-phone`, Termius over mosh): the header drops the session id (`/session` shows it),
tool badges move to the result line, the composer has no border, hints say `^j`, the welcome
card shows the 16-column mark, replies stream as plain text and settle into markdown when the
segment ends, and the approval dialog is full width with stacked buttons.

```text
 τ tau · home                                  en
 › Salon lambası açık mı? Açıksa kapat.
 ○ set_light(room="salon", on=false)
   ⎿  tier 2 · running
 ✻ Running set_light…
 ❯
 esc cancel · ^j newline                     busy
```

`-short` (< 20 rows): no hint row, the welcome mark is hidden, the composer grows to two rows.

## Vocabulary

Every glyph is one cell wide and none is an emoji-presentation code point, so phone terminals
draw them at the right width: `›` you · `τ` tau · `●` finished tool call · `○` running or waiting
for approval · `⎿` result line · `✻` busy verb / reasoning · `✓ ◆ ✗` turn footer (finished /
limit, cancelled, interrupted / error) · `◆` needs you · `▸` notice · `❯` prompt.

State colours (deliberate; no green and no red in the palette, shapes double the colours):
**ok / success = Flare**, **error = Signal**, **rejected = Ember**, **running / pending = Core at
55 %**, **attention = Flare**, notice = Ember. Rich renderables (the events pane) cannot take a TCSS
alpha, so they use the literal blends `theme.TEXT_MUTED` (Core over Void at 60 %, the live clock and
the running dot) and `theme.TEXT_DISABLED` (38 %, replayed clocks). The header `τ` breathes while the welcome card is
on screen, runs the comet while a turn is busy and is static Ember otherwise; nothing else in
the UI moves. The composer border is Ember, Signal while busy and Flare while an approval waits.

## Keys and commands

| Key | Effect |
|---|---|
| Enter | send (or accept the highlighted menu row); while tau answers the text stays and a toast says so |
| ctrl+j | newline (shift+enter too where the terminal delivers it) |
| Esc | close the menu · cancel the running turn · leave the events view · scroll back to the bottom |
| ctrl+e / F4 | events: toggle the column (≥ 100 cols) or the view (< 100 cols) |
| ctrl+r / F2 | session picker (Enter resumes, `n` new, Esc closes) |
| ctrl+n | new session |
| ctrl+t / F3 | `/tools` |
| ctrl+o / F6 | expand or collapse the cards of the last turn: the arguments as JSON and the full result (a click toggles any card) |
| PageUp / PageDown, F7 / F8 | scroll the transcript; PageUp at the top of a folded history loads 20 older turns |
| F9 | back to the bottom |
| ↑ / ↓ | recall sent prompts (single-line composer); navigate the menu while it is open |
| `?` or F1 | help (only in an empty composer; `?x` is sent as a message) |
| ctrl+q | quit (ctrl+c copies a selection in the composer; without one it only says how to quit) |

Typing `/` into an empty composer opens a fuzzy menu of the slash commands (`↑↓` pick, Tab
complete, Enter run, Esc close). An exact name ranks first, and a command typed in full runs as
typed even when the menu has not caught up with a burst of keys (a paste, mosh), so `/session`
never runs `/sessions`. The commands are the shared spec of `tau_core.commands`, with
the same wording as `tau chat`: `/help`, `/tools`, `/sessions`, `/resume [n|id]`, `/new`,
`/session`, `/lang en|tr`, `/quit`. The Turkish aliases (`/devam`, `/çık`, …) keep working but
are never listed. `/new` and `/resume` wait for the current turn.

## Approvals

`TuiApprover` (`name = "tui"`) is the channel's `Approver`. A tier-2 call opens `ApprovalScreen`:
tool, effect, the arguments as pretty JSON and the buttons **Approve** / **Reject**.

- `y` or `e` approves, `n`, `h` or Esc rejects; focus starts on **Reject**, so Enter rejects, and
  Tab only moves between the two buttons (PageUp/PageDown scroll the arguments). The keys work in
  both languages whatever the UI setting.
- `y`/`e` and **Approve** only work 0.5 s after the dialog opens (the hint reads `(arming…)`
  meanwhile), so keys typed for the chat cannot approve by accident.
- Anything other than an explicit approval rejects: a dialog closed another way, an approver
  with no running app, or a cancelled wait (the dialog is taken down so it cannot approve later).
- Rejecting does not cancel the turn: the model reads the refusal and answers.

The dialog is translucent: the chat stays visible behind it. Behind it the tool card reads
`○ set_light(…)` + `⎿ ◆ waiting for your approval`, the composer and the header `τ` turn Flare
and the hint bar says what to press. Nothing in this package approves on its own.

## Sessions and events

`/sessions` lists the ten most recent earlier sessions with messages (numbered for `/resume n`,
same order as `tau chat`); `/resume` alone resumes the most recent one. Resuming rebuilds the
agent on the stored session (the previous one is closed), renders the history from the stored
messages (user rows, markdown replies, tool cards with the recorded duration, approval and
result), replays the stored agent events into the events pane before live ones, and keeps the
current agent when the rebuild fails. The last 40 turns stay live; older ones fold into one
line and PageUp at the top pages them in. One `EventBus` serves the app for its lifetime; events
stamped with another session id are ignored.

## Knobs

| Setting | Effect |
|---|---|
| `TAU_TUI_ASCII=1` | ASCII vocabulary (`> t * o L * + x ! - >`), `ascii` box borders on every screen (the screens carry an `-ascii` class that `theme.ASCII_CSS` keys on), an Ember-only mark |
| `TAU_TUI_PLAIN_STREAM=1` | stream every reply as plain text and parse the markdown once per segment |
| `TEXTUAL_ANIMATIONS=none` | no header motion at all (also the default under `motion=False`) |
| `TEXTUAL_COLOR_SYSTEM` / `--ansi` | the `tau-ansi` theme for 16-colour terminals |

Live markdown streaming needs ≥ 60 cols; two consecutive slow appends (a long open code fence)
switch the segment to plain text until it ends. Replies are coalesced to at most one update every
80 ms.

## Logs

While the interface runs the terminal belongs to Textual: details go to
`<TAU_DATA_DIR>/logs/tau.log` (for example `~/.local/share/tau/logs/tau.log`), the stderr
handler of the `tau` command is detached for the duration, and the chat shows a short notice
instead of a traceback.

## Python API

```python
from tau_tui import TauApp, build_app, resolve_resume, SessionNotFound
from tau_tui import TuiApprover, ApprovalScreen, Transcript, EventLog, rasterise

app = build_app(config, session_store=store, session_id=None)  # builds the agent (channel "tui")
app.run()
```

`build_app` creates one `EventBus` and one `TuiApprover`, builds the first agent with
`tau_core.build_agent(..., channel="tui")` and gives `TauApp` a factory that builds every later
agent (`/new`, `/resume`) on the same bus, store and approver. Tests pass `model=FakeModel([...])`,
`tools=[...]`, a fixed `clock`, `tz=UTC`, `motion=False` and `show_durations=False`.
`resolve_resume(store, resume, language=...)` turns `--resume [ID]` into a session id and an
optional notice (`SessionNotFound` for an unknown id). `rasterise(cols)` is the τ mark as
half-block cells (`docs/brand/README.md`, "Terminal").

## Development

```sh
uv run pytest packages/tau-tui -q                      # pilot + snapshot tests, offline
uv run pytest packages/tau-tui --snapshot-update       # after an intended visual change
```

Snapshots live under `tests/__snapshots__/test_snapshots/` as `.raw` files: pytest-textual-snapshot
1.0 with syrupy 6 writes SVG under that extension, and the extension is pinned in
`test_snapshots.py` (exactly one file per snapshot test, no glob). There are twelve: welcome at
80x24, 50x24 and in Turkish, chat (a markdown list, a one-line fence and a rejected tier-2 card),
busy, approval, menu and picker at 80x24, wide 100x30 (busy chrome), ultra 160x45 (a fence and the
last turn's cards expanded), the events view at 50x24 and short 80x18. Every snapshot uses the fixed session id
`20260929-120000-abcd` (checked in every file), a fixed clock, UTC event times, no motion and no
durations, and is taken after the streams stopped; review a regenerated file before committing it
(it must never contain a local path, which the test also checks). The pilot tests read the widgets
through text oracles (`Transcript.text`, `EventLog.text`, `HintBar.text`, `HeaderBar.text`,
`ToolCard.text`) so behaviour changes do not churn the snapshots. The mark fixtures under
`tests/fixtures/` are the text previews of `rasterise(24)` and `rasterise(16)`; regenerate them
together with the pinned SHA-256 in `test_brand.py` when the geometry in `docs/brand/render.py`
changes.

License: MIT.
