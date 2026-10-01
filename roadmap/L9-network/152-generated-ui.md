# 152 · Generated interfaces in the web UI

Status: wontfix
Type: AFK
Layer: L9 · Cloud mode and the tau network
Packages: tau-web
Blocked by: 074

## What to build

A tiny can answer "render a football scoreboard" with a working interface inside its chat. tau could do the same in its web UI (074):

- a sub-tau or the main tau returns a small sandboxed HTML component;
- the web UI renders it in an isolated frame, with no network access and no access to the hub API.

Decide the sandbox and the approval rules (tier) before building.

## Acceptance criteria

- [ ] Decision recorded; a component renders in an isolated frame that cannot reach the hub

## Blocked by

- [074 · tau-web](../L4-interface/074-tau-web-textual-serve.md)

## Comments

- 2026-09-30: filed with ADR 0012; the owner showed tiny's rendered scoreboard as an example.
- 2026-10-01: wontfix, replaced by [180](../L4-interface/180-render-ui-widgets.md). [ADR 0015](../../docs/adr/0015-web-app-agentic-chat.md) §3 records the decision: a tier-0 `render_ui` tool, and a frame with `sandbox="allow-scripts"`, no same origin and `connect-src 'none'`.
