# 142 · Spine kit: `tau net spine init|deploy` from the tau-net wheel

Status: in-progress
Type: AFK
Layer: L9 · Cloud mode and the tau network
Packages: tau-net, cloud/spine, .github
Blocked by: none

## What to build

`docs/reference/tau-universe.md` §4:

- `cloud/spine`'s `pnpm run kit` bundles the Worker, its migrations and a local-mode Wrangler template into `tau_net/spine_kit/`.
- The kit ships in the wheel, and CI checks that it is in sync with the source.
- `tau net spine init DIR [--address HOST]` writes a deployable project.
- `tau net spine deploy DIR` logs in, deploys, applies the migrations, sets `HUB_TOKEN` from the hub's `.env` through stdin, and writes `TAU_SPINE_URL` back.
- `release.yml` also publishes `tau-net` and `tau-cloud`.

This covers the local-mode part of 102.

## Acceptance criteria

- [ ] The built wheel contains the kit; `init` + `npx wrangler deploy --dry-run` succeeds in a fresh directory
- [ ] `deploy` never puts the token in argv or output (tests with a fake runner)
- [ ] CI fails when the kit is stale
- [ ] `release.yml` builds, smoke-tests and publishes tau-net and tau-cloud with trusted publishing

## Blocked by

None - can start immediately.

## Comments

- 2026-09-30: opened with ADR 0010.
