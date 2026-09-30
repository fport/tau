# 170 · One Mac app, "tau": TauBar and tau Desktop merged, built and signed in CI

Status: ready-for-agent
Type: AFK
Layer: L4 · Interface
Packages: apps/taubar, apps/tau-desktop, .github
Blocked by: –

## What to build

[ADR 0014](../../docs/adr/0014-one-installer-and-onboarding.md) §3, §4, §6.

- **One app.** TauBar (the menu bar and the hub's supervisor) and tau Desktop (chat windows running `tau tui` in a PTY) become one Tauri app named "tau": the menu bar item plus windows. The bundle id and the migration of existing installs are decided here.
- **CI builds it** on each release tag: a universal `tau.dmg`, attached to the GitHub release, plus a `latest.json` for the updater.
- **Signing.** Every build is signed with one stable self-signed code-signing identity kept as a CI secret, so macOS keeps camera and notification permissions across updates. The build is not notarised yet.
- **Download page.** `tau.getporti.com/download` in the site's style (EN + TR) explains the first-open warning.

## Acceptance criteria

- [ ] The app runs the menu bar and chat windows; the guard's camera permission belongs to it
- [ ] A tag produces `tau.dmg` in the release; an update keeps the camera permission (checked by hand once)
- [ ] The download page and `docs/guides/taubar` (EN + TR) describe install and first open

## Comments

- 2026-10-01: filed with ADR 0014.
