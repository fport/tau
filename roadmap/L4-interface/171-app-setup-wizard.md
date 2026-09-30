# 171 · The app's first-launch wizard and permissions

Status: ready-for-agent
Type: AFK
Layer: L4 · Interface
Packages: apps/taubar (the tau app)
Blocked by: 169, 170

## What to build

[ADR 0014](../../docs/adr/0014-one-installer-and-onboarding.md) §2 and §5. On first launch the app shows the wizard over `tau setup`'s JSON protocol (`docs/reference/setup.md`).

1. Language.
2. Installing uv and tau, with progress.
3. The model key, at a hidden field sent on stdin.
4. The features.
5. Permissions: only for the chosen features, each with one sentence of why.
6. Each feature's steps: the guard's enrolment in the app, Telegram pairing, Tailscale, the network.
7. A summary with "talk to tau".

The wizard can be opened again from the menu, and every step can be skipped.

## Acceptance criteria

- [ ] A fresh Mac with only the app reaches a working tau with a real key
- [ ] Permissions are requested only for the chosen features
- [ ] The guard, Telegram and network steps run from the wizard (fakes in tests)

## Comments

- 2026-10-01: filed with ADR 0014.
