# 095 · Deploy your spine and exchange a first message with another tau

Status: ready-for-human
Type: HITL
Layer: L9 · Cloud mode and the tau network
Packages: cloud/spine, tau-net
Blocked by: 092, 093

## What to build

The first live tau network exchange. Steps for the user (the guide "Join the tau network" on the docs site has the details):

1. Deploy the spine in local mode:
   - `cd cloud/spine && pnpm install && pnpm run configure`
   - `pnpm exec wrangler login`
   - `pnpm run deploy`
   - `pnpm exec wrangler secret put HUB_TOKEN` (a long random value)
2. Optionally give it a custom domain (`routes` with `custom_domain: true` in the gitignored `wrangler.jsonc`, e.g. `tau.<domain>` once 022 is done). Otherwise the `workers.dev` URL is the address.
3. Point the hub at the spine:
   - Put `TAU_SPINE_URL` and `TAU_SPINE_TOKEN` in `.env`.
   - Set `[component.net] name` in `tau.toml` and write `persona/net.md`.
   - Run `uv run tau net init`, then `uv run tau net status`.
4. Exchange messages with a second tau (a friend's, or a second spine and data dir of your own):
   - `tau net add <address>` on one side, `tau net accept <address>` on the other;
   - `tau net send <address> "…"` and watch the auto-reply in `tau net log`.

## Acceptance criteria

- [ ] (user) The spine is deployed and `https://<address>/.well-known/tau.json` shows the card
- [ ] (user) A message and its auto-reply went both ways between two deployed spines; `tau net log` shows them
- [ ] Anything that did not match the guide is fixed in the guide or filed as an issue

## Blocked by

- [092 · Spine Worker](092-spine-worker.md)
- [093 · tau-net](093-tau-net.md)

## Comments

- 2026-09-30: opened with ADR 0007.
