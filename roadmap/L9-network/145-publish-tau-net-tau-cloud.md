# 145 · Publish tau-net and tau-cloud on PyPI

Status: done
Type: HITL
Layer: L9 · Cloud mode and the tau network
Packages: tau-net, tau-cloud, .github
Blocked by: 142

## What to build

tau-core and tau-tui are on PyPI already. tau-net and tau-cloud need their pending publishers before the first tag can publish them. This repository is private, so the tutorial's install path (`uv tool install tau-core --with tau-tui --with tau-net`) works for other people only after this.

Steps for the user: on pypi.org, add a pending trusted publisher for `tau-net` and for `tau-cloud`, with the workflow and environment names given in the header of `.github/workflows/release.yml` (142). Then push a version tag.

## Acceptance criteria

- [x] (user) Both pending publishers exist
- [x] (user) A tag published tau-net and tau-cloud; `uv tool install tau-core --with tau-tui --with tau-net` works on a clean machine and `tau net spine init` finds the kit

## Blocked by

- [142 · Spine kit](142-spine-kit.md)

## Comments

- 2026-09-30: opened with ADR 0010.
- 2026-09-30: found while writing the tutorial (144). The source `tau-core` still says 0.3.1 but has moved on a lot since the PyPI 0.3.1 (for example `tau proxy`, and the template `tau init --provider fake` writes). Bump and release tau-core (and tau-tui) in the same tag as the first tau-net and tau-cloud.
  - `tau net init/status` and `tau net spine init` were checked against PyPI tau-core 0.3.1 and work.
  - The pending publishers to create: `tau-net` with environment `pypi-net`, and `tau-cloud` with `pypi-cloud`. The repository is `fport/tau` and the workflow `release.yml`; `docs/contributing/release.md` has the steps.
- 2026-10-01: done.
  - The owner added pending publishers for tau-net (`pypi-net`), tau-cloud (`pypi-cloud`) and tau-sub (`pypi-sub`); release.yml now publishes tau-sub too.
  - The v0.4.0 tag, cut by the guard session, published tau-core and tau-tui 0.4.0 and, for the first time, tau-net, tau-cloud and tau-sub 0.1.0, with `tau-core>=0.4.0` floors.
  - Checked in an isolated uv tool dir: `uv tool install tau-core --with tau-tui --with tau-net --with tau-sub` gives those versions, and `tau net spine init` writes the kit.
  - tau-guard waits for its own pending publisher, because PyPI allows three pending ones at a time; its publish job is rerun after that.
