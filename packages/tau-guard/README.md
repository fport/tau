# tau-guard

The owner guard for tau: tau's guarded surfaces (`tau tui`, `tau chat`, tau Desktop) work only
while the owner is verified at the Mac. The decision and its threat model are in
[ADR 0008](../../docs/adr/0008-owner-guard.md).

tau-guard is its own distribution (`tau-guard`, import `tau_guard`). It uses only the public API
of `tau-core`, whose `tau_core.guard` owns the `Guard` protocol, the reason lists and the
`/guard/*` route contract, and plugs in through two entry points:

| group | name | what |
|---|---|---|
| `tau.hub_services` | `guard` | the guard service inside `tau hub run` |
| `tau.commands` | `guard` | `tau guard status`, `lock` and `log` |

Channels never import this package: they talk to the hub through tau-core's `HubGuard`, so no
camera library ever loads in a channel process.

## What it does

- **Inert until switched on.** Without the marker `TAU_DATA_DIR/guard/enrolled` and without
  `[component.guard] enabled = true`, the service only reports `guard: {state: "off"}` in
  `/status`. It starts no thread, adds no route and imports neither OpenCV nor pyobjc.
- **Locked at every start.** An unlock lives in memory only; a hub start, even after
  `kill -9`, is `locked` with trigger `startup`.
- **One check at a time, in a worker.** Each unlock, presence recheck or step-up runs in its own
  short-lived subprocess (`python -P -m tau_guard.worker`, run in `TAU_DATA_DIR/guard/`).
  The hub kills it on cancel, lock, timeout or hub stop (SIGTERM, then SIGKILL after 1 s). Its stderr goes to
  `TAU_DATA_DIR/guard/worker.log`, never to a terminal. Concurrent unlocks share one attempt;
  a step-up waits behind a running check.
- **Reflex locks without an LLM or the cloud.** The service locks on the longest unlock time,
  on HID idle, when the screen locks and after the Mac slept. It checks these at every admission
  and every verification, again when a worker's verdict arrives and when a client reads it,
  and a reflex loop checks them every 2 s. A lock that comes while a check runs cancels it, so
  its late match counts for nothing. If the loop stops ticking, admission refuses. No check
  starts while the screen is locked.
- **Presence rechecks.** After a few minutes of idle since the last face match, or after
  `presence_recheck_minutes`, admission answers `recheck`, and the channel runs a quick passive
  check. A non-matching face locks, and so does a failed step-up or re-unlock: any check that
  sees someone else while tau is unlocked.
- **Cooldown.** Three failed matches (`no_match`, `spoof`, `multiple_faces`) within 10 minutes
  start a 30 s cooldown. The cooldown doubles with each further failure, up to 15 minutes.
  The count and the cooldown survive a hub restart (`TAU_DATA_DIR/guard/failures.json`, 0600).
- **An audit log.** `TAU_DATA_DIR/guard/audit.jsonl` (0600, in a 0700 directory) records every
  check, lock, unlock and cooldown. It never holds an embedding, a frame or anything about
  another person. It is rotated at 1 MiB, with 3 files kept. The hub log gets no verdicts and
  no scores.

This release has the service and its plumbing. The worker's `verify` answers `not_enrolled`
(`unavailable` once a marker exists) and `enroll` answers `not_enrolled`. The camera, the face
engine and enrollment come with issue 112, and Touch ID with issue 114.

## Routes

All routes are protected control routes. `ControlApi` checks each request's signature and
signs each answer. No route accepts a verdict, an image or an embedding: a route can only ask
the hub to look.

| Route | Body or query | Answer |
|---|---|---|
| `GET /guard/status` | `?since=<seq>&wait=<0..25>[&attempt=<id>]` | every `GuardStatus` field plus `enrollment`, `screen`, `step_up_active` and `attempt` |
| `POST /guard/admit` | `{channel, session_id, client_id}` | `{allowed, reason, enrollment, state}` |
| `POST /guard/verify` | `{channel, client_id, kind, request_id?, tool?, policy?}` | `202 {attempt, seq}`, or `409`/`429 {reason, retry_after?}` |
| `POST /guard/cancel` | `{client_id, attempt?}` | `{ok}` |
| `POST /guard/lock` | `{channel, client_id, trigger}` | `{state: "locked"}` |
| `POST /guard/enroll` | `{client_id}` | `202 {attempt, seq}` |

A body with an unknown key or a wrong type gets `400 {reason: "error"}`. The open `/status`
gains only `guard: {state, enrolled, available, reason}`.

Inside the hub, `GuardService` is a `tau_core.Guard`: find it with `hub.find_service("guard")`
plus an `isinstance(service, Guard)` check. It also offers `subscribe(callback)` for state
changes and `face_fresh(seconds)`.

## Configuration

Every key is optional. A value out of range or of the wrong type makes the guard `unavailable`,
with the reason in the log. The guard never falls back to a weaker value.

```toml
[component.guard]
enabled = true                      # or the enrollment marker
max_unlock_hours = 8                # 1-24, on the wall clock
idle_lock_minutes = 10              # 1-240; also the cap while the screen state is unknown
recheck_after_idle_minutes = 3      # 1-240
presence_recheck_minutes = 30       # 1-1440
verify_timeout_seconds = 15         # 5-60; the worker gets 15 s more
unlock_liveness = "challenge"       # or "none"
step_up = "face"                    # face | face_or_touch_id | touch_id | none
```

A client sends its own `step_up` and `unlock_liveness` values with every check, and the hub
applies the stricter of its own value and the client's.

## Commands

```sh
tau guard status [--json]           # the state as the running hub reports it
tau guard lock                      # lock every guarded channel now
tau guard log [--since 2h] [--json] # the audit log
```

## Tests

`tau_guard.testing` has `FakeClock`, `FakePresence` and a fake worker
(`fake_worker_command(script)`) that speaks the worker protocol from a JSON script. No test
opens a camera, a microphone, the Keychain or a Touch ID prompt, and every macOS call sits
behind a protocol and is imported lazily, so the suite runs on Linux.

```sh
uv run pytest -q packages/tau-guard
uv build --package tau-guard
```
