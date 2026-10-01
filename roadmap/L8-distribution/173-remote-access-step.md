# 173 · Remote access in setup: Tailscale and the phone

Status: done
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

- [x] The step reports each check clearly and never runs sudo
- [x] `docs/guides/phone-tailscale-termius` (EN + TR) points to it

## Comments

- 2026-10-01: filed with ADR 0014.
- 2026-10-01: done. As built:
    - **`tau remote`** (tau-core, `tau_core.remote`): `tailscale`, `ssh`, `phone` and `status`, each with `--json` printing one check object. It lives in tau-core because `infra/remote` belongs to this repository, the checks need only the standard library, and `tau setup` offers remote access on a bare install. Everything it reads goes through a `System` that tests replace with a fake: no test runs `tailscale`, `ssh`, `sudo` or a script, or reads the real `/etc/ssh`.
    - **Tailscale:** the CLI on `PATH`, else inside `/Applications/Tailscale.app`; `tailscale status --json` must say `Running`, and the MagicDNS name and the 100.x address are shown. Missing: the download page on macOS (opened on request in the wizard), the official install script shown on Linux. Logged out, off, the daemon down or awaiting approval each get their own instruction.
    - **SSH and mosh:** port 22, the drop-in (`PasswordAuthentication no`, `KbdInteractiveAuthentication no`, every `AllowUsers` entry `<user>@<tailnet or localhost>`), the `Include` line, a live password probe as in `doctor.sh`, mosh, tmux and, on macOS, Homebrew and the `~/.zshenv` block. Otherwise one command, `bash <kit>/setup-all.sh`, with what it changes per platform. The new `infra/remote/setup-all.sh` runs `setup.sh` and `setup-sudo.sh` on macOS and the new `setup-linux.sh` on Linux (the drop-in before openssh-server, mosh and tmux from apt-get, dnf or pacman; `sshd -t` with rollback; the SSH service; it stops over SSH without a key).
    - **Shipping the scripts:** tau-core carries a copy of `infra/remote` (without the README) as package data in `tau_core/remote/kit/`; a test keeps it byte-identical, with the same modes, and another checks it is in the built wheel and sdist. In a checkout the command points at `infra/remote`; an installed tau writes the copy to `$TAU_DATA_DIR/remote/` (0700, `config.local.env` kept) first. Package data rather than a GitHub download: it comes with the release the owner installed, works offline and always matches the running tau.
    - **Phone:** the Termius values from the live state (printed only) and a key in `authorized_keys`, else `add-key.sh`. No QR code: there is no dependency-free encoder, and `values` lets the app draw one.
    - **The engine:** generic check steps (`check = true` in the catalog, `tau_core.setup.checks`). The wizard shows the lines and the action, offers to open its page, and waits: Enter checks again, `skip` goes on; `--yes` reports what needs the owner. JSON mode emits a `check` event and, while the check fails with an action, `needs_ui` with `action` instead of `argv`, stopping with the check first in `pending`. `[feature.configured] command = ["remote", "status"]` makes the feature set up when `tau remote status` exits 0.
    - Docs: the phone guide (EN + TR) leads with `tau setup` → Remote access; `docs/reference/setup.md` specifies check steps and the three checks; `docs/reference/cli.md` (EN + TR) has `tau remote`; the Pi guide, `infra/remote/README.md`, the tau-core README and `CONTEXT.md` (check step) follow.
    - Not run here: `infra/remote/doctor.sh` and the scripts themselves (they need the owner and sudo); `sshd/tau.conf` is unchanged. `setup-linux.sh` is checked with `bash -n` and the drop-in it writes is the same template the tests validate; a first run on a Raspberry Pi is still to be seen.
