# 073 · `tau ask "…"`: one-shot command for scripts and iOS Shortcuts

Status: ready-for-agent
Type: AFK
Layer: L1 · Agent
Packages: tau-core, docs
Blocked by: none

## What to build

`tau ask "<prompt>"` (the prompt also comes from stdin when there is no argument or it is `-`) builds the agent with `channel="ask"`, runs one turn, prints the reply as plain text (no markup, no spinner, no ANSI when stdout is not a TTY, so `say` and Shortcuts can read it) and exits: 0 on `end_turn`, 2 when the turn was refused or hit a limit, 1 on an error with one English line on stderr. Options mirror `tau chat`: `--resume` (continue the most recent session), `--session <id>`, `--role <role>`, `--profile`, `--lang`, and `--json` (reply, session id, stop reason). By default every call opens a fresh session, so scripts do not pollute the user's conversations; the session is still recorded and shows in `/sessions`. Tier-2 tools are never approved from `tau ask`: a `RefusingApprover` in `tau_core.approval` returns the gate's refusal text plus one sentence naming the trusted channels (TUI, TauBar, Telegram, the web UI), and the turn ends normally (ADR 0006, consequences). Slash commands are not interpreted; a leading `/` is sent as text.

Docs: a guide page on the docs site with the iOS Shortcut recipe "Dictate text" → "Run Script over SSH" (host: the hub's tailnet name, command `tau ask "<Dictated Text>"`, key-based login) → "Speak text", with example values only and the Tailscale/Termius prerequisites from the phone guide.

## Acceptance criteria

- [ ] `tau ask "…"` prints the reply and exits 0; `echo hi | tau ask` works; the session is recorded with `channel = "ask"`
- [ ] `--resume`, `--session`, `--role`, `--profile`, `--lang` and `--json` behave as documented (tests with `FakeModel` and `test_config`)
- [ ] A tier-2 tool call is refused with the gate's text and a pointer to a trusted channel; exit code 2; no approval prompt ever appears and nothing is auto-approved (test with a tier-2 fake tool); the `RefusingApprover` is reusable by 014 and 074
- [ ] Output is plain text on stdout, diagnostics on stderr, no ANSI in non-TTY mode
- [ ] The docs-site guide describes the iOS Shortcut recipe with example values; the tau-core README lists the command

## Blocked by

None - can start immediately; 054 (channel in the dynamic context) is independent, and the `ask` channel name should be added to its list.

## Comments

- 2026-09-29: opened for ADR 0006 (private-first): "a one-shot `tau ask` command exists for scripts and iOS Shortcuts over SSH/Tailscale; it never approves tier-2 calls".
- 2026-09-30: ADR 0008 (owner guard): with a guard active, `TauAgent.ask()` raises `GuardLocked`; `tau ask` catches it, prints the guard notice (`guard.refused.<reason>`) on stderr and exits 2, and `--json` reports stop reason `locked`. Over SSH it is admitted only while the owner is verified at the Mac, so remote use needs 117's per-client grants.
