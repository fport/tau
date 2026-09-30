# 150 · Public sub-taus over the network and in the universe

Status: done
Type: AFK
Layer: L9 · Cloud mode and the tau network
Packages: tau-net, cloud/universe
Blocked by: 149, 105, 146

## What to build

The network half of ADR 0012:

- **Addressing.** A contact reaches a public sub-tau as `<address>/<name>`, through an optional `sub` field in the signed `message` payload.
- **Answers.** The hub routes it to the sub-tau's narrow network turn: its persona and its public note, no tools, the same limits. It drops messages for private or unknown sub-taus.
- **Universe reports** list public sub-taus (`{name, about}`), and the universe page draws them inside the owner's hull, like tiny's builders and tinys.

## Acceptance criteria

- [x] `tau net send alice.example.com/coach "…"` reaches Alice's public `coach`; a private one is dropped and logged
- [x] The universe snapshot carries `subs` per tau; the page shows them as small nodes in the owner's hull and in the tau cards
- [x] Protocol pages updated (`tau-network.md`, `tau-universe.md`)
- [x] Cloud mode: the brain image installs tau-sub; `tau cloud push|pull` carry `persona/subs/*.md`

## Blocked by

- [149 · Sub-taus](149-sub-taus.md)
- [105 · Free plan link](105-spine-free-plan-link.md)
- [146 · Site](146-site-how-it-works-bilingual.md)

## Comments

- 2026-09-30: opened with ADR 0012.
- 2026-09-30: done.
  - Protocol: an optional `sub` in the sealed `message` content (the signed header is unchanged, so spines never see it and older hubs answer as the main tau). It names a sub-tau of the tau that received the thread's first envelope: an even `hops` addresses the receiver's sub-tau, an odd one is the sender's sub-tau answering. Replies carry the same `sub`, so a thread stays with `/coach`.
  - tau-net finds sub-taus through the new entry-point group `tau.subs` (tau-sub provides `tau_sub.network:public_subs`); neither package imports the other.
  - Universe: reports carry `subs: [{name, about}]` (public only, at most 20, left out when empty); the Worker stores them per tau (schema v2) and the page draws them inside the owner's hull and as chips on the cards.
  - Cloud mode: the spine keeps `persona/subs/<file>.md` (plus `DELETE /hub/files/<name>`), `tau cloud push|pull|run` carry them, the brain image installs tau-sub, and the container gets `OPENAI_API_KEY`, `GEMINI_API_KEY` and `GOOGLE_API_KEY` (153).
  - Checked locally with two kit spines, two hubs on the fake model and a local universe: `127.0.0.1:8862/coach` answered on its own role and session, the thread stayed with `/coach` up to `max_hops`, `/diary` (private) and `/nobody` were dropped, and `/api/universe` listed Bob's `coach`.
  - To deploy: the universe Worker, the regenerated spine kit (with tau-net), and the owner's spine and brain image for cloud mode.
