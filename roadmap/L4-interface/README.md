# L4 · Interface

**Goal:** More ways to talk to tau: TauBar, the web app (an agentic chat with widgets, served by the hub and by tau-host, [ADR 0015](../../docs/adr/0015-web-app-agentic-chat.md)), tau-voice (push-to-talk, Telegram voice notes, voice from the phone, "Hey tau"), Claude Code integration and ambient mode.

**Done when:** TauBar controls sleep and shows status, the web app chats, renders widgets and drives routines, tasks and devices from the browser behind Access or on the tailnet, voice works at the desk, on Telegram and from the phone without audio leaving the hub, and ambient mode can be switched on per profile.

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
| 074 | [tau-web: the TUI in the browser through `textual-serve`, served by the hub](074-tau-web-textual-serve.md) *(wontfix)* | AFK | – |
| 075 | [tau-voice: push-to-talk from the TUI with local speech-to-text and text-to-speech](075-tau-voice-push-to-talk.md) | AFK | 054 |
| 080 | [Voice from the phone: browser microphone in the web UI, transcribed on the hub](080-voice-from-the-phone.md) | AFK | 075, 179 |
| 084 | [TauBar runs the hub: on/off switch, restart after a crash, launch at login](084-taubar-runs-the-hub.md) | AFK | 024 |
| 085 | [Start or restart the hub TauBar supervises from the phone](085-start-taubar-hub-from-the-phone.md) | AFK | 084 |
| 086 | [TauBar follows the UI language setting](086-taubar-ui-language.md) | AFK | 024 |
| 088 | [Opening TauBar again does not show its window](088-taubar-reopen-shows-no-window.md) | AFK | – |
| 089 | [A nicer TauBar menu and settings window](089-taubar-ui-polish.md) | AFK | – |
| 091 | [Two TauBar copies can run at once](091-taubar-single-instance.md) | AFK | – |
| 130 | [TauBar's login tests trip the "no personal paths" repo rule](130-taubar-test-paths-trip-the-repo-rule.md) | AFK | – |
| 166 | [TauBar in black and fire: only what is on burns](166-taubar-black-and-fire.md) | AFK | 089 |
| 170 | [One Mac app, "tau": TauBar and tau Desktop merged, built and signed in CI](170-one-mac-app.md) | AFK | – |
| 171 | [The app's first-launch wizard and permissions](171-app-setup-wizard.md) | AFK | 169, 170 |
| 177 | [The turn protocol: JSON turn events and session history shared by the hub and tau-host](177-turn-protocol.md) | AFK | – |
| 178 | [tau-web: the hub's web service with a turn API, paired devices and a web approver](178-tau-web-hub-service.md) | AFK | 177 |
| 179 | [The web app: chat, sessions, tool cards and approvals, served by tau-web](179-web-app-chat.md) | AFK | 178 |
| 180 | [`render_ui`: widgets the model writes, shown in a sandboxed frame](180-render-ui-widgets.md) | AFK | 179 |
| 184 | [The app's control pages: routines, tasks, devices, the toolbox and sub-taus](184-app-control-pages.md) | AFK | 179, 181, 182, 183 |
| 187 | [Widgets that talk back: a message bridge the owner confirms](187-widgets-that-talk-back.md) | AFK | 180 |

Live status: `python3 roadmap/board.py --layer L4`
