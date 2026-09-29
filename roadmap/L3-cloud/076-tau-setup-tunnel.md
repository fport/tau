# 076 · `tau setup tunnel` and `infra/tunnel`: cloudflared, Access policy, Tailscale Serve, doctor checks

Status: ready-for-agent
Type: AFK
Layer: L3 · Access and data
Packages: tau-core, infra/tunnel
Blocked by: 022

## What to build

The safe-to-script part of the private deployment (ADR 0006 §1 and §8) as a `tau setup` command group in tau-core (a `tau.commands` entry point `setup`) plus `infra/tunnel/`:

- `tau setup tunnel`: checks for `cloudflared` and, if missing, prints the install command for the platform (Homebrew on macOS, apt on the RPi5) and asks before running it; creates the tunnel (`cloudflared tunnel create tau`) using the token from 013, writes `<home>/tunnel/config.yml` from a template (ingress: `tau.<domain>` → `http://127.0.0.1:<web port>` from `[component.web]`, catch-all 404), creates the DNS route for the hostname, creates the Access application for it with one policy (allow the owner's email through one-time PIN, optional device rule) through the Cloudflare API, and installs `cloudflared` as a launchd or systemd service (templates in `infra/services/`). Idempotent: re-running updates in place and never duplicates; `--dry-run` prints every call with example values; `--remove` tears everything down.
- `tau setup serve`: the no-domain alternative: `tailscale serve` for the same loopback port in the background, prints the tailnet URL; `--off` removes it.
- `tau doctor` gains checks: `cloudflared` installed and its service running, tunnel connector healthy, Access application present for the hostname, `tailscale serve` status when used, and no listening socket outside loopback and the tailnet (a non-loopback bind of the web service is a failure).
- `infra/tunnel/README.md`: what the command does, the Access policy in words, how to revoke access, and the manual dashboard path for people who prefer clicking. Example values only; ids and hostnames go to `.env` (`TAU_PUBLIC_HOSTNAME`, `CLOUDFLARE_TUNNEL_ID`, `CLOUDFLARE_ACCESS_AUD`), names in `.env.example`.
- The Cloudflare API and the `cloudflared`/`tailscale` binaries sit behind interfaces with fakes; tests never touch the network.

## Acceptance criteria

- [ ] `tau setup tunnel --dry-run` prints the full plan with example values; the real run creates tunnel, DNS route, Access application and policy and is idempotent (fakes in tests, one live run by the user during 023)
- [ ] The ingress config points only at the web UI's loopback port with a catch-all 404; it lives under `<home>`, never in the repo
- [ ] `tau setup serve` publishes the same port on the tailnet and `--off` undoes it
- [ ] `tau doctor` reports the tunnel, Access, Tailscale Serve and listening-socket checks; a non-loopback bind fails the check
- [ ] `infra/tunnel/README.md` and the service templates exist; `.env.example` lists the new names; nothing personal in tracked files

## Blocked by

- [022 · Move the getporti domain's DNS to Cloudflare](022-move-dns-to-cloudflare.md)

## Comments

- 2026-09-29: opened for ADR 0006 (private-first), §1 (one public surface through Tunnel + Access, Tailscale Serve without a domain) and §8 (`tau setup <thing>` helpers where a script is safe). 023 uses this to go live.
