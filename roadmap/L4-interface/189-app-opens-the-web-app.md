# 189 · The tau app opens the hub's web app in a window

Status: needs-triage
Type: AFK
Layer: L4 · Interface
Packages: apps/tau
Blocked by: 170, 178, 179

## What to build

[ADR 0015](../../docs/adr/0015-web-app-agentic-chat.md) makes the web app the owner's chat: `apps/web`, served by the hub's `tau-web` on `127.0.0.1:7878`. The tau app ([ADR 0014](../../docs/adr/0014-one-installer-and-onboarding.md)) opens chat windows that run `tau tui` in a PTY. It should also open the web app in a window, next to the TUI windows or instead of them:

- A menu item "New web chat"; the setting decides what ⌘N opens.
- The window loads the hub's `tau-web` origin only, with the same webview restrictions as the chat windows: no devices, no other origins.
- Turns from it are the web channel, with the guard and approvals as ADR 0015 defines them.

## Acceptance criteria

- [ ] A web chat window works against a local hub's `tau-web`; the TUI windows keep working
- [ ] The app guide (EN + TR) describes both kinds of window

## Comments

- 2026-10-01: filed at the web app session's suggestion (ADR 0015 notes the app could show the web app).
