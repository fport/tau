# 102 · Deploy a spine without cloning the repo

Status: needs-triage
Type: AFK
Layer: L9 · Cloud mode and the tau network
Packages: cloud/spine, tau-net, tau-cloud
Blocked by: 078, 092

## What to build

Someone who installs tau from PyPI (`uv tool install tau-core --with tau-tui --with tau-net`) should be able to deploy a spine without cloning this repo. Options to decide in triage:

- publish `tau-spine` to npm and document `npm create`;
- ship the built Worker bundle and the migrations inside `tau-net` and add `tau setup spine`, which writes a `wrangler.jsonc` into a directory of the user's choice and runs `npx wrangler deploy`;
- a Cloudflare "Deploy to Workers" button.

The cloud-mode image likewise installs from PyPI instead of the workspace.

## Acceptance criteria

- [ ] A clean machine with only the PyPI packages and Node can deploy a spine and join the network by following the guide
- [ ] The container image can be built from PyPI releases

## Blocked by

- [078 · PyPI release path](../L8-distribution/078-pypi-release-path.md)
- [092 · Spine Worker](092-spine-worker.md)

## Comments

- 2026-09-30: filed with ADR 0007.
- 2026-09-30: the spine part is done by 142 (the kit in the tau-net wheel, `tau net spine init|deploy`). What remains here is the cloud-mode brain image built from PyPI releases instead of the workspace.
