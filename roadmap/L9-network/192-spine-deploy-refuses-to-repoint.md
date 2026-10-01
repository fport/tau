# 192 · `tau net spine deploy` refuses to repoint a live spine

Status: ready-for-agent
Type: AFK
Layer: L9 · Cloud mode and the tau network
Packages: tau-net
Blocked by: –

## What to build

A kit project is deployed as the Worker `tau-spine`. When the account already runs a spine under that name for another address, a deploy replaces it. The Durable Object storage stays, so the card's keys stay, but the address, its route and its config change. Peers then reach an inbox that is no longer there. This happened on 2026-10-01: a local test deploy of a kit made for `tau.example.com` replaced the owner's live spine until it was redeployed.

Before uploading, both deploy paths (the API and `--wrangler`) read the deployed Worker's `ADDRESS` and routes or custom domains:

- When the account already has a `tau-spine` serving another address, stop.
- The error names both addresses.
- To go ahead, the owner uses `--replace` (or `--name` to deploy a second spine under another Worker name).
- In `--json` mode this is an `error` event with `reason: "would_replace"`.

## Acceptance criteria

- [ ] A fake API with a deployed spine for another address makes the deploy stop before any write; `--replace` goes through; the same project redeploys without a question
- [ ] The Wrangler path checks the same thing with `wrangler deployments` or the API before `wrangler deploy`

## Comments

- 2026-10-01: filed after a local test replaced the owner's live spine. It was restored within minutes with `cloud/spine`'s `bun run deploy`; keys, storage and the hub token were unchanged.
