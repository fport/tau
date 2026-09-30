# 092 · Spine Worker: card, sealed mailbox and hub long poll, locally and deployed

Status: in-progress
Type: AFK
Layer: L9 · Cloud mode and the tau network
Packages: cloud/spine
Blocked by: none

## What to build

`cloud/spine` is the `tau-spine` Worker (TypeScript, pnpm) of ADR 0007. It implements §1–§5 of `docs/reference/tau-network.md`:

- the card at `/.well-known/tau.json`;
- `POST /net/inbox`, which verifies the sender's signature against the sender's card and stores only sealed envelopes (checks, rate limit and mailbox cap as specified);
- the hub API (`/hub/health`, `/hub/card`, `/hub/updates` as a long poll woken by the `HubSignal` Durable Object, `/hub/ack`);
- the cloud-mode store routes (state, files, sessions, brain), gated by `TAU_MODE=cloud`;
- a cron that prunes the mailbox and keeps the brain container awake in cloud mode.

The configuration and the deploy flow:

- Tracked example configurations carry no resource ids: `wrangler.example.jsonc` for local mode (Free plan) and `wrangler.cloud.example.jsonc` for cloud mode (with the `TauBrain` container).
- `pnpm run configure` writes the gitignored `wrangler.jsonc` and `.dev.vars`.
- `pnpm dev` runs the spine locally. `pnpm run deploy` provisions KV and D1 on the first deploy and applies the D1 migrations.

## Acceptance criteria

- [ ] Every row of the reference's inbox and hub tables is covered by a vitest test in workerd (`pnpm test`), including the §3 test vector
- [ ] `pnpm dev` runs without Docker and without a Cloudflare account; two spines on 8787/8788 exchange a signed dev envelope
- [ ] `wrangler deploy --dry-run` passes for the local-mode config
- [ ] Cloud routes answer `404 cloud_mode_off` in local mode; the local-mode spine never stores contacts or plaintext
- [ ] `cloud/spine/README.md` covers local dev, two local spines, deploy in both modes, secrets and costs; no personal value in any tracked file

## Blocked by

None - can start immediately.

## Comments

- 2026-09-30: opened with ADR 0007; built together with 093 against the reference page.
