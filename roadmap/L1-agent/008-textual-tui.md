# 008 · Textual TUI with chat and live event pane

Status: done
Type: AFK
Layer: L1 · Agent
Packages: tau-tui
Blocked by: 004

## What to build

`tau tui` opens a Textual interface that is usable over SSH from Termius: a chat pane and a live event pane (tool calls with tier and approval result, errors). Tier-2 approvals appear as an in-TUI dialog.

## Acceptance criteria

- [x] Usable at 80x24 and in Termius on a phone over mosh
- [x] Replies stream into the chat pane; the event pane shows tool calls with tier and approval result
- [x] Tier-2 approvals are handled inside the TUI
- [x] `tau-tui` is its own distribution and uses only the public API of `tau-core`
- [x] Tests use Textual's pilot/snapshot harness

## Blocked by

- [004 · Tracer bullet: `tau chat` answers in the Jarvis persona](004-tau-chat-tracer-bullet.md)

## Comments

### 2026-09-29 · done (agent)

Replaced the `tau-tui` skeleton with the Textual app. `tau tui [--profile AD] [--resume [ID]]` opens a one-line header (profile and session id only), a chat pane where `TauAgent.stream()` turn events stream in (`sen:`/`tau:` blocks, `⚙`/`✓`/`✗` tool lines, `ℹ` notices), an event pane fed by `EventBus.subscribe` (every agent event with local time; `tool_call` shows tool, tier, status, approval, duration and summary; unknown kinds are shown with their data), and a one-row input. Under 100 columns the panes stack, above they sit side by side; both re-wrap on resize. Tier-2 calls open `ApprovalScreen` (tool, pretty-JSON arguments, effect, `Onayla`/`Reddet`; `e` approves, `h`/Esc reject, focus starts on `Reddet`); `TuiApprover` (`name = "tui"`) awaits a future the dialog resolves and rejects on anything but an explicit approval. Config/credential errors and an unknown `--resume ID` exit 2 with the Turkish message before the UI opens; while the UI runs, logs go to `<data_dir>/logs/tau.log`. Colors come from the brand palette.

Criteria notes: 80x24 is checked by the pilot layout test, the committed 80x24 snapshot and a run of the real command in a pseudo-terminal (xterm-256color, 80x24: reply streamed, Ctrl+Q exited 0); a 50-column portrait layout was checked by screenshot. Nothing needs a mouse. A run from Termius over mosh on the phone itself is still for the user to confirm. `tau-tui` imports only the tau-core names listed in the brief (plus `tau_core.testing` in tests).

Commits:
- `docs(roadmap): start 008`
- `feat(tui): add the chat and event panes`
- `feat(tui): add the approval dialog and TuiApprover`
- `feat(tui): add TauApp and the tau tui command`
- `test(tui): drive the TUI with pilot and an 80x24 snapshot`
- `docs(tui): document layout, keys, approvals and logs`
- `test(tui): keep path fragments out of repo-wide path searches`
- `docs(roadmap): close 008`

Deviations and notes:
- `packages/tau-core/tests/test_cli.py::test_placeholders` still expects the `tau tui` placeholder (`Henüz yok (issue 008).`); with the real command it exits 2 (no config in that test). The `["tui"]` case must be dropped at merge (tau-core is outside 008's files).
- The committed snapshot is `tests/__snapshots__/test_app/test_empty_app_snapshot.raw`: pytest-textual-snapshot 1.0.0 with syrupy 6 writes `.raw` instead of `.svg` (the content is the SVG). If either library changes, re-run `uv run pytest packages/tau-tui --snapshot-update` and delete the old file. The test checks both the captured screenshot and the committed file for home-directory and temp paths.
- `e` only approves 0.5 s after the dialog opens (`APPROVE_DELAY`), so keys typed for the chat cannot approve by accident; tests use `approve_delay` to shorten or remove it.
- `tau_core.logs` is not in the allowed API, so `tau_tui.cli.file_logging` adds its own file handler for `<data_dir>/logs/tau.log`.
- `tau-tui` imports `click` and `rich` directly; they arrive through `tau-core` and `textual` but are not declared in its `pyproject.toml` (declaring them changes `uv.lock`, outside this issue's files).
- The TUI has `/araçlar` and `/çık` (also `/cik`, Ctrl+Q); `/devam`, `/yeni`, `/oturum` are not in the TUI yet.

For the next issues:
- 006: when `TierGate` gets `timeout_seconds` (`asyncio.wait_for`), `TuiApprover.decide` is cancelled; it then takes the dialog down, so a late `e` cannot approve.
- 007: `--resume` uses `store.list_sessions(limit=1)`, `read_session` and `read_meta`; with the `file` backend it works across processes and `ChatPane.show_history(agent.messages)` shows the restored conversation.
- L3/L4 channels that emit new agent event kinds show up in the event pane as `kind: {data}` without changes here.
