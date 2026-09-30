# 165 · Go live: hosted taus on `tau.getporti.com`

Status: in-progress
Type: HITL
Layer: L9 · Cloud mode and the tau network
Packages: cloud/host, cloud/universe
Blocked by: 159, 160, 161, 162, 163

## What to build

The owner creates the GitHub OAuth App (callback `https://tau.getporti.com/auth/callback`) and hands over the client id; the secrets `GITHUB_CLIENT_SECRET`, `VAULT_KEY` and `UNIVERSE_IDENTITY` are set with `wrangler secret put`; tau-host is deployed without a route of its own, the universe gets the `HOST` service binding and is redeployed; the owner's spine is redeployed from the new kit; the owner signs in, claims `@<their handle>` for their local tau and publishes one web sub-tau.

## Acceptance criteria

- [ ] Sign-in, key, chat and a web sub-tau work on `tau.getporti.com`
- [ ] The owner's local tau has its handle page; a visitor chat reaches the local hub

## Blocked by

- 159, 160, 161, 162, 163

## Comments

- 2026-09-30: filed with ADR 0013.
- 2026-09-30: live in part. The owner created the GitHub OAuth App and set `GITHUB_CLIENT_SECRET`. The orchestrator did the rest:
  - generated `VAULT_KEY` (a gitignored file, uploaded by stdin; the owner keeps an offline copy);
  - deployed tau-host (no route of its own, `workers_dev` off, `PUBLIC_HOST=tau.getporti.com`, `SIGNUP` limited to the owner, the `UNIVERSE_SERVICE` binding);
  - bound the universe to it with `HOST` and redeployed it with its identity secret;
  - redeployed the owner's spine from the 0.2.0 kit.

  The owner signed in on tau.getporti.com, pasted a key and chatted. Still to check: a web sub-tau and its visitor chat, the owner's claim for the local tau, and opening sign-ups.
