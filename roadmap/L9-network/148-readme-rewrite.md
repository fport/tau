# 148 · A README a newcomer understands, in English and Turkish

Status: done
Type: AFK
Layer: L9 · Cloud mode and the tau network
Packages: docs
Blocked by: 146, 149

## What to build

tau has grown, and even its owner finds the README hard to follow. Rewrite `README.md` in plain language, in this order:

1. what tau is, in three sentences;
2. what you do on your own machine first;
3. what taus do with each other (the network and the universe);
4. sub-taus;
5. where to go next: the docs tutorial, try locally, and the public site.

Keep a short status table of what works today and what is planned, and move the long details to the docs. Add `README.tr.md` as the Turkish twin, with a language link at the top of both.

## Acceptance criteria

- [x] Both READMEs follow that order and link the live site and docs
- [x] Nothing in them contradicts the docs; no personal value

## Blocked by

- [146 · How it works](146-site-how-it-works-bilingual.md)
- [149 · Sub-taus](149-sub-taus.md)

## Comments

- 2026-09-30: opened at the owner's request.
- 2026-09-30: done.
  - Commits: 7b83fa0, 5005702, 3266771.
  - Structure: what tau is (a Mermaid overview with no LiteLLM node) → first on your own machine → together with other taus (the Alice and Bob example, what the other tau can and cannot see, the universe) → sub-taus → is it safe → where things are (packages, and a status table from the board) → links.
  - `README.tr.md` is its Turkish twin and links the Turkish site and docs pages. Every relative link resolves and every live URL answers 200.
  - Also fixed while merging: the tiers reference lists the Telegram approver, and the private deployment guide and the docs home use `hub.tau.<your-domain>` (ADR 0010).
