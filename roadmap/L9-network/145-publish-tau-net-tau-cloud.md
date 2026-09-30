# 145 · Publish tau-net and tau-cloud on PyPI

Status: ready-for-human
Type: HITL
Layer: L9 · Cloud mode and the tau network
Packages: tau-net, tau-cloud, .github
Blocked by: 142

## What to build

tau-core and tau-tui are on PyPI already. tau-net and tau-cloud need their pending publishers before the first tag can publish them. This repository is private, so the tutorial's install path (`uv tool install tau-core --with tau-tui --with tau-net`) works for other people only after this.

Steps for the user: on pypi.org, add a pending trusted publisher for `tau-net` and for `tau-cloud`, with the workflow and environment names given in the header of `.github/workflows/release.yml` (142). Then push a version tag.

## Acceptance criteria

- [ ] (user) Both pending publishers exist
- [ ] (user) A tag published tau-net and tau-cloud; `uv tool install tau-core --with tau-tui --with tau-net` works on a clean machine and `tau net spine init` finds the kit

## Blocked by

- [142 · Spine kit](142-spine-kit.md)

## Comments

- 2026-09-30: opened with ADR 0010.
