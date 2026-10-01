# 190 · Public downloads for the tau app and its updates

Status: needs-triage
Type: AFK
Layer: L8 · Distribution
Packages: .github, apps/tau, cloud/universe
Blocked by: 170

## What to build

The app's release assets (`tau.dmg`, the updater's `latest.json` and `.app.tar.gz`) are attached to GitHub releases, and the updater and `/download` point there. The repository is private for now, so nobody without access can download them, and the updater cannot reach them either.

Serve them from a public place that does not depend on the repository's visibility:

- CI uploads the signed assets to an R2 bucket on each release tag.
- The universe serves them at `https://tau.getporti.com/download/tau.dmg` and `…/latest.json`, through an R2 binding or a public bucket on a subdomain.
- The updater endpoint and the download page use those URLs.
- GitHub releases keep the copies.

## Acceptance criteria

- [ ] A tag puts `tau.dmg` and `latest.json` where a signed-out visitor can download them; the updater updates from there
- [ ] `/download`, the app guide and `tau setup`'s app step use the public URL

## Comments

- 2026-10-01: found by issue 175. The repository is private, so the GitHub release links do not work for visitors.
