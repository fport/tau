# 180 · `render_ui`: widgets the model writes, shown in a sandboxed frame

Status: ready-for-agent
Type: AFK
Layer: L4 · Interface
Packages: tau-web, apps/web
Blocked by: 179

## What to build

"Render a football scoreboard" becomes a working interface inside the chat ([ADR 0015](../../docs/adr/0015-web-app-agentic-chat.md) §3).

**The tool.**

- `render_ui(title: str, html: str)` is tier 0. tau-web passes it to the agents it builds. It is **not** a `tau.tools` entry point, so the TUI, Telegram and network turns never see it. If `build_agent` has no way to take extra tools, add one to its public API.
- The tool description tells the model three things:
  - the document is self-contained, with inline CSS and JS;
  - it has no network, no external scripts and no fonts from the web;
  - it can use the injected theme variables.
- `html` is capped at 256 KB, and a larger one is refused with a clear message. The tool returns "rendered" to the model.
- The stream emits a `widget` event. History renders the widget from the stored tool input.

**The frame.**

- `<iframe sandbox="allow-scripts" srcdoc=… allow="" referrerpolicy="no-referrer">`, with no `allow-same-origin`, forms, popups or top navigation.
- Before the model's markup, the app prepends a CSP `<meta>`: `default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: blob:; font-src data:; connect-src 'none'; form-action 'none'`.
- It also prepends a `:root` block with the app's theme variables, and a tiny size reporter.
- The parent accepts exactly one message from the frame: `{type: "tau.widget.size", height: number}`, from that frame's `contentWindow`, clamped between 80 px and 80 vh. Everything else is ignored.
- The app's own CSP allows `frame-src 'self' about:srcdoc` and nothing wider.

**Card chrome.**

- The widget card has a title, a reload button that re-renders from the stored HTML, "open full width", and "copy HTML".
- Widgets from sessions that other people could have fed (network sessions) are never rendered. The app shows "widget not shown" there.

## Acceptance criteria

- [ ] Asked for a scoreboard, the brain calls `render_ui` and the chat shows a working widget (clicks, timers) in the frame
- [ ] A browser test shows the frame cannot `fetch`, open a WebSocket, load a remote image, read `document.cookie` of the app, reach `parent.document`, navigate the top window or open a popup
- [ ] Any message other than a well-formed size message is ignored; a size outside the bounds is clamped
- [ ] Reopening the session re-renders the widget from history; a widget over 256 KB is refused with a message the model reads
- [ ] `render_ui` is absent from the TUI's `/tools` and from Telegram and network turns

## Blocked by

- [179 · The web app](179-web-app-chat.md)

## Comments

- 2026-10-01: filed with ADR 0015. Supersedes 152. Widgets that talk back are 187.
