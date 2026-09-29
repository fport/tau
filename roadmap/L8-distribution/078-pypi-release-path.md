# 078 · PyPI release path: trusted publishing on tags, version policy, install verified from wheels

Status: ready-for-human
Type: HITL
Layer: L8 · Distribution
Packages: tau-core, tau-tui, .github
Blocked by: none

## What to build

Anyone can `uv tool install tau-core --with tau-tui` (ADR 0006 §8). The 2026-09-29 docs wave scaffolds the workflow: `.github/workflows/release.yml` (a `v<version>` tag builds the sdists and wheels of tau-core and tau-tui, smoke-tests them in a fresh virtualenv and through `uv tool install`, publishes with trusted publishing from the `pypi` environment, and creates the GitHub release), package metadata in the two `pyproject.toml` files, and `docs/contributing/release.md` with the version policy (tau-core and tau-tui released in lockstep with one version; `0.x` until L3 ships). This issue makes it real.

Human steps first (nothing can be published without them):

1. On PyPI, add a pending trusted publisher for `tau-core` and again for `tau-tui`: the repository of this repo, workflow `release.yml`, environment `pypi`.
2. In the GitHub repository, create the `pypi` environment (Settings → Environments); optionally add the owner as a required reviewer so a tag waits for a click before the upload.
3. Then set this issue to `ready-for-agent`.

Agent work after that:

- Run `release.yml` by hand as a dry run and fix anything it finds; cut the first release (`v0.2.x` or the next version, the tag matching `packages/tau-core/pyproject.toml`) and watch the publish and release jobs.
- Verify the documented install from PyPI in a clean environment: `uv tool install tau-core --with tau-tui`, then `tau version`, `tau init --yes --provider fake`, `tau doctor`, one `tau chat` turn with the fake provider.
- Check the PyPI pages (README rendered, links to docs, source and changelog work, classifiers present) and fix the metadata if not.
- Record in `docs/contributing/release.md` how a new package (`tau-web`, `tau-voice`, …) joins the release: the workflow's package list, the same version, its own pending publisher.

## Acceptance criteria

- [ ] (user) Pending trusted publishers exist on PyPI for `tau-core` and `tau-tui` (workflow `release.yml`, environment `pypi`); the `pypi` GitHub environment exists
- [ ] A `v<version>` tag publishes both packages to PyPI from CI with no stored token, and the GitHub release carries the built files
- [ ] `uv tool install tau-core --with tau-tui` in a clean environment gives a working `tau` (`tau version`, `tau init`, `tau doctor`, one `tau chat` turn with the fake provider), verified from the published wheels
- [ ] The PyPI pages render the READMEs and their links work; the version policy and the "add a package" steps are in `docs/contributing/release.md`
- [ ] The lockstep version check in the workflow fails a tag whose version does not match `pyproject.toml` (one deliberate dry run proves it)

## Blocked by

None - the human steps come first; the agent part starts once they are ticked.

## Comments

- 2026-09-29: opened for ADR 0006 (private-first), §8 ("installable by anyone"). The workflow, metadata and release notes are scaffolded by the docs wave of the same day; this issue tracks the human setup and the first verified release.
