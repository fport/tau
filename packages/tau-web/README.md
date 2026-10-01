# tau-web

The web app's server on tau's hub ([ADR 0015](https://github.com/fport/tau/blob/main/docs/adr/0015-web-app-agentic-chat.md)). When it is installed, `tau hub run` starts the `web` hub service, which does three things:

- It runs the owner's turns **inside the hub**. They use the same Strands agent, tools, tiers, owner guard and session store as `tau tui`, on the `web` channel.
- It streams those turns to paired browsers with the [turn protocol](https://docs.tau.getporti.com/reference/turn-protocol/).
- It serves the web app itself, the bundle of `apps/web`, once that app is built into the wheel.

```sh
uv tool install tau-core --with tau-web
tau hub run                       # serves http://127.0.0.1:7878
tau web device add phone          # prints a one-time pairing link (10 minutes)
tau web device list
tau web device remove phone
```

## Where it listens

It listens on loopback (`127.0.0.1:7878`) by default, or on the hub's tailnet address, and **never** on `0.0.0.0` or the LAN. A wrong `bind` stops the service from starting. To use it from another device, put Tailscale Serve or the Cloudflare Tunnel in front of it (see the private deployment guide). The hub opens no inbound port.

```toml
[component.web]
port = 7878
bind = "127.0.0.1"                       # or the hub's 100.x.y.z tailnet address
hostnames = ["my-mac.tailXXXXXX.ts.net"]  # names the browser uses (Tailscale Serve, the tunnel)
# access_aud = "..."                     # with access_team: require a valid Cloudflare Access token
# access_team = "my-team"
# approval_timeout_seconds = 300
# turn_keep_seconds = 300
```

## The door

Every request passes these checks:

- **Host.** The `Host` header must be loopback, the bind address or one of the `hostnames`. This blocks DNS rebinding.
- **Cloudflare Access.** With `access_aud` and `access_team` set, the request needs a valid `Cf-Access-Jwt-Assertion`. The token must be signed with RS256 by the team's keys, for this audience and from the team's issuer.
- **Origin.** A request that changes something must come from the app's own `Origin`, so no other site can post to `127.0.0.1`.
- **Paired device.** Every `/api` route needs a paired browser, except `/api/pair`.
  - `tau web device add` writes the hash of a one-time code.
  - The browser opens `/pair#<code>` and posts the code from the URL fragment.
  - The hub keeps only the hash of the new device key. The browser keeps the key in an `HttpOnly; SameSite=Strict` cookie.
  - The device id is the channel's `client_id`, so the guard's per-client grants (117) apply per browser.

## Turns, approvals and the guard

- **The turn belongs to the hub, not the tab.** A closed tab does not stop a turn. `GET /api/turns/<id>?after=<seq>` re-attaches and replays the events after `<seq>`.
- **Tier-2 calls wait for a person.** The call waits for `POST /api/approvals/<id>` from a paired device. Without an answer it is rejected when `approval_timeout_seconds` runs out. Nothing is ever approved automatically, and the guard's step-up still runs after an approval.
- **The guard.** A locked guard refuses web turns (stop reason `locked`). A lock rejects every pending approval and cancels running turns.
- **One place at a time.** A session can be open in only one place. A session the TUI or Telegram holds answers `409`, and so does a session the web holds for them.
- **Read-only sessions.** Network, visitor, sub-tau and scheduled sessions can be read in the app but never continued there with the main tau's tools.

## Status

`tau hub status` shows `web: {bind, port, devices, open_sessions, turns, approvals_pending}`.

## Public API

`WebService`, `make_service`, `WebSettings`, `DeviceRegistry`, `Runtime`, `create_app` and the other names in `tau_web.__all__`. tau-web depends on tau-core only through its public API.
