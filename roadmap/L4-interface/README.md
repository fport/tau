# L4 · Interface

**Goal:** More ways to talk to tau: TauBar, the web UI (the TUI in the browser), tau-voice (push-to-talk, Telegram voice notes, voice from the phone, "Hey tau"), Claude Code integration and ambient mode.

**Done when:** TauBar controls sleep and shows status, the TUI runs in the browser behind Access or on the tailnet, voice works at the desk, on Telegram and from the phone without audio leaving the hub, and ambient mode can be switched on per profile.

| # | Issue | Type | Blocked by |
|---|---|---|---|
| 024 | [TauBar v0: tray app with sleep modes](024-taubar-sleep-modes.md) | AFK | – |
| 025 | [TauBar status panel: hub, nodes, spend, approvals](025-taubar-status-panel.md) | AFK | 009, 011, 024 |
| 026 | [Telegram voice notes transcribed on the hub](026-telegram-voice-notes.md) | AFK | 014, 075 |
| 027 | [Claude Code "waiting for you" notification on Telegram](027-claude-code-waiting-notification.md) | AFK | 014 |
| 028 | [tau as an MCP server for Claude Code](028-tau-mcp-server.md) | AFK | 020, 021 |
| 029 | [Ambient mode: off by default, switchable profiles](029-ambient-mode-profiles.md) | AFK | 011, 019, 025 |
| 030 | [Pick the "Hey tau" wake phrase and record samples](030-pick-wake-phrase.md) | HITL | – |
| 031 | ["Hey tau": local wake word on top of tau-voice](031-hey-tau-voice.md) | AFK | 009, 024, 030, 075 |
| 074 | [tau-web: the TUI in the browser through `textual-serve`, served by the hub](074-tau-web-textual-serve.md) | AFK | – |
| 075 | [tau-voice: push-to-talk from the TUI with local speech-to-text and text-to-speech](075-tau-voice-push-to-talk.md) | AFK | 054 |
| 080 | [Voice from the phone: browser microphone in the web UI, transcribed on the hub](080-voice-from-the-phone.md) | AFK | 074, 075 |

Live status: `python3 roadmap/board.py --layer L4`
