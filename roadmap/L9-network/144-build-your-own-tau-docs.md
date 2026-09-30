# 144 · Docs: build your own tau from zero, verified on a clean home

Status: ready-for-agent
Type: AFK
Layer: L9 · Cloud mode and the tau network
Packages: docs
Blocked by: 141, 142

## What to build

A single tutorial on the docs site that takes a newcomer from nothing to a tau of their own that talks to other taus and appears in the universe. It links the existing guides for the details. The steps:

1. prerequisites;
2. install from PyPI;
3. `tau init` and model credentials;
4. first conversation (terminal and TUI);
5. run the hub as a service;
6. Telegram;
7. deploy your spine with `tau net spine init|deploy`;
8. `tau net init` and publish;
9. add a contact and talk;
10. join the universe;
11. back up the identity.

Cloud mode appears as an advanced option for owners without a machine at home. Every command is run once on a clean `TAU_HOME` and `TAU_DATA_DIR` while writing, with a fake model and local spine and universe Workers standing in for the live ones; the outputs shown are real ones.

## Acceptance criteria

- [ ] The tutorial is in the nav as the first getting-started page, and `mkdocs build --strict` passes
- [ ] Every command in it was run on a clean home; where the live site differs (URLs), the local equivalent is named
- [ ] No personal value anywhere; example addresses only

## Blocked by

- [141 · Universe client](141-universe-client.md)
- [142 · Spine kit](142-spine-kit.md)

## Comments

- 2026-09-30: opened with ADR 0010.
