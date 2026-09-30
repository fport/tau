# 174 · Deploy a spine without Node: the Cloudflare API with a scoped token

Status: ready-for-agent
Type: AFK
Layer: L9 · Cloud mode and the tau network
Packages: tau-net
Blocked by: –

## What to build

[ADR 0014](../../docs/adr/0014-one-installer-and-onboarding.md) §4.

`tau net spine deploy` gains an API path that needs no Node, bun or Wrangler:

- **The token.** It opens Cloudflare's token page pre-filled with the scopes the spine needs (Workers Scripts, Durable Objects, KV, custom domains, rate limits), and takes the token at a hidden prompt. The token is stored in `.env` as `CLOUDFLARE_API_TOKEN`, never in argv.
- **The deploy.** It uploads the kit's pre-bundled `worker.js` with its metadata (bindings, migrations, compatibility date, rate limits), sets `HUB_TOKEN` as a secret and adds the custom domain or the workers.dev route.
- **Wrangler stays** as the other path. Tests use a fake Cloudflare API.

## Acceptance criteria

- [ ] A deploy through the fake API sends exactly the documented requests; secrets never reach argv or logs
- [ ] `docs/guides/tau-network` and `build-your-own-tau` (EN + TR) show the no-Node path first

## Comments

- 2026-10-01: filed with ADR 0014.
