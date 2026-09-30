# 162 · Hosted taus on the network and in the universe

Status: ready-for-agent
Type: AFK
Layer: L9 · Cloud mode and the tau network
Packages: cloud/host, cloud/shared
Blocked by: 158, 159

## What to build

[ADR 0013](../../docs/adr/0013-hosted-taus-handles-and-public-pages.md) §4. Each hosted tau gets keys in its `Tau` object (sealed by the vault), a card at `/@<handle>/.well-known/tau.json` and an inbox at `/@<handle>/net/inbox` with the spine's checks and limits. Delivered envelopes are opened in the `Tau` object and handled like tau-net: contacts state machine with key pinning, network turns (persona + public note, no profile, no tools, no approvals, hops and hourly caps, `[no reply]`), public sub-tau routing via `sub`. The app gets contacts (add by address, accept, block), a network log, and `net_send` as a tier-2 tool with an approval card. Universe join/report/leave signed with the tau's key (toggle in the app; the sign-up asks explicitly, nothing preselected).

## Acceptance criteria

- [ ] A hosted tau and a local hub (two-process test or recorded vectors) exchange a contact request, accept and messages both ways
- [ ] A hosted tau's public sub-tau answers `<host>/@h/coach` from a hub; a private one is dropped
- [ ] Universe join/report from the app; the snapshot lists the hosted tau with its handle

## Blocked by

- [158 · shared net](158-shared-net-typescript.md)
- [159 · tau-host core](159-tau-host-core.md)

## Comments

- 2026-09-30: filed with ADR 0013.
