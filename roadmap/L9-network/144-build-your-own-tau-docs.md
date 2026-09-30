# 144 · Docs: build your own tau from zero, verified on a clean home

Status: done
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

- [x] The tutorial is in the nav as the first getting-started page, and `mkdocs build --strict` passes
- [x] Every command in it was run on a clean home; where the live site differs (URLs), the local equivalent is named
- [x] No personal value anywhere; example addresses only

## Blocked by

- [141 · Universe client](141-universe-client.md)
- [142 · Spine kit](142-spine-kit.md)

## Comments

- 2026-09-30: opened with ADR 0010.
- 2026-09-30: done.
  - Commits: 96bd844..df69b30, 53975ed, 8be5c91.
  - `getting-started/build-your-own-tau.md` has the 12 sections. `getting-started/try-locally.md` covers two taus, two kit spines under `wrangler dev` and the fake model, with no account. The network guide uses the kit first, the backups guide includes `net/`, and the CLI reference matches the real `--help`.
  - Every command was run on a clean home, and the `<!-- verified: … -->` markers in the page source say which. The live deploy and universe steps came from the code and were exercised against the fakes; the owner's own live run (095, 143) covered them for real.
  - The rough edges found while writing were fixed in 53975ed: the public note is now created by `tau net init`, universe retries jump ahead, the local-peer hint names `TAU_NET_ALLOW_INSECURE`, and the hop log and publish help are clearer.
