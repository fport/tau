# 146 · The public site explains how tau works, in English and Turkish

Status: in-progress
Type: AFK
Layer: L9 · Cloud mode and the tau network
Packages: cloud/universe
Blocked by: none

## What to build

A "How it works" page on `tau.<domain>` that a newcomer understands without the docs. It goes in two steps:

1. **What you do on your own machine.** The brain at home; talking through the terminal, TUI and Telegram; approvals.
2. **What taus do with each other.** The spine as a mailbox, the card as an ID card, envelopes as signed and locked letters, contacts, narrow automatic answers, the universe as a shop window, and sub-taus as specialists.

It uses concrete examples, for instance "your tau asks Bob's tau when Bob is free on Friday". It also has a short "Can I be hacked?" section that is honest about what an attacker gets.

The whole site becomes bilingual: English at `/`, `/universe`, `/how-it-works`, and Turkish under `/tr/…`. A language switcher sits on every page, and the universe page's script strings are translated too. Accept-Language may pick the start page once; the explicit switcher always wins.

## Acceptance criteria

- [ ] `/how-it-works` and `/tr/how-it-works` exist, with the two steps, the examples and the security section; linked from the landing page and the nav
- [ ] Every page has an EN/TR switcher; the Turkish pages are complete and correct
- [ ] The CSP and tests stay green; the pages work at 360 px

## Blocked by

None - can start immediately.

## Comments

- 2026-09-30: opened at the owner's request.
