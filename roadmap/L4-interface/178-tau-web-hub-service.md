# 178 · tau-web: the hub's web service with a turn API, paired devices and a web approver

Status: done
Type: AFK
Layer: L4 · Interface
Packages: tau-web, tau-core
Blocked by: 177

## What to build

A new distribution `packages/tau-web` (import `tau_web`) with one `tau.hub_services` component, `web` ([ADR 0015](../../docs/adr/0015-web-app-agentic-chat.md) §2). It replaces 074's `textual-serve` plan.

**Bind.**

- The service listens on `127.0.0.1:<port>` (`[component.web] port`, default 7878). `bind` may be the hub's tailnet address, and it refuses anything else, `0.0.0.0` included.
- It serves the built app (179) at `/` and the protocol routes of 177 under `/api/`.

**Turns run in the hub.**

- Every open session gets a `TauAgent` from `build_agent` with `channel="web"`, the in-hub guard (`guard=DISCOVER`), a `WebApprover` and the device id as `client_id`.
- A turn runs as an asyncio task that owns its event buffer. The stream is NDJSON, and a re-attach with `after=` replays from the buffer. The buffer is dropped a few minutes after `end`.
- Cancel calls `TauAgent.cancel()`.
- Turns in one session are serialized, as `TauAgent` already does.

**Session lock.**

- The file session store gains an advisory per-session lock (`fcntl.flock` on `sessions/<id>/.lock`), taken by whoever holds the session open: tau-web, the TUI, `tau chat` or Telegram.
- A second opener gets a clear error, and `/resume` of a locked session names the holder's channel.

**Paired devices, for every route but pairing.**

- `tau web device add <name>` is a `tau.commands` entry point. It prints `http://127.0.0.1:7878/pair#<code>`, a single-use code valid for 10 minutes.
- The pairing page posts the fragment. The hub stores only a hash of the device key, with the name and the creation and last-seen times, in `TAU_DATA_DIR/web/devices.json` (mode `0600`).
- The key lives in an `HttpOnly; SameSite=Strict` cookie, which is `Secure` except on plain `http://127.0.0.1`.
- `tau web device list|remove` manage devices. Removing one ends its open streams.

**Browser attacks.**

- `Host` must be loopback, the tailnet name or `[component.web] hostname`.
- Every non-`GET` request needs the app's own `Origin`.
- With `[component.web] access_aud` set, a valid `Cf-Access-Jwt-Assertion` is required, checked against Cloudflare's keys (tests use a fake JWKS).

**`WebApprover`.**

- It emits the `approval` event, awaits `POST /api/approvals/<id>` from a paired device and times out as the gate says. It never auto-approves.
- A lock rejects pending approvals, as ADR 0008 decision 10 says.
- The step-up after an approval runs unchanged, and its `guard` events reach the stream.

**Guard.** `web` is guarded and trusted. A locked hub answers turns with stop reason `locked` and the app shows the lock (179). There is no flag, environment variable or config key that changes the channel.

**Other routes and checks.**

- `/api/sessions` lists sessions from every channel. `/api/sessions/<id>` returns `history_blocks`.
- `/api/capabilities` reports which hub services exist: guard, routines, devices, subs, net.
- `/status` gains `web: {bind, port, devices, open_sessions, turns}`.
- `tau doctor` fails on a bind that is neither loopback nor tailnet.

## Acceptance criteria

- [x] With tau-web installed, `tau hub run` serves on `127.0.0.1:7878`; a bind to `0.0.0.0` or a LAN address refuses to start
- [x] A turn posted by a paired device streams the protocol of 177 from a Strands agent inside the hub; a closed tab does not stop it and a re-attach with `after=` resumes the stream (test with `FakeModel`)
- [x] Without a paired device every route but `/pair` answers 401; a wrong `Host` or a cross-site `Origin` is refused; the pairing code works once and expires
- [x] A tier-2 call shows an approval, is approved or rejected through the route, and times out as rejected; nothing is auto-approved (`ScriptedApprover` never used in the service; tests drive the route)
- [x] With the guard locked (`FakeGuard`), turns end with `locked`; a step-up failure turns an approval into a rejection
- [x] Opening a session that another process holds fails with the holder's channel; the TUI's `/resume` says so
- [x] `tau-web` builds as its own wheel, depends on tau-core only through its public API, and is added to CI (the release workflow waits for the owner's PyPI publisher, see Comments)

## Blocked by

- [177 · The turn protocol](177-turn-protocol.md)

## Comments

- 2026-10-01: filed with ADR 0015. Supersedes 074. Remote use while the owner is away from the Mac waits for 117's per-client grants, keyed by the device id.
- 2026-10-01: done (24c0502, 6164ea9, c114eae, 2b69a90).
  - **tau-core:**
    - `SessionStore.hold` and `SessionBusy`. The file store takes an `flock` on `<session>/.lock`. The same channel of a process may hold a session again; another channel or process is refused with an error that names the holder. `build_agent` holds the session and `TauAgent.close` releases it.
    - `Hub.started_services()`.
  - **tau-web:** the server is starlette plus uvicorn on the hub's loop. The service binds its own socket and leaves the hub's signal handlers alone. `Runtime` keeps one `TauAgent` per open session, on channel `web`, with the hub's guard service (or `DISCOVER`) and a `WebApprover`. A turn's buffer is appended to synchronously, so guard step-up events land in order.
  - **Sessions the web may continue:** only sessions from the owner's own channels (`web`, `tui`, `terminal`, `telegram`, `ask`). Network, visitor, sub-tau and scheduled sessions are listed and readable but answer 409 to a turn, so peer-written text never meets the main tau's tools.
  - **Config:** `[component.web]` takes `port`, `bind`, `hostnames` (a list, so Tailscale Serve's `*.ts.net` name and the tunnel's both work), `access_aud` with `access_team`, `approval_timeout_seconds` and `turn_keep_seconds`. An idle session is closed after `turn_keep` seconds, which releases its lock.
  - **Not done:**
    - `tau doctor` does not check the bind: components cannot add doctor checks yet (107). The service refuses a bad bind instead.
    - `release.yml` waits for a PyPI trusted publisher for `tau-web`.
    - tau-web imports `tau_core.agent.AGENT_ID` for the history read, like tau-sub's use of `tau_core.agent`.
  - **For 179:**
    - The static bundle goes to `packages/tau-web/src/tau_web/static/` with an `index.html`; without it the root serves a placeholder.
    - The CSP allows only `'self'` scripts and `frame-src 'self' about:`.
    - `/api/capabilities` returns `{backend, protocol, language, pages, device}`.
    - `/api/sessions` items carry `channel`, `continuable` and `open_here`.
