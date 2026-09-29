# L1 · Agent

**Goal:** A Strands-based tau agent that can be talked to from the terminal, with persona, permission tiers, sessions and a long-running hub process.

**Done when:** `tau chat` / `tau tui` hold resumable conversations in the Jarvis persona, tier-2 tools ask for approval, and `tau hub` runs as a self-healing service.

| # | Issue | Type | Blocked by |
|---|---|---|---|
| 003 | [Provision model credentials with cost guards](003-provision-model-credentials.md) | HITL | – |
| 004 | [Tracer bullet: `tau chat` answers in the Jarvis persona](004-tau-chat-tracer-bullet.md) | AFK | – |
| 005 | [Live persona files and dynamic context in the system prompt](005-live-persona-dynamic-context.md) | AFK | 004 |
| 006 | [Tool permission tiers with approval and a loop guard](006-tool-permission-tiers.md) | AFK | 004 |
| 007 | [Session persistence and `/devam` resume](007-session-persistence-resume.md) | AFK | 004 |
| 008 | [Textual TUI with chat and live event pane](008-textual-tui.md) | AFK | 004 |
| 009 | [`tau hub` daemon with launchd service and self-heal](009-hub-daemon.md) | AFK | 004 |
| 054 | [Show the conversation channel in the dynamic context](054-channel-in-dynamic-context.md) | AFK | – |
| 055 | [Session commands and event replay in the TUI](055-tui-session-commands.md) | AFK | – |
| 056 | [Session index for fast listing once sessions number in the thousands](056-session-index.md) | AFK | – |
| 057 | [Verify the `tau hub` launchd agent live (install, kill -9 relaunch, uninstall)](057-verify-hub-launchd-live.md) | HITL | – |
| 058 | [Load hub-hosted services from entry points in `tau hub run`](058-hub-services-from-entry-points.md) | AFK | – |
| 059 | [Export a logging helper from tau-core's public API](059-logging-helper-public-api.md) | AFK | – |
| 060 | [Pin or fix the snapshot file extension for tau-tui snapshots](060-tui-snapshot-extension.md) | AFK | – |
| 061 | [Verify `tau tui` from the phone over mosh (Termius)](061-verify-tui-on-phone.md) | HITL | – |
| 062 | [English UI with a per-installation language setting](062-english-ui-language-setting.md) | AFK | – |
| 063 | [Premium TUI: session sidebar, markdown replies, tool cards, status bar](063-premium-tui.md) | AFK | – |
| 064 | [Strands-correctness pass over tau-core (strands-agents 1.57.1)](064-strands-correctness-pass.md) | AFK | – |
| 065 | [Component builder: entry-point groups, `[components]` config, `tau components\|doctor\|init`](065-component-builder.md) | AFK | – |
| 066 | [English docs: README, ARCHITECTURE, infra/remote, CLAUDE.md, CONTEXT.md, ADRs](066-english-docs.md) | AFK | – |
| 072 | [Session commands: /clear, /compact, /status and /model in both channels](072-session-commands-clear-compact-status-model.md) | AFK | – |

Live status: `python3 roadmap/board.py`
