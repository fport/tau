# 173 · Remote access in setup: Tailscale and the phone

Status: ready-for-agent
Type: AFK
Layer: L8 · Distribution
Packages: tau-core, infra/remote
Blocked by: 169

## What to build

[ADR 0014](../../docs/adr/0014-one-installer-and-onboarding.md) §5.

A `tau setup` feature:

- It checks that Tailscale is installed and logged in, or explains how to install it.
- It shows the one `sudo` command of `infra/remote/setup.sh` for SSH and mosh, with what it changes, and waits. It never runs `sudo` itself.
- It then runs `infra/remote/doctor.sh`, or the equivalent checks, and prints what to put in Termius.

On Linux the same applies with the distro's packages.

## Acceptance criteria

- [ ] The step reports each check clearly and never runs sudo
- [ ] `docs/guides/phone-tailscale-termius` (EN + TR) points to it

## Comments

- 2026-10-01: filed with ADR 0014.
