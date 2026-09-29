# 074 · tau-web: the TUI in the browser through `textual-serve`, served by the hub

Status: ready-for-agent
Type: AFK
Layer: L4 · Interface
Packages: tau-web, tau-tui, tau-core
Blocked by: none

## What to build

A new distribution `packages/tau-web` (import `tau_web`) with one `tau.hub_services` component `web` (ADR 0006, consequences; contract in ADR 0005). Inside `tau hub run` it starts `textual-serve` for the `tau tui` app, bound to `127.0.0.1:<port>` only (`[component.web] port`, default 7878; `bind` may also be the hub's tailnet address, never `0.0.0.0`), so the only ways in are the Tunnel + Access (023/076) or Tailscale Serve. Every browser tab gets its own TUI process with the hub's config (home, profile and UI language passed through), so `/sessions`, `/resume`, approvals and everything else behave exactly as in the terminal. The TUI's `-short` band already exists; the page must stay usable at phone width.

Trust (ADR 0006 §5): tier-2 approvals from the browser are accepted only from a browser that presented the per-device key: `tau web device add <name>` (a `tau.commands` entry point of tau-web) prints a random key and stores its hash under `TAU_DATA_DIR/web/devices.json`; the browser sends it once (query parameter on first open, then a cookie); a tab without it runs the TUI with the refusing approver from 073 and says which channel to use. When `[component.web] access_aud` is set, the service also verifies the `Cf-Access-Jwt-Assertion` header against Cloudflare's public keys and rejects requests without it (defense in depth behind Access; off on the tailnet and documented as such). `/status` shows `web: {bind, port, sessions}`; `tau doctor` fails when the bind address is neither loopback nor tailnet.

## Acceptance criteria

- [ ] With tau-web installed, `tau hub run` serves the TUI at `http://127.0.0.1:7878` and refuses to bind to an address that is neither loopback nor the tailnet
- [ ] Each browser session is an isolated TUI process with the hub's config; closing the tab ends it; `/status` counts the open sessions
- [ ] Without a device key a tier-2 call is refused with a pointer; with a registered key the TUI's approval dialog works; keys are stored hashed and `tau web device list|remove` manage them; nothing is ever auto-approved
- [ ] With `access_aud` set, a request without a valid Access JWT is rejected (tests with a fake JWKS); without it the check is off and the README says it is tailnet-only
- [ ] Works through Tailscale Serve on the tailnet and is the target 023 puts behind the tunnel; the docs guide "Private deployment" covers both
- [ ] `tau-web` builds as its own wheel (`uv build --package tau-web`), depends on tau-core and tau-tui only through their public APIs, is added to CI and to the release workflow's package list

## Blocked by

None - can start immediately; the hub service contract (065) and the TUI (063) are done.

## Comments

- 2026-09-29: opened for ADR 0006 (private-first): "the web UI is a new package (`tau-web`), served by the hub; first slice: the existing TUI in the browser through `textual-serve`, behind Access". Voice from the phone (browser microphone) is 080.
