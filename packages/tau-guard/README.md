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
| `tau.commands` | `guard` | `tau guard setup`, `enroll`, `verify`, `forget`, `doctor`, `status`, `lock` and `log` |

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

Touch ID (the unlock fallback, a Touch ID step-up, biometrics-only authorisation of
re-enrollment and forget) comes with issue 114.

## The face check

Everything runs in the worker, on this Mac; frames exist only in the worker's memory and are
never saved.

- **Camera.** Only the built-in camera: the AVFoundation device of type
  `AVCaptureDeviceTypeBuiltInWideAngleCamera` on transport `bltn`. Continuity Camera and
  virtual cameras (OBS) are never picked, because keeping them out is the only defence against
  injected frames. The OpenCV index is the device's place in the uniqueID-sorted list of video
  and muxed devices, the order OpenCV's AVFoundation backend uses; the list is read again right
  after the open, and a change aborts with `camera_unavailable`. The worker checks the camera
  permission itself (`permission_pending` asks macOS, `camera_denied`), drops 5 warm-up frames,
  keeps the camera on for at most 20 s and releases it on every path, a kill included.
- **Models.** YuNet 2023mar finds faces and five landmarks. SFace 2021dec turns a face into an
  L2-normalised 128-d embedding, compared with the template by cosine similarity. Both files
  are sha256-checked at every load. Only `opencv-python-headless` and `numpy` are needed.
- **Quality gates.** A frame counts when the detector score is at least 0.90, the eye distance
  at least 40 px (hint `face_too_small`), the brightness at least 60 (hint `too_dark`) and the
  sharpness at least 30. A second face counts only when its eye distance is at least 45 % of
  the owner's and at least 40 px, so a photo on the wall does not block; a counted one aborts
  with `multiple_faces`.
- **Match.** At least 3 of the last 5 quality frames reach the threshold: `unlock_threshold`
  0.50 (never below 0.45), `step_up_threshold` 0.55 for step-ups and presence rechecks.
- **Head-turn challenge.** After a frontal match, 2 random steps for an unlock and 3 for a
  step-up. The head's yaw comes from `cv2.solvePnP`, which fits YuNet's five landmarks to a
  generic 3D head (degrees, relative to the frontal frames of the attempt): turn left or right
  by at least `max(12°, half your calibrated turn)`, hold for a random 0.3-0.6 s, come back
  within 6° (a swing past the centre on the way back is fine). Each prompt follows a random
  0.3-0.9 s pause and has 4 s. The check fails as `spoof`, naming the rule in the verdict and
  the audit log: 8° the wrong way before the turn is held (`overshoot_before_target`), more
  than 3 reversals within one step (`oscillation`), more than 10° of movement while no prompt
  is up (`moved_between_prompts`; up to 20° on the far side of a return swing), and a step not
  done in time (`no_turn`, `too_slow`, `no_return`). A flat photo turned about the vertical
  axis reads a few degrees at most, and turned further its landmarks stop fitting a head, so
  those frames count for nothing. Exactly one face stays in view (box IoU above 0.3 from frame
  to frame, never gone for more than 0.2 s: `face_lost`), the frames near the centre between
  the turns must match you too (`step_identity`), and a second frontal match closes the check.
  Cancelling or locking while a turn prompt is up counts like a failed step (`abandoned`). A
  prompt is shown only when its step can end before the camera's 20 s limit. A presence
  recheck is a passive strict match, and so is a step-up within
  `step_up_challenge_fresh_seconds` of a passed challenge.
- **Enrollment.** Guided, 15-20 s at most: look, turn left, turn right, up, down, with live
  hints. 10-20 samples, none closer than 0.97 to another, each at least 0.55 to the mean of the
  others (leave-one-out); the template is their renormalised mean, stored with the turn
  calibration in degrees (an enrollment from before degrees keeps working with a 12° turn each
  way; `tau guard enroll` measures your own range). It always runs behind LocalAuthentication (Touch ID or the Mac password, asked
  only once the camera permission is granted), is refused over SSH, and runs through the hub
  when a hub with an active guard runs (`POST /guard/enroll`), else in a local worker. On a
  first `tau guard setup` the hub's guard is not active yet, so the app that runs the hub asks
  for its own camera permission at the first unlock.
- **Storage.** `TAU_DATA_DIR/guard/owner.face.v1.bin` (0600, atomic) is
  `b"TAUG1" | nonce | AES-GCM(payload)` with the model's sha256 as associated data; the 256-bit
  key is in the macOS Keychain (service `tau-guard`, account `template-key-v1`; always keyring's
  macOS backend, whatever `PYTHON_KEYRING_BACKEND` says) and is read only in the worker, with a
  timeout. A copy of the data dir or a backup cannot decrypt it. The public marker
  `guard/enrolled` holds `{v, enrollment, model, created}` and nothing biometric; a template
  file must carry the marker's enrollment id. The template is read again for every check, so
  `tau guard forget` works at once.

**Honest limits.** Without an infrared camera, a 2D webcam check is a presence and convenience
factor. It keeps a housemate out of tau's own surfaces and stops low-effort photo and screen
attacks. It does not stop a real-time deepfake, a determined attacker with a good video, or
anyone with a shell in your account: a synthetic looping clip of natural head turns passes a
few percent of the unlock challenges (see issue 112). That is why it is only ever required in
addition to the human approval.

### Models and credits

| Model | License | How it arrives |
|---|---|---|
| YuNet 2023mar (`face_detection_yunet_2023mar.onnx`, sha256 `8f2383e4...52fa4`) | MIT, © 2020 Shiqi Yu (`tau_guard/models/LICENSE-yunet`) | in the wheel |
| SFace 2021dec (`face_recognition_sface_2021dec.onnx`, sha256 `0ba9fbfa...34e79`) | Apache-2.0 (OpenCV Zoo) | `tau guard setup` downloads it from opencv_zoo at commit `47534e2`, or `--model-file PATH` |

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
| `POST /guard/enroll` | `{client_id, add?}` | `202 {attempt, seq}`; LocalAuthentication first |

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
verify_timeout_seconds = 15         # 5-60 for the frontal match; the camera stops at 20 s anyway
unlock_threshold = 0.50             # 0.45-0.95
step_up_threshold = 0.55            # 0.45-0.95; step-ups and presence rechecks
step_up_challenge_fresh_seconds = 120  # 0-600; a step-up this soon after a challenge is passive
unlock_liveness = "challenge"       # or "none" (the doctor warns: a photo could unlock)
step_up = "face"                    # face | face_or_touch_id | touch_id | none
unlock_fallback = "touch_id"        # touch_id | touch_id_or_password | none (issue 114)
camera = "builtin"                  # or a camera's AVFoundation uniqueID
```

A client sends its own `step_up` and `unlock_liveness` values with every check, and the hub
applies the stricter of its own value and the client's.

## Commands

```sh
tau guard setup [--model-file PATH] # model, enrollment, one check, [component.guard] enabled = true
tau guard enroll [--add]            # enroll again, or add samples under other light
tau guard verify [--explain[=all]]  # one check; --explain highlights each prompt and prints
                                    # every 3rd frame's numbers (=all: every frame)
tau guard forget                    # remove template, marker and key; the guard is off
                                    # (exit 1 if the Keychain kept the key; run it again)
tau guard doctor                    # everything the face guard depends on
tau guard status [--json]           # the state as the running hub reports it
tau guard lock                      # lock every guarded channel now
tau guard log [--since 2h] [--json] # the audit log
```

`setup`, `enroll` and `forget` run only at the Mac (macOS, no `SSH_CONNECTION`). After
`setup`, restart the hub and any open `tau chat`, `tau tui` or tau Desktop window. While you
are away from the Mac, remote `tau tui` and `tau chat` and `tau ask` stay locked (until issue
117).

## Tests

`tau_guard.testing` has `FakeClock`, `FakePresence`, a fake worker
(`fake_worker_command(script)`) that speaks the worker protocol from a JSON script, and fakes
for the face check: synthetic YuNet rows and embeddings (`face_row`, `identity`, `variant`), a
`FakeEngine`, a `FakeFrameSource`, a `SimulatedUser` who follows the prompts (with switches for
every way an attempt must fail), `FakeLocalAuth` and `fake_deps` for running the worker's
operations in-process. No test opens a camera, a microphone, the Keychain or a Touch ID prompt,
and every macOS call sits behind a protocol and is imported lazily, so the suite runs on Linux.

The real-model tests are opt-in: they fetch SFace and a few public-domain portraits by pinned
URL and sha256 into a cache outside the repo (`TAU_GUARD_TEST_CACHE`, default
`~/.cache/tau-guard-tests`; `TAU_GUARD_SFACE=PATH` installs a local SFace file instead). No
face image is ever committed.

```sh
uv run pytest -q packages/tau-guard
uv run pytest -m models packages/tau-guard   # opt-in, real models
uv build --package tau-guard
```
