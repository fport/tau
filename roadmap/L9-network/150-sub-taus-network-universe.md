# 150 · Public sub-taus over the network and in the universe

Status: ready-for-agent
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

- [ ] `tau net send alice.example.com/coach "…"` reaches Alice's public `coach`; a private one is dropped and logged
- [ ] The universe snapshot carries `subs` per tau; the page shows them as small nodes in the owner's hull and in the tau cards
- [ ] Protocol pages updated (`tau-network.md`, `tau-universe.md`)

## Blocked by

- [149 · Sub-taus](149-sub-taus.md)
- [105 · Free plan link](105-spine-free-plan-link.md)
- [146 · Site](146-site-how-it-works-bilingual.md)

## Comments

- 2026-09-30: opened with ADR 0012.
