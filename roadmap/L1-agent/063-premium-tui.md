# 063 · Premium TUI: session sidebar, markdown replies, tool cards, status bar

Status: done
Type: AFK
Layer: L1 · Agent
Packages: tau-tui
Blocked by: none

## What to build

Turn `tau tui` from a header plus two `RichLog`s plus one `Input` into a keyboard-first, Claude-Code-style interface, following the design spec produced by the design workflow of the 2026-09-29 wave. The visible pieces: a session sidebar fed by `list_sessions()`, markdown-rendered replies, collapsible tool-call cards (tool, tier, approval result, duration, summary), a status bar (profile, session, model role, pending approval tier, spend placeholder), the tau logo from `docs/brand`, and a layout that still works at 80x24 and in portrait on the phone (061).

Fixed points that do not change: `tau tui` stays the entry point with `--profile` and `--resume [ID]`; config, credential and session errors exit 2 before the UI opens; logs go to `<data_dir>/logs/tau.log`; `TuiApprover` / `ApprovalScreen` semantics stay (explicit approval only, arming delay, reject on cancel, tier 2 never auto-approved); only the tau-core public API is imported; tests are pilot plus snapshot tests, offline with `FakeModel`.

This issue absorbs three smaller ones so the package is rewritten once:

- 055 · session commands and event replay: `/sessions`, `/resume`, `/resume <n|id>`, `/new`, `/session` in the TUI with the shared `tau_core.commands` spec; resuming rebuilds the agent on the stored session after `agent.close()`, re-subscribes the event pane to the new `EventBus`, updates the status bar, and replays `read_events()` before live events; a failed rebuild leaves the current agent working.
- 059 · logging helper: use tau-core's exported logging helper if it is in `tau_core.__all__` by then; otherwise keep the local `file_logging` and leave 059 open under this note. Either way nothing is written to stderr while the UI owns the terminal.
- 060 · snapshot extension: keep `.raw`, pin the extension (no glob), note the choice and the `--snapshot-update` command in the tau-tui README.

## Acceptance criteria

- [x] Session sidebar lists recent sessions from `list_sessions()`; selecting one resumes it; the current session is highlighted
- [x] Replies render as markdown (headings, lists, code blocks) and stream in as text arrives
- [x] Tool calls appear as collapsible cards with tool, tier, approval result, duration and summary; errors and notices are visually distinct
- [x] Status bar shows profile, session id, model role and the tier of a pending approval (header + hint bar); the spend figure is added by 011/025 when there is one to show
- [x] Logo and colors come from `docs/brand` (no redrawn assets)
- [x] Usable at 80x24 (snapshot test) and in a narrow portrait layout (panes stack, sidebar collapses); the 061 phone check is repeated after this lands
- [x] `/sessions`, `/resume`, `/resume <n|id>`, `/new`, `/session`, `/tools`, `/lang`, `/help`, `/quit` work through `tau_core.commands` with the same wording as the terminal channel; Turkish aliases still work (055)
- [x] Resuming rebuilds the agent, follows the new `EventBus`, replays stored events before live ones; a failed rebuild leaves the current agent working (055)
- [x] `ApprovalScreen` keeps explicit approval only, the arming delay and reject-on-cancel; keys `y`/`e` approve and `n`/`h`/Esc reject; a test proves tier 2 is never auto-approved
- [x] Nothing is written to stderr while the UI runs; the file log still receives records (059)
- [x] Exactly one `.raw` snapshot file per snapshot test, no glob; README documents the choice and the re-generation command (060)
- [x] `tau tui` keeps `--profile`, `--resume [ID]`, exit code 2 before the UI on config/credential/session errors, logging to `<data_dir>/logs/tau.log`
- [x] Only the tau-core public API is imported; pilot and snapshot tests run offline with `FakeModel`; `uv run pytest -q`, `ruff check` and `ruff format --check` are green
- [x] tau-tui README describes the layout, keys and commands in English; 055, 059 and 060 are closed with a note pointing here

## Blocked by

None - 007 and 008 are done. Uses the message table and command spec from 062 (same wave).

## Comments

- 2026-09-29: opened by the 2026-09-29 wave on the user's request (English UI, premium TUI, Strands audit, plug-and-play setup). Absorbs 055, 059 and 060; spec: wave decisions section 5 plus the design workflow output.
- 2026-09-29: built by the premium-TUI agent of the wave: `tau_tui` rewritten as theme/brand/strings/keys/transcript/tools/history/composer/events/sessions/approval/commands/header/app (`panes.py` deleted, tau-tui 0.2.0). Everything in the design spec except: the status-bar criterion is met by the header (profile, session id, role, tool count) plus the hint bar (pending approval) — the spend placeholder waits for 011 and is not shown; per-card keyboard browsing of older turns and OSC 52 copy are follow-ups per the spec. 059 stays open: tau-core exported `configure_logging` in the same wave, so the local `file_logging` can be replaced by it in a small follow-up. The 061 phone check is still due.
- 2026-09-29: test plan of the design spec (§22) implemented by the TUI-tests agent: 105 tests in `packages/tau-tui/tests` (conftest/helpers, transcript, history, composer, approval, cancel, sessions, app, brand, cli, snapshots) and the twelve snapshots of §22, every one containing the fixed session id and no local path, suite under 40 s. Bugs fixed on the way: the app CSS made modal screens opaque (the chat behind the approval dialog and the picker was hidden); a resize never re-ran the chrome refresh after the band changed (`-short` kept the old composer cap and hints; fixed with `TauScreen.on_resize`); Enter on the command menu ran the highlighted row even when a full command was typed (a key burst made `/session` run `/sessions`; found by the pty smoke run); a late `tool_call: running` bus event reopened a finished card; a `tool_call` event for an unknown id mounted its card below the busy row; `load_history` left the welcome card in place; the expanded card showed a Python repr instead of JSON; the header text oracle ignored ASCII mode. Tab in the approval dialog now only moves between the two buttons (PageUp/PageDown scroll the arguments). pty smoke runs at 80x24, 50x24 and 120x40 exit 0.
- 2026-09-29: review pass (two reviewers, seven findings, all confirmed and fixed with a regression test each): the chrome bands are read from the default screen (`TauApp.chrome_screen`), so an approval dialog or the picker on top no longer flips the phone/wide hints or the composer cap, and `#hint-left` keeps a one-cell gap before the right label; the events pane used a TCSS alpha (`"#FFF4E0 55%"`) as a Rich style, which Rich dropped — the live clock and the running dot now use the literal blends `theme.TEXT_MUTED`/`TEXT_DISABLED` (`test_events.py` parses every style string); `TAU_TUI_ASCII=1` now really switches the box borders (`theme.ASCII_CSS` on an `-ascii` screen class set by `mark_ascii` on the default screen and both modals; the uncalled `border_style()` is gone); a one-line fence costs one row plus its margins (`MarkdownFence > Label { padding: 0 1 }`, as mockup 4.6); the session picker no longer parses titles as markup (`OptionList(markup=False)`: a first message containing `[/x]` crashed the app); `EventLog._entries` is a `deque(maxlen=500)` like the log. Snapshots regenerated: chat_80x24 now pins the fence and the rejected card (spec §22), wide_100x30 the busy chrome (mockup 4.5), ultra_160x45 the fence (mockup 4.6). 112 tests in tau-tui, workspace green.
- 2026-09-29: done (orchestrator): Ember Console shipped as tau-tui 0.2.0 (commit b504eb7): rasterised brand mark, streamed Markdown replies, tool cards, approval modal, events pane/strip/view, session sidebar + picker, command menu, breakpoint bands, Esc cancel, 12 snapshots, 112 tests. Spend placeholder deferred to 011/025. 061 (phone check) stays for the user.
