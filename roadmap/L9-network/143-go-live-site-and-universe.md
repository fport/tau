# 143 · Go live: `tau.getporti.com`, the owner's tau in the universe, the docs

Status: done
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

- [x] `https://tau.getporti.com/` and `/universe` serve the site; `/api/universe` lists the owner's tau
- [x] A message and its auto-reply went both ways between two deployed spines
- [x] `https://docs.tau.getporti.com/` has the tutorial and the new reference pages
- [x] No test tau is left listed or deployed

## Blocked by

- [140 · Public site](140-public-site-universe.md)
- [141 · Universe client](141-universe-client.md)
- [142 · Spine kit](142-spine-kit.md)

## Comments

- 2026-09-30: opened with ADR 0010.
- 2026-09-30: done.
  - **The public site.** https://tau.getporti.com and `/universe` are live on the `tau-universe` Worker with the custom domain. The CSP, nosniff and Referrer-Policy headers were checked. The landing page's set-up buttons open the tutorial.
  - **The owner's tau.** `furkan.tau.getporti.com` (095) joined the universe with `--owner Furkan`, and `/api/universe` lists it: 1 of 1 tau, online.
  - **The live exchange.** It ran between the owner's spine and a temporary kit-deployed spine; see 095. The test Worker and its KV namespace are deleted, and it was never listed.
  - **The docs.** https://docs.tau.getporti.com has the tutorial, the local-trial page, the network guide with the kit, and the ADR 0010 and universe reference pages. Every one of them answers 200.
  - **Owner's step.** Restart the hub from TauBar so its `net` service polls the live spine and reports to the universe every hour; `tau net status` then shows `polling`.
