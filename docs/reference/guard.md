# Owner guard reference

Everything the owner guard reads, writes and answers: the `[component.guard]` keys, the `tau guard` commands, the states and reasons, the `/guard/*` routes with the signed-request scheme, the audit log and the files under `TAU_DATA_DIR/guard/`. The setup and daily use are in the [guard guide](../guides/guard.md); the decision is [ADR 0008](../adr/0008-owner-guard.md).

Where the code lives:

- **`tau_core.guard`** (tau-core) owns the `Guard` protocol, the value types, the reason lists, `HubGuard` (the channels' client of the hub), `LockedGuard` and `resolve_guard`. No channel process ever imports OpenCV or pyobjc.
- **`tau_guard`** (the `tau-guard` distribution) is the hub service `guard` (`tau.hub_services`), the worker `python -m tau_guard.worker` and the `tau guard` command (`tau.commands`).

## When the guard is active

| Condition | Result |
|---|---|
| no marker `TAU_DATA_DIR/guard/enrolled` and `[component.guard] enabled` is not `true` | **off**: no guard, nothing locks; `/status` reports `guard: {state: "off"}` |
| the marker exists, **or** `enabled = true` | **active**: guarded channels need the owner verified at the Mac |
| active on any platform but macOS | locked for good, reason `unsupported_platform` |
| `enabled` is not a bool, or `[component.guard]` holds an unknown key | locked for good (`tau doctor` names the problem); a typo such as `enable = true` never means "off" |
| `enabled = true` but nothing enrolled | locked, reason `not_enrolled` |
| a known key out of range or of the wrong type | `unavailable`, reason `config`, each problem in the hub log; never a fallback to a weaker value |

While the marker exists, `enabled = false` is ignored and `tau doctor` says so. The only off switch is `tau guard forget`.

## `[component.guard]`

Every key is optional.

```toml
[component.guard]
enabled = true                         # or the enrollment marker
max_unlock_hours = 8
idle_lock_minutes = 10
recheck_after_idle_minutes = 3
presence_recheck_minutes = 30
verify_timeout_seconds = 15
unlock_threshold = 0.50
step_up_threshold = 0.55
step_up_challenge_fresh_seconds = 120
unlock_liveness = "challenge"
step_up = "face"
unlock_fallback = "touch_id"
camera = "builtin"
```

| Key | Default | Range or values | Meaning |
|---|---|---|---|
| `enabled` | `false` | bool | switches the guard on without an enrollment; `tau guard setup` writes `true` and `tau guard forget` writes `false` |
| `max_unlock_hours` | `8` | 1–24 | longest unlock, on the UTC wall clock (trigger `max_age`) |
| `idle_lock_minutes` | `10` | 1–240 | HID idle time that locks (trigger `idle`); also the cap on an unlock while the screen state is unknown |
| `recheck_after_idle_minutes` | `3` | 1–240 | idle time since the last face match after which admission asks for a presence recheck |
| `presence_recheck_minutes` | `30` | 1–1440 | age of the last face match after which admission asks for a presence recheck |
| `verify_timeout_seconds` | `15` | 5–60 | bound on the frontal match; the camera stays on for at most 20 s whatever this says |
| `unlock_threshold` | `0.50` | 0.45–0.95 | cosine similarity a frame needs for an unlock |
| `step_up_threshold` | `0.55` | 0.45–0.95 | the same for step-ups and presence rechecks |
| `step_up_challenge_fresh_seconds` | `120` | 0–600 | within this time after a check that passed the head-turn challenge, a step-up is a passive strict match |
| `unlock_liveness` | `"challenge"` | `challenge`, `none` | `none` drops the head turns from an unlock; the doctor warns, because a photo could then unlock |
| `step_up` | `"face"` | `face`, `face_or_touch_id`, `touch_id`, `none` | what a tier-2 step-up asks for; Touch ID answers `touch_id_unavailable` until issue 114, so `touch_id` fails every step-up until then |
| `unlock_fallback` | `"touch_id"` | `touch_id`, `touch_id_or_password`, `none` | offered after two face failures or a `camera_*` verdict (issue 114) |
| `camera` | `"builtin"` | `builtin` or a camera's AVFoundation uniqueID | `builtin` picks the device of type `AVCaptureDeviceTypeBuiltInWideAngleCamera` on transport `bltn`; the doctor warns when an id names anything else |

A client sends its own `step_up` and `unlock_liveness` with every check, and the hub applies the stricter of its own value and the client's (strictest first: `face` or `touch_id`, then `face_or_touch_id`, then `none`; `challenge` before `none`).

## `tau guard`

| Command | What it does | Where it runs |
|---|---|---|
| `tau guard setup [--model-file FILE]` | installs SFace (download pinned by sha256, or `FILE`), enrolls, runs one check, writes `[component.guard] enabled = true` | at the Mac only (macOS, no `SSH_CONNECTION`); through the hub when a guarded hub runs, else a local worker |
| `tau guard enroll [--add]` | enrolls again behind Touch ID or the Mac password; `--add` adds samples to the template (other light) | at the Mac only |
| `tau guard verify [--explain[=all]]` | one check with the head-turn challenge; `--explain` runs it in a local worker, prints each prompt as a highlighted line (`>>> TURN YOUR HEAD LEFT <<<`) and every 3rd frame's numbers (`=all`: every frame): the prompt on screen, head yaw, turn from the frontal baseline and pitch in degrees, the landmarks' fit error, eye distance, detector score, brightness, sharpness, similarity. No frame is saved. A local check that fails its challenge names the liveness rule. Exit 1 when it fails | macOS (exit 2 elsewhere); through the hub when a guarded hub runs, so a passed check unlocks tau, else a local worker |
| `tau guard forget` | removes the template, the marker and the Keychain key behind Touch ID or the Mac password, and writes `enabled = false`; exit 1 when the Keychain kept the key (run it again) | at the Mac only, always a local worker |
| `tau guard doctor` | checks platform, worker, OpenCV, the YuNet and SFace files, enrollment, template, the head-turn calibration (measured in degrees, or the default of an enrollment from before degrees), Keychain, modes, liveness, camera, the terminal's camera permission, failures and the app holding the hub's camera grant; exit 1 on a `fail` | anywhere |
| `tau guard status [--json]` | the state as the running hub reports it (`GET /guard/status`); without an active guard prints `off`; exit 0 when no hub runs, 1 on a hub error | anywhere |
| `tau guard lock` | locks every guarded channel (`POST /guard/lock`, trigger `command`) | anywhere; also over SSH |
| `tau guard log [--since WHEN] [--json]` | the audit log; `WHEN` is a duration (`30m`, `2h`, `7d`) or an ISO date or time | anywhere |

After `setup` or `forget`, restart the hub and any open `tau chat`, `tau tui` or tau Desktop window. The [CLI reference](cli.md#tau-guard) has the `--help` texts.

## States

| State | Meaning |
|---|---|
| `off` | no guard is active |
| `locked` | guarded channels refuse every turn; `lock_trigger` says why |
| `verifying` | an unlock is running; concurrent unlocks join it (same attempt, same verdict) |
| `unlocked` | admitted; `since`, `expires_at`, `face_seen_at` and `method` are set |
| `unavailable` | the guard cannot decide (no hub, bad config, reflex loop stalled); it refuses like `locked` |

Next to the state the hub keeps `step_up_active`, `failures` (counted failures since the last unlock), `cooldown_until`, `seq` (grows with every change), `face_seen_at`, the HID idle time since the last face, `screen` (`locked`, `unlocked` or `unknown`) and `camera` (`ok`, `denied`, `not_determined`, `unavailable`).

### Lock triggers

`command`, `idle`, `screen_lock`, `sleep` (more than 30 s of drift between the wall clock and the monotonic clock across two ticks), `max_age`, `hub_stop`, `telegram`, `step_up_failed`, `startup`.

The reflex checks (max age, sleep, idle, screen lock) run inline at every admission and step-up and in a loop every 2 s. If the loop's last tick is older than 6 s, admission refuses with `unavailable`. They need no model, no cloud and no mesh. Every lock cancels a running attempt and releases the camera; on guarded channels it also cancels the running turn and rejects a pending approval.

### Transitions

| Event | From | To / effect |
|---|---|---|
| hub start | – | `locked` (trigger `startup`) |
| unlock request | `locked`, `unlocked` | `verifying` |
| unlock ok | `verifying` | `unlocked`; `face_seen_at` = now; failures reset after the channel reported them |
| unlock fail | `verifying` | the previous state; a counted reason moves the failure counter |
| step-up request | `unlocked` | stays `unlocked` with `step_up_active`; waits behind a running check |
| step-up request | `locked`, or an unlock from `locked` running | refused (`locked`); the camera never opens |
| step-up ok | – | `face_seen_at` = now; `since` and `expires_at` unchanged |
| step-up or recheck fail with `no_match`, `spoof` or `multiple_faces` | `unlocked` | `locked` (trigger `step_up_failed`) |
| recheck ok | `unlocked` | `face_seen_at` = now; idle since the last face = 0 |
| any lock trigger | any | `locked`; a running attempt ends as `cancelled`, or as `spoof` when a head-turn prompt was up |

### Failures and cooldown

`no_match`, `spoof` and `multiple_faces` are counted failures, for unlock, recheck and step-up alike. Three within 10 minutes start a cooldown of 30 s; each further counted failure doubles it, up to 15 minutes. A match, or 10 quiet minutes, resets the doubling. During a cooldown a check answers `cooldown` with `retry_after` (seconds). The count and the cooldown survive a hub restart (`failures.json`).

## Reasons

### Admission (`POST /guard/admit`, `Admission.reason`)

| Reason | Meaning |
|---|---|
| `ok` | admitted |
| `locked` | refused: the guard is locked |
| `recheck` | admitted after a passive presence check: the channel runs `unlock(kind="recheck")` and sends the kept prompt again |
| `not_enrolled` | active but nothing enrolled |
| `cooldown` | refused during a cooldown |
| `unavailable` | the guard cannot decide (no hub, bad answer, stale reflex loop, 3 s timeout) |
| `unsupported_platform` | not macOS |
| `error` | anything else, including an unknown value |

A refused turn yields a notice and `TurnEnd("locked")`: nothing is appended to the history, no model is called, no repair turn follows. `TauAgent.ask()` raises `GuardLocked(reason)`.

### Verdicts (`GuardVerdict.reason`, an attempt's `reason`)

| Reason | Meaning | Counted |
|---|---|---|
| `match` | verified; `method` is `face` (or `touch_id`, issue 114) | – |
| `no_match` | a quality frame did not match the template | yes |
| `no_face` | no face was seen | no |
| `multiple_faces` | a second face big enough to count | yes |
| `spoof` | the head-turn challenge failed; the audit's `liveness` names the rule (see below) | yes |
| `timeout` | the check ran out of time | no |
| `cancelled` | cancelled by the caller or by a lock | no |
| `too_dark`, `face_too_small` | the frames never passed the quality gates (also live hints) | no |
| `camera_busy`, `camera_unavailable` | another app holds the camera, or no single built-in camera was found | no |
| `camera_denied`, `permission_pending` | no camera grant for the app that runs the hub, or the macOS prompt is still open | no |
| `not_enrolled`, `template_invalid`, `model_changed` | no template, an unreadable one (or one whose enrollment id is not the marker's), a changed face model | no |
| `key_unavailable` | the Keychain key could not be read | no |
| `cooldown` | refused during a cooldown; `retry_after` is set | – |
| `locked` | a step-up while locked | – |
| `touch_id_unavailable`, `touch_id_failed` | Touch ID missing (closed lid, no sensor, until 114) or not confirmed | no |
| `unsupported_platform`, `unavailable`, `busy`, `error` | not macOS; no hub or bad answer; another check runs; anything else | no |

### Head-turn challenge

The head's yaw comes from `cv2.solvePnP`: YuNet's five landmarks fitted to a generic 3D head, seen by a camera whose focal length is the frame width. Everything is in degrees relative to the median yaw of the attempt's frontal frames, so a seat off to the side works.

| | |
|---|---|
| steps | 2 for an unlock, 3 for a step-up, left or right at random |
| pause before each prompt | random 0.3–0.9 s |
| time per step | 4 s from the prompt |
| turn | at least `max(12°, 0.5 × the calibrated turn)` the asked way |
| hold | random 0.3–0.6 s; the turn may sag 3° while held |
| return | within 6° of the frontal yaw, or past it |
| frames that count | landmarks fit the head within 0.10 eye distances (1.5 × the frontal fit when larger); a 3-frame running median |

An enrollment calibrates the sign of a left turn and the owner's range to each side. One made before degrees (issue 127) keeps working: its sign stays and a 12° turn is asked each way; `tau guard enroll` measures the owner's own range.

### Liveness rules (`liveness` of a `spoof`)

| Rule | When |
|---|---|
| `overshoot_before_target` | 8° or more the wrong way before the turn is held |
| `oscillation` | more than 3 reversals of direction (6° each) within one step |
| `moved_between_prompts` | more than 10° from the frontal yaw while no prompt is up (20° on the far side of a return swing) |
| `no_turn` | the turn never reached its target in time |
| `too_slow` | the turn reached its target but was not held in time |
| `no_return` | the head did not come back in time |
| `face_lost` | the face was gone for more than 0.2 s, or its box jumped |
| `step_identity` | the frames near the centre around a turn did not match the owner |
| `abandoned` | cancelled, or locked, while a head-turn prompt was up |

A flat photo turned about the vertical axis reads at most about 10° while it is turned up to 50° (across sizes, seats and a 15° tilt; a few degrees when it faces the camera squarely), and turned further its landmarks stop fitting a head. A head reads the full angle.

### Progress steps

`starting`, `look`, `turn_left`, `turn_right`, `center`, `touch_id`, `done`, and for enrollment `look_up`, `look_down`, `turn_more`. A progress event carries `step`, `seq`, `deadline` (UTC, when the step times out) and `hint` (a verdict reason used as a live hint, such as `too_dark`).

## Channels

| | Guarded: admission and step-up | Identified elsewhere: `guard=None` |
|---|---|---|
| **Trusted** (may approve tier 2) | TUI (local, SSH or mosh, tau Desktop, a web tab), `tau chat` | Telegram (chat-id allowlist, polled directly) |
| **Not trusted** (never approves) | `tau ask`, voice (later) | network turns (`net`: no tools, approvals refused) |

`build_agent(guard=DISCOVER)` is the default: a caller that passes nothing is guarded when a guard is active, so unknown and future channels (the MCP server, sub-taus run by `ask_sub` under the delegating turn's guard) land in the guarded column. Only `TelegramService` and tau-net's network turns pass `guard=None`, and a repo-rule test fails on any other `guard=None` in `packages/*/src`. No flag, variable or config key picks a channel.

While locked, only `/help`, `/lang`, `/guard` and `/quit` run (`ALLOWED_WHILE_LOCKED`).

## The tier gate

`TierGate(guard=…, client_id=…)`; every `TierGate(` call in `packages/*/src` must pass `guard=` explicitly.

- **Before a tier-1 or tier-2 call,** admission runs again. A refusal refuses the call without asking the approver; the model reads `tau was locked before the user answered.` and the `tool_call` event records approval `locked`.
- **After `APPROVED` on a tier-2 call,** admission runs once more (a lock during the dialog refuses the call the same way), then `step_up`. Its progress becomes `guard` agent events (`{"action": "challenge", "step", "hint", "deadline", "request_id"}`). Anything but `True` turns the decision into `REJECTED`; the model reads `The guard could not confirm the user's identity.` and the `approval` event records `step_up: passed | failed`.
- **Exempt calls** (routines) reach neither check.

No path produces `APPROVED` from the guard.

## Control routes

The hub's control API listens on `127.0.0.1:<control_port>` only. **Only `GET /health` and `GET /status` are open.** Every other route is protected: `GET /spend`, the six `/guard/*` routes and every route a hub service adds (`ControlApi.add_route(..., open=False)` is the default).

### Signed requests

The hub writes a fresh token to `TAU_DATA_DIR/hub/control.token` at every start (32 random bytes, urlsafe, mode `0600`, in a `0700` directory) and removes it on a clean stop. The token never travels:

| Header | Value |
|---|---|
| `X-Tau-Nonce` | fresh per request, at most 128 characters |
| `X-Tau-Auth` | `hex(HMAC-SHA256(token, "req" \| nonce \| METHOD \| path))` |
| `X-Tau-Proof` (answer) | `hex(HMAC-SHA256(token, "resp" \| nonce \| METHOD \| path \| status \| body))` |

The fields are joined with a literal `|` byte, the method is upper case and the path has no query string. The `req` and `resp` domains keep a request's auth value from passing as a proof.

The hub refuses a protected request with 403 JSON when the token file is missing, empty or no longer holds this hub's token; when the nonce or `X-Tau-Auth` is missing or wrong (a raw token in a header is never accepted); when any `Origin` header is present; and when a POST's media type is not `application/json`. A client must check `X-Tau-Proof`: after a hard hub exit, any local process could bind the free port, and only the proof tells the real hub from a squatter.

`tau_core.hub.HubClient` does all of this: loopback only, no proxies, no redirects, the token re-read for every request and once more after a 403, the proof checked:

```sh
uv run python -c 'from tau_core import Config; from tau_core.hub import HubClient; print(HubClient(Config.load()).get("/spend", timeout=5))'
```

The open `/status` carries only `guard: {state, enrolled, available, reason}`, with no timestamps, which would tell other local accounts when the owner left.

### `/guard/*`

A route can only ask the hub to look. No route accepts a verdict, a score, an image or an embedding. The `channel` fields are audit labels and never change policy. The routes exist only while the guard is active; otherwise they answer 404.

| Route | Body or query | Answer |
|---|---|---|
| `GET /guard/status` | `?since=<seq>&wait=<0..25>[&attempt=<id>]` (long poll) | every `GuardStatus` field plus `enrollment`, `screen`, `step_up_active` and `attempt` |
| `POST /guard/admit` | `{channel, session_id, client_id}` | `{allowed, reason, enrollment, state}`, with the reflex checks evaluated inline |
| `POST /guard/verify` | `{channel, client_id, kind: "unlock" \| "recheck" \| "step_up", request_id?, tool?, policy?}` | `202 {attempt, seq}` (joins a running unlock); refused with `409 {reason}` (`locked`, `busy`, `not_enrolled`, `unavailable`) or `429 {reason: "cooldown", retry_after}` |
| `POST /guard/cancel` | `{client_id, attempt?}` | `{ok}` |
| `POST /guard/lock` | `{channel, client_id, trigger}` | `{state: "locked"}`, idempotent |
| `POST /guard/enroll` | `{client_id, add?}` | `202 {attempt, seq}`; LocalAuthentication first |

A body with an unknown key, a missing required key or a wrong type gets `400 {reason: "error", error}`.

An **attempt** is `{id, kind, step, seq, deadline, hint, done, ok, reason, method, retry_after}`. With `attempt=<id>`, `GET /guard/status` returns that attempt's record whether it is queued, running or finished, and `null` once the id is unknown or expired; a finished record is kept for at least 60 s. Only a finished attempt with `ok: true`, `reason: "match"`, a `method`, `state: "unlocked"` and the local marker's `enrollment` id is a success; `HubGuard` treats everything else, a missing proof included, as locked.

## Audit log

`TAU_DATA_DIR/guard/audit.jsonl`, one JSON object per line, mode `0600`, rotated at 1 MiB with 3 files kept (`audit.jsonl`, `.1`, `.2`). `tau guard log` reads it.

```json
{"v": 1, "at": "2026-09-30T08:12:03+00:00", "event": "verify", "channel": "tui", "client_id": "3f9a1c0b7e2d4a61", "trigger": null, "ok": true, "reason": "match", "score": 0.71, "liveness": "challenge", "duration_ms": 2380}
```

| Key | Always | Meaning |
|---|---|---|
| `v` | yes | schema version, `1` |
| `at` | yes | UTC, ISO 8601 with seconds |
| `event` | yes | `verify`, `step_up`, `recheck`, `lock`, `unlock`, `enroll`, `forget`, `cooldown`, `camera_open`, `touch_id` |
| `channel`, `client_id`, `trigger` | yes | audit labels (`null` when they do not apply); `client_id` is random per process; `trigger` is a lock trigger for `lock` |
| `ok`, `reason` | yes | the outcome and its verdict reason |
| `duration_ms` | yes | how long it took |
| `score` | no | the similarity score, rounded to 2 decimals |
| `liveness` | no | `challenge` or `passive` for a face match; for a `spoof`, the liveness rule that failed |
| `request_id`, `tool` | no | the tier-2 call a step-up belonged to |

A record never holds an embedding, a frame or anything about another person. Strings are cut to 128 characters and non-printable characters become `?`, so a caller's label cannot drive the terminal that prints the log. The hub log gets no verdicts and no scores.

## Files

Under `TAU_DATA_DIR/guard/`, mode `0700`, left out of backups and never pushed by `tau cloud push`:

| File | What it is |
|---|---|
| `enrolled` | the public marker, JSON `{"v": 1, "enrollment": "<id>", "model": "<sha256>", "created": "<iso>"}`; nothing biometric. While it exists the guard is active |
| `owner.face.v1.bin` | the template, `0600`, written atomically: `b"TAUG1" \| nonce(12) \| AES-GCM(payload)` with `b"tau-guard/v1\|" + model_sha256` as associated data. The payload holds the renormalised mean embedding, the samples and the head-turn calibration |
| `models/face_recognition_sface_2021dec.onnx` | SFace, installed by `tau guard setup`, sha256-checked at every load |
| `audit.jsonl` (+ `.1`, `.2`) | the audit log |
| `failures.json` | the failure count and cooldown, `0600` |
| `worker.log` | the worker's stderr, `0600`, rotated past 1 MiB; never a frame or an embedding |

Elsewhere:

- **The template key**, 256 bits, in the macOS Keychain: service `tau-guard`, account `template-key-v1`, always through keyring's macOS backend. Only the worker reads it.
- **YuNet** (`face_detection_yunet_2023mar.onnx`, MIT) ships inside the `tau-guard` wheel with its license.
- **The control token**, `TAU_DATA_DIR/hub/control.token`.

## Models and credits

| Model | License | Size | How it arrives |
|---|---|---|---|
| YuNet 2023mar (face detection, five landmarks) | MIT, © 2020 Shiqi Yu | 232 KB | in the wheel |
| SFace 2021dec (128-d face embeddings) | Apache-2.0 (OpenCV Zoo) | 38.7 MB | `tau guard setup`, from opencv_zoo at commit `47534e2`, or `--model-file` |

The stack needs only `opencv-python-headless` and `numpy`; on macOS also `keyring` and the pyobjc AVFoundation, Quartz and LocalAuthentication frameworks.
