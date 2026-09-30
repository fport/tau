# 095 · Deploy your spine and exchange a first message with another tau

Status: done
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

- [x] (user) The spine is deployed and `https://<address>/.well-known/tau.json` shows the card
- [x] (user) A message and its auto-reply went both ways between two deployed spines; `tau net log` shows them
- [x] Anything that did not match the guide is fixed in the guide or filed as an issue

## Blocked by

- [092 · Spine Worker](092-spine-worker.md)
- [093 · tau-net](093-tau-net.md)

## Comments

- 2026-09-30: opened with ADR 0007.
- 2026-09-30: the owner asked the agent to do it. Per ADR 0010 the address is `furkan.tau.getporti.com`; the second tau for the live exchange is a temporary test spine (143).
- 2026-09-30: done by the agent at the owner's request.
  - **The owner's spine.** It is live at `https://furkan.tau.getporti.com`: custom domain, Workers Free plan, no D1. The first deploy hit the account's D1 limit (10), which moved the local-mode mailbox into the `Mailbox` Durable Object.
    - `HUB_TOKEN` is set, and the hub's `.env` has `TAU_SPINE_URL`/`TAU_SPINE_TOKEN`.
    - The identity is in the data dir, the card is published as "Furkan's tau", and `persona/net.md` holds a minimal public note for the owner to edit.
  - **The second tau.** It was deployed with the spine kit (`tau net spine init|deploy`, Worker renamed to `tau-spine-livetest`) and exchanged a contact request, an accept and messages both ways with the owner's tau. The owner's side answered through the real model (the LiteLLM proxy).
  - **Fixes from the exchange.** The reply came in Turkish to an English message, and a trailing `[no reply]` went out; both were fixed in 03c556e.
  - **Cleanup.** The test contact was removed from the owner's store, and the test Worker and its KV namespace were deleted.
