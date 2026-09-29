# 063 · Premium TUI: session sidebar, markdown replies, tool cards, status bar

Status: in-progress
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

- [ ] Session sidebar lists recent sessions from `list_sessions()`; selecting one resumes it; the current session is highlighted
- [ ] Replies render as markdown (headings, lists, code blocks) and stream in as text arrives
- [ ] Tool calls appear as collapsible cards with tool, tier, approval result, duration and summary; errors and notices are visually distinct
- [ ] Status bar shows profile, session id, model role, the tier of a pending approval and a spend placeholder (filled by 011)
- [ ] Logo and colors come from `docs/brand` (no redrawn assets)
- [ ] Usable at 80x24 (snapshot test) and in a narrow portrait layout (panes stack, sidebar collapses); the 061 phone check is repeated after this lands
- [ ] `/sessions`, `/resume`, `/resume <n|id>`, `/new`, `/session`, `/tools`, `/lang`, `/help`, `/quit` work through `tau_core.commands` with the same wording as the terminal channel; Turkish aliases still work (055)
- [ ] Resuming rebuilds the agent, follows the new `EventBus`, replays stored events before live ones; a failed rebuild leaves the current agent working (055)
- [ ] `ApprovalScreen` keeps explicit approval only, the arming delay and reject-on-cancel; keys `y`/`e` approve and `n`/`h`/Esc reject; a test proves tier 2 is never auto-approved
- [ ] Nothing is written to stderr while the UI runs; the file log still receives records (059)
- [ ] Exactly one `.raw` snapshot file per snapshot test, no glob; README documents the choice and the re-generation command (060)
- [ ] `tau tui` keeps `--profile`, `--resume [ID]`, exit code 2 before the UI on config/credential/session errors, logging to `<data_dir>/logs/tau.log`
- [ ] Only the tau-core public API is imported; pilot and snapshot tests run offline with `FakeModel`; `uv run pytest -q`, `ruff check` and `ruff format --check` are green
- [ ] tau-tui README describes the layout, keys and commands in English; 055, 059 and 060 are closed with a note pointing here

## Blocked by

None - 007 and 008 are done. Uses the message table and command spec from 062 (same wave).

## Comments

- 2026-09-29: opened by the 2026-09-29 wave on the user's request (English UI, premium TUI, Strands audit, plug-and-play setup). Absorbs 055, 059 and 060; spec: wave decisions section 5 plus the design workflow output.
