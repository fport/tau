# 111 · `tau-guard` service: state machine, reflex locks, worker subprocess, protected `/guard/*` routes, cooldown, audit log

Status: done
Type: AFK
Layer: L10 · Guard
Packages: tau-guard (new)
Blocked by: 110

## What to build

A new distribution `packages/tau-guard` (import `tau_guard`) whose `guard` hub service owns the guard's state inside `tau hub run`. It locks on its own (reflexes), runs every check in a worker subprocess, and answers the protected `/guard/*` routes that tau-core's `HubGuard` (110) speaks. This slice is the service and its plumbing; the real camera, face engine and enrollment are 112, which fills in the worker's `verify` and `enroll` operations. Until then the worker answers those operations with `not_enrolled`, and tests drive a fake worker. The decisions are in [ADR 0008](../../docs/adr/0008-owner-guard.md) (decisions 2, 3, 9, 10 and 13).

### Package

- **Dependencies:** `tau-core` (at least the version with `tau_core.guard`), `numpy>=2`, `opencv-python-headless>=4.14,<5` and `cryptography>=44`. On darwin only (each with `; sys_platform == 'darwin'`): `keyring>=25`, `pyobjc-framework-AVFoundation`, `pyobjc-framework-Quartz` and `pyobjc-framework-LocalAuthentication`. Every pyobjc and cv2 import is lazy, so the package imports and its tests run on Linux CI.
- **Entry points:** `tau.hub_services: guard = tau_guard.service:make_service` and `tau.commands: guard = tau_guard.cli:guard`. The command group is a skeleton here (`status`, `lock`, `log`); 112 adds the rest.
- **Distribution:** `LICENSE`, a README, its own version and tests, `uv build --package tau-guard`, and entries in CI and in the release workflow's package list. The PyPI environment for tau-guard is a human step; note it under Comments.
- **Inert when inactive.** When neither the marker `TAU_DATA_DIR/guard/enrolled` nor `[component.guard] enabled = true` is present, the service only reports `guard: {state: "off"}`. It starts no threads, imports neither cv2 nor pyobjc and adds no routes.

### State machine (`state.py`: pure code with a fake clock)

The states are `off` / `locked` / `verifying` / `unlocked` / `unavailable`. Orthogonal to them are `step_up_active`, `failures`, `cooldown_until`, `seq` (grows on every change), `face_seen_at` and `max_idle_since_face`.

| Event | From | To / effect |
|---|---|---|
| start | – | `locked` (trigger `startup`); an unlock is never restored |
| unlock request | locked, unlocked | `verifying`; a concurrent unlock joins the running attempt (same attempt id, same verdict) |
| unlock ok | verifying | `unlocked`; since = now, expires_at = now + max age, face_seen_at = now; failures reset after being reported |
| unlock fail | verifying | back to the previous state; the failure counter moves (below) |
| step-up request | unlocked | stays `unlocked`, `step_up_active`; queues behind a running verification, bounded by its timeout |
| step-up request | locked, or verifying an unlock from locked | returns `False` (`locked`); the camera never opens |
| step-up ok | – | face_seen_at = now; since and expires_at unchanged |
| step-up fail with `no_match`, `spoof` or `multiple_faces` | unlocked | `locked` (trigger `step_up_failed`) |
| any lock trigger | any | `locked`; a running attempt is cancelled (`cancelled`) and the camera released |
| recheck ok | unlocked | face_seen_at = now, max_idle_since_face = 0 |

### Reflex locks (`presence.py` and `service.py`)

- **Where they run.** They are evaluated inline at every admit and step-up (monotonic plus wall clock), and by a reflex loop every 2 s. Admit refuses (`unavailable`) when the loop's last tick is older than 6 s.
- **Max age.** `max_unlock_hours` (default 8, range 1–24) on the UTC wall clock.
- **Sleep.** A wall − monotonic drift of more than 30 s between ticks locks with trigger `sleep`.
- **Idle.** `CGEventSourceSecondsSinceLastEventType(kCGEventSourceStateHIDSystemState, kCGAnyInputEventType)`; `idle_lock_minutes` (default 10, range 1–240).
- **Screen lock.** `CGSessionCopyCurrentDictionary()["CGSSessionScreenIsLocked"]`, checked inline and every tick.
  - A `None` session reads as `unknown`; it is reported in the status and the doctor.
  - While the state is unknown, the unlock is capped at `idle_lock_minutes`.
- **Presence recheck.** Admission answers `recheck` when `max_idle_since_face ≥ recheck_after_idle_minutes` (default 3), or when `now − face_seen_at ≥ presence_recheck_minutes` (default 30).
  - The recheck is `unlock(kind="recheck")`: a passive strict match of 3 frames out of 5, with no challenge. The worker side is 112.
  - A recheck that sees a non-matching face locks.
- **Sources.** Presence reads go through a `PresenceSource` protocol: a macOS implementation (Quartz, imported lazily) and a fake for tests. The clock goes through a `Clock` protocol.
- **Dependencies.** None: no LLM, no cloud, no mesh.
- **Validation.** Out-of-range or non-numeric knobs make the service `unavailable`, with the reason in the doctor. They never fall back to a weaker value.

### Worker subprocess

- **Protocol.** `python -m tau_guard.worker <op>` with `op` in `verify | enroll | touch_id | selftest`.
  - The request JSON goes to stdin.
  - Stdout carries JSON lines: `{"type": "progress", "step", "hint", "deadline"}`, then a final `{"type": "verdict", "ok", "reason", "method", "score"?, "liveness"?}`. The score is rounded to 2 decimals, for the audit only.
  - Stderr goes to `TAU_DATA_DIR/guard/worker.log` (0600).
- **Lifetime.** The service spawns one worker per attempt. It kills it on cancel, lock, timeout or hub stop: SIGTERM, then SIGKILL after 1 s.
- **Threads.** Blocking reads happen in a dedicated daemon thread, never in `asyncio.to_thread`, so `tau hub stop` is not delayed.
- **Bad output.** A malformed line, an unknown reason or a worker that exits without a verdict gives `error`.
- **This slice's operations.** `selftest` checks the platform and the imports. `verify` and `enroll` answer `not_enrolled` until 112.

### Routes (all protected, JSON)

| Route | Body / query | Response |
|---|---|---|
| `GET /guard/status` | `?since=<seq>&wait=<0..25>[&attempt=<id>]` long poll | every `GuardStatus` field as JSON, plus the `enrollment` id; `attempt` is the running attempt, or with `attempt=<id>` that attempt's own record |
| `POST /guard/admit` | `{channel, session_id, client_id}` | `{allowed, reason, enrollment}`, with the reflex checks evaluated inline |
| `POST /guard/verify` | `{channel, client_id, kind: "unlock" \| "recheck" \| "step_up", request_id?, tool?, policy?}` | `202 {attempt, seq}`; joins a running unlock |
| `POST /guard/cancel` | `{client_id, attempt?}` | `{ok}` |
| `POST /guard/lock` | `{channel, client_id, trigger}` | `{state: "locked"}`, idempotent |
| `POST /guard/enroll` | `{client_id}` | `202 {attempt, seq}`; runs LocalAuthentication first (112) |

- **Reading a result.** An attempt is `{id, kind, step, seq, deadline, hint, done, ok, reason, method, retry_after}`; `HubGuard` (110) reads every field. Its result is read through `GET /guard/status?attempt=<id>`, with the id from the `202` of `/guard/verify`:
  - `attempt` is then that attempt's own record, whether it is queued (a step-up waiting behind a running verification: `step: "starting"`, `done: false`), running or finished; it is `null` once the id is unknown or expired;
  - the hub keeps a finished attempt's record for at least 60 s, so a client that polls late, or while another client's attempt runs, still reads its own verdict;
  - without the parameter, `attempt` is the running attempt or `null`;
  - a successful attempt has `done: true`, `ok: true`, `reason: "match"` and a `method` (`face` or `touch_id`), and the same answer must carry `state: "unlocked"` and the local `enrollment` id, or `HubGuard` does not count it as a success;
  - a refused `/guard/verify` answers 4xx (never 403, which only the token check uses) with `{reason, retry_after?}`, for example `cooldown` or `busy`.
- **Nothing is taken on trust.** No route accepts a verdict, an image or an embedding. The `channel` fields are audit labels only.
- **Policy.** A `policy` in the verify body can only make the check stricter.
- **The open `/status`** gains only `guard: {state, enrolled, available, reason}`.
- **When the service is active but broken**, `/status` still carries the guard block, with `state: "unavailable"`; it never omits it.

### In-hub API

`GuardService` implements `tau_core.Guard` directly; in-hub callers find it with `hub.find_service("guard")` plus an `isinstance(Guard)` check, looked up lazily. It also offers:
- `subscribe(callback)`, for state changes;
- `face_fresh(seconds) -> bool`, for voice later.

### Failures, cooldown, audit

- **What counts.** `no_match`, `spoof` and `multiple_faces` count as failures, for unlock, recheck and step-up alike.
- **Cooldown.** Three failures within 10 minutes start a cooldown of 30 s that doubles up to 15 minutes. During it the verdict is `cooldown`, with `retry_after`.
- **Reporting.** The count is shown on the next successful unlock (`GuardStatus.failures`).
- **Audit log.** `TAU_DATA_DIR/guard/audit.jsonl` (0600, in a 0700 directory, both chmod explicitly) uses the schema `{v: 1, at, event, channel, client_id, trigger, ok, reason, score?, liveness?, duration_ms, request_id?, tool?}`.
  - `event` is one of `verify | step_up | recheck | lock | unlock | enroll | forget | cooldown | camera_open | touch_id`.
  - It never holds an embedding, a frame or anyone else's data.
  - It is rotated at 1 MiB, keeping 3 files. `tau guard log [--since] [--json]` reads it.
- **The hub log** gets no verdicts and no scores. `hub/logs` is 0700 and new log files are 0600, unless 110 already did that.

## Acceptance criteria

- [x] `uv build --package tau-guard` builds a wheel with `LICENSE`; the package is in CI and the release list; `uv run pytest -q` passes on Linux without pyobjc
- [x] With the guard inactive, the service reports `guard: {state: "off"}` only; no thread starts, `cv2` and `objc` are not in `sys.modules`, and no `/guard/*` route exists
- [x] Every row of the state table has a pure `state.py` test with a fake clock, including concurrent unlocks sharing one attempt and verdict, a step-up while locked returning `False` without spawning a worker, and a lock during `verifying` cancelling the attempt
- [x] A hub start is always `locked` (trigger `startup`), including after `kill -9` of the previous hub
- [x] Reflex locks fire with a fake clock and a fake presence source: max age, sleep drift, idle, screen lock, and an unknown screen state capping the unlock at `idle_lock_minutes`; admit refuses when the reflex loop's last tick is older than 6 s
- [x] Admission answers `recheck` after `recheck_after_idle_minutes` of idle since the last face and after `presence_recheck_minutes`; a recheck with a non-matching face locks
- [x] Cooldown: three counted failures within 10 minutes give `cooldown` with `retry_after` 30 s, doubling to 15 min; a failed step-up with `no_match` locks with trigger `step_up_failed`
- [x] A test enumerates every registered `/guard/*` route and its body schema, and finds no field that accepts a verdict, a score, an image or an embedding; `/guard/lock` is idempotent
- [x] Every `/guard/*` route answers 403 without the token and carries a valid proof with it (real `ControlApi` on port 0, `HubGuard` from 110 as the client)
- [x] The worker runner: a fake worker script's progress lines reach `GET /guard/status` as `seq` changes; cancel, lock and a timeout kill it (SIGTERM, then SIGKILL after 1 s); garbage output or an exit without a verdict gives `error`; stderr lands in `worker.log`, never on the hub's stderr
- [x] `/status` carries `guard: {state, enrolled, available, reason}` and nothing more; an active but failed service shows `state: "unavailable"`
- [x] `audit.jsonl` follows the schema, rotates at 1 MiB with 3 files, and a test asserts no record contains a list of floats or any key other than the schema's; `guard/` is 0700 and its files 0600
- [x] `GuardService` passes `isinstance(service, tau_core.Guard)`; `subscribe` callbacks see every state change; `face_fresh` follows `face_seen_at`
- [x] Stopping the hub during a running attempt kills the worker and ends within the hub's normal stop time

## Blocked by

- [110 · Guard seams in tau-core](110-guard-seams-in-tau-core.md)

## Comments

- 2026-09-30: filed with ADR 0008.
- 2026-09-30: notes from 110's verification fixes:
  - Protected routes are signed (`X-Tau-Nonce`, `X-Tau-Auth`) and proven (`X-Tau-Proof`) by `ControlApi`; a route handler does nothing for it. Tests call the routes through `HubClient`/`HubGuard`, or sign with `tau_core.hub.control.auth_headers`.
  - `/guard/status?attempt=<id>` returns that attempt's own record (queued, running or finished) and `null` once the id is unknown or expired; keep finished records for at least 60 s. A queued step-up shows `step: "starting"`, `done: false`. See "Reading a result" above.
  - Never answer 403 from a `/guard/*` handler: 403 belongs to the token check, is never signed, and `HubGuard` reads it as `unavailable` whatever the body says. Refusals such as `cooldown` or `busy` use 409 or 429 with `{reason, retry_after?}`.
  - `/guard/lock` must answer `{"state": "locked"}`; `HubGuard.lock` logs an error otherwise.
  - 110 set mode 0700 on `hub/logs` only when `tau hub install` creates it (`mkdir(mode=)` does not change an existing directory). Chmod it explicitly at hub start and create new log files 0600.
- 2026-09-30: done on `guard/service` (commits 71634cc, ff685e6, 14cfc2c, 088b45b, 11542db, cbf4cff, b012cf5, 9a819a2, 692b1f6, d064750). `packages/tau-guard` holds `state.py` (the pure machine), `presence.py`, `config.py`, `audit.py`, `worker.py` (the subprocess), `runner.py` (spawn, read, kill), `routes.py` (strict schemas), `service.py` (`GuardService`, `make_service`), `cli.py` with `strings.py` (`guard.cli.*`) and `testing.py` (`FakeClock`, `FakePresence`, a scripted fake worker). The package has 191 tests. The full suite passes except the pre-existing `test_no_personal_paths_in_tracked_files` (issue 130). The tau-guard tests also pass with pyobjc and cv2 imports blocked; CI confirms them on Linux.
  - **`verifying` means an unlock from `locked`.** A re-unlock, a recheck or a step-up started while `unlocked` keeps the state `unlocked`, with `attempt` set (and `step_up_active` for a step-up). Other channels are not refused in the meantime, and a finished step-up still reads `state: "unlocked"`, which `HubGuard` requires for a success.
  - **A failed recheck** (`no_match`, `spoof`, `multiple_faces`) locks with trigger `step_up_failed` ("locked after a failed identity check"). `LOCK_TRIGGERS` has no recheck value, and only `GUARD_CONFIG_KEYS` may change in `tau_core/guard.py` on this branch.
  - **Cooldown rule.** Three counted failures within 10 minutes start 30 s. After that, every further counted failure starts the next cooldown at twice the length (up to 15 min), until a match or 10 quiet minutes (no failure, no cooldown ending) reset the doubling.
  - **The cap for unknown presence.** While the screen state or the HID idle is unknown, the unlock lasts at most `idle_lock_minutes` from `since`, with lock trigger `max_age`.
  - **Knob ranges the ADR leaves open:** `recheck_after_idle_minutes` 1–240, `presence_recheck_minutes` 1–1440, `verify_timeout_seconds` 5–60, `step_up_challenge_fresh_seconds` 0–600, thresholds 0.45–0.95. A worker is killed after `verify_timeout_seconds` + 15 s. Finished records stay readable for 120 s (at most 256 of them). At most 8 attempts queue; beyond that the answer is `409 busy`.
  - **Answers.** `409 {reason}` for `locked`, `busy`, `not_enrolled` and `unavailable`; `429` for `cooldown`; `400 {reason: "error"}` for a body or query outside the schema. The `202` of `/guard/verify` carries a `seq` just below the attempt's, so the first poll answers at once with `step: "starting"`. A `since` from an earlier hub is answered at once.
  - **Extra fields.** `/guard/status` adds `screen` (`locked`, `unlocked` or `unknown`) and `step_up_active`. Besides the unavailable reasons (`config`, `unsupported_platform`, `presence_unavailable`, `no_control_api`, `error`, `stopped`), the open `/status` `reason` says `reflex_stalled` or, while available, `screen_unknown`. `camera` is derived from the last verdict.
  - **The worker in this slice.** `verify` answers `not_enrolled` without a marker and `unavailable` with one. `enroll` answers `not_enrolled` and `touch_id` answers `touch_id_unavailable`. A passing `selftest` has `reason: null` and a `checks` map. Workers inherit the hub's environment plus `OPENCV_LOG_LEVEL=ERROR` and `OPENCV_AVFOUNDATION_SKIP_AUTH=1`. The service does not run `selftest` at start.
  - **Logs.** `hub/logs` is chmod 0700 and its files 0600 at every hub start (`HubFiles.secure_logs`). `tau.log` is also created 0600 in a 0700 directory, and an existing one is narrowed.
  - **Human step:** a PyPI trusted publisher for `tau-guard` with the GitHub environment `pypi-guard` (see `release.yml` and `docs/contributing/release.md`). The release that ships `tau_core.guard` bumps tau-core, tau-tui and tau-guard together and raises tau-guard's `tau-core>=` floor to that version; 0.3.1 on PyPI has no `tau_core.guard`.
  - **For 112.** Fill `tau_guard.worker.run` for `verify` and `enroll`. The request carries `kind`, the merged `policy`, `settings` (thresholds, timeout, camera, fallback) and `challenge_fresh`. Release the camera before writing the verdict: the hub waits 1 s for the exit, then sends SIGTERM. A verdict with `liveness: "challenge"` starts the `step_up_challenge_fresh_seconds` window. The hub cannot see the camera open, so `camera_open` needs a progress step or a new message type. `tau guard doctor` should run `selftest` and show `screen_unknown` and the unavailable reason. `/guard/enroll` still needs LocalAuthentication first and the `SSH_CONNECTION` refusal.
  - **For 113 and 115.** `GuardStatus.failures` shows the count before an unlock for as long as it stays unlocked. An admission answer of `recheck` means `unlock(kind="recheck")`. `subscribe()` callbacks run on the hub loop.
  - **Out of scope, for the orchestrator:** tau-core's `guard_doctor_check` reports a hub guard in state `unavailable` as `ok` and never shows the block's `reason`.
