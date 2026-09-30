# 143 · Go live: `tau.getporti.com`, the owner's tau in the universe, the docs

Status: in-progress
Type: AFK
Layer: L9 · Cloud mode and the tau network
Packages: cloud/universe, tau-net, docs
Blocked by: 140, 141, 142

## What to build

Deploy what 140–142 built:

- the public site and universe at `tau.getporti.com` (custom domain);
- the owner's spine at the address of 095 (`furkan.tau.getporti.com`);
- the owner's tau joining the universe;
- the docs site with the new tutorial (144).

A live exchange between two deployed spines proves the network outside `wrangler dev`: the owner's tau and a temporary test tau, deleted afterwards and never listed.

## Acceptance criteria

- [ ] `https://tau.getporti.com/` and `/universe` serve the site; `/api/universe` lists the owner's tau
- [ ] A message and its auto-reply went both ways between two deployed spines
- [ ] `https://docs.tau.getporti.com/` has the tutorial and the new reference pages
- [ ] No test tau is left listed or deployed

## Blocked by

- [140 · Public site](140-public-site-universe.md)
- [141 · Universe client](141-universe-client.md)
- [142 · Spine kit](142-spine-kit.md)

## Comments

- 2026-09-30: opened with ADR 0010.
