# 023 · `tau.<domain>` through Cloudflare Tunnel + Access in front of the hub's web UI, Tailscale Serve as the no-domain default

Status: ready-for-agent
Type: AFK
Layer: L3 · Access and data
Packages: infra/tunnel, tau-web, docs
Blocked by: 022, 074, 076

## What to build

The one public surface of ADR 0006 §1, live. `cloudflared` on the hub (outbound only, installed and configured by `tau setup tunnel` from 076) publishes the web UI (074, bound to loopback) as `tau.<domain>`; a Cloudflare Access application with one policy for the owner's identity (one-time PIN to the owner's email or an IdP, optionally a device rule) sits in front, so unauthenticated requests never reach the tunnel. The hub opens no inbound port. Where there is no domain, `tau setup serve` (Tailscale Serve) publishes the same loopback port to the tailnet, and the docs present that path first. Approvals from the browser follow 074's per-device key.

Verification from outside the tailnet (phone on mobile data): the hostname asks for the Access login; after login the TUI appears; `curl` without credentials gets Access's redirect, never the hub; `tau doctor` reports the tunnel connector, the Access application and the web service; no listening socket other than loopback and the tailnet (checked by `tau doctor` and `infra/remote/doctor.sh`). The docs guide "Private deployment" records the whole path with example values.

## Acceptance criteria

- [ ] `https://tau.<domain>` serves the web UI only after the Access login; an unauthenticated request never reaches the hub (Access log and hub log)
- [ ] The hub has no inbound port: `cloudflared` is outbound, the web service listens on loopback; both doctors verify it
- [ ] The Tailscale Serve variant is documented and tested on the tailnet without a domain
- [ ] Configuration lives in the repo (`infra/tunnel/`: `cloudflared` config template, the Access application and policy as `tau setup tunnel` creates them); only ids and hostnames go to `.env`
- [ ] The docs guide "Private deployment" walks through it end to end with example values only

## Blocked by

- [022 · Move the getporti domain's DNS to Cloudflare](022-move-dns-to-cloudflare.md)
- [074 · tau-web: the TUI in the browser through `textual-serve`, served by the hub](../L4-interface/074-tau-web-textual-serve.md)
- [076 · `tau setup tunnel` and `infra/tunnel`: cloudflared, Access policy, Tailscale Serve, doctor checks](076-tau-setup-tunnel.md)

## Comments

- 2026-09-29: rewritten for ADR 0006 (private-first). Before: the relay at `api.tau.<domain>`, a re-pointed webhook and Access with a service token for the hub. Now: one hostname for the hub's own web UI through Tunnel + Access, Tailscale Serve as the no-domain default; the helper tooling is 076, the web UI is 074. The file keeps its old slug so links stay stable.
