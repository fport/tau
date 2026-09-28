# L4 · Interface

**Goal:** More ways to talk to tau: TauBar, voice notes, Claude Code integration, ambient mode and "Hey tau".

**Done when:** TauBar controls sleep and shows status, voice works on Telegram and at the desk, and ambient mode can be switched on per profile.

| # | Issue | Type | Blocked by |
|---|---|---|---|
| 024 | [TauBar v0: tray app with sleep modes](024-taubar-sleep-modes.md) | AFK | – |
| 025 | [TauBar status panel: hub, nodes, spend, approvals](025-taubar-status-panel.md) | AFK | 009, 011, 024 |
| 026 | [Telegram voice notes with Whisper in the Worker](026-telegram-voice-notes.md) | AFK | 014 |
| 027 | [Claude Code "waiting for you" notification on Telegram](027-claude-code-waiting-notification.md) | AFK | 014 |
| 028 | [tau as an MCP server for Claude Code](028-tau-mcp-server.md) | AFK | 020, 021 |
| 029 | [Ambient mode: off by default, switchable profiles](029-ambient-mode-profiles.md) | AFK | 011, 019, 025 |
| 030 | [Pick the "Hey tau" wake phrase and record samples](030-pick-wake-phrase.md) | HITL | – |
| 031 | ["Hey tau": local wake word, speech-to-text and spoken replies](031-hey-tau-voice.md) | AFK | 009, 024, 030 |

Live status: `python3 roadmap/board.py`
