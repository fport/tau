# 187 · Widgets that talk back: a message bridge the owner confirms

Status: needs-triage
Type: AFK
Layer: L4 · Interface
Packages: apps/web
Blocked by: 180

## What to build

A widget from 180 can reach nothing. Some widgets are more useful when a button can ask tau something, for example "explain this play" or "add player stats".

Sketch ([ADR 0015](../../docs/adr/0015-web-app-agentic-chat.md) §3):

- The frame gets a second allowed message, `{type: "tau.widget.say", text}`, capped at 2 KB.
- The app puts the text into the composer, marked as coming from a widget, and **the owner sends it**. A widget can never send by itself, call a tool or approve anything.

Decide before building:

- whether rate limits are needed;
- whether a widget's text is framed as untrusted when sent;
- whether hosted taus get it too.

## Acceptance criteria

- [ ] Decision recorded; a widget button fills the composer and nothing is sent without the owner

## Blocked by

- [180 · `render_ui`](180-render-ui-widgets.md)

## Comments

- 2026-10-01: filed with ADR 0015.
