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

Live status: `python3 roadmap/board.py`
