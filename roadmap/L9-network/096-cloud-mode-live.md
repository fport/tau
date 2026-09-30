# 096 · Run tau in cloud mode live: Workers Paid, image build, secrets, Telegram from the container

Status: ready-for-human
Type: HITL
Layer: L9 · Cloud mode and the tau network
Packages: cloud/spine, tau-cloud
Blocked by: 094

## What to build

The first live cloud-mode tau. Steps for the user:

1. Prepare the account and the machine:
   - Switch the Cloudflare account to Workers Paid (Containers need it).
   - Start Docker Desktop.
2. Configure and deploy:
   - `cd cloud/spine && pnpm run configure --cloud --force`
   - Set `SPINE_URL` in `wrangler.jsonc`.
   - `pnpm run deploy:cloud`
3. Set the container secrets with `wrangler secret put`: `HUB_TOKEN`, model credentials, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_CHAT_IDS`, `TAU_NET_IDENTITY`.
4. From the machine that has `tau.toml` and `persona/`, run `uv run tau cloud push` (confirm `user.md`), then `uv run tau cloud status`.
5. Talk to tau on Telegram, restart the container, and check that the session resumes.

## Acceptance criteria

- [ ] (user) The container runs, `tau cloud status` shows the brain healthy
- [ ] (user) Telegram answers from the cloud tau, including a tier-2 approval through the buttons
- [ ] (user) After a container restart the conversation resumes from D1
- [ ] (user) The monthly cost estimate from the Cloudflare dashboard is written under Comments

## Blocked by

- [094 · tau-cloud](094-tau-cloud.md)

## Comments

- 2026-09-30: opened with ADR 0007.
