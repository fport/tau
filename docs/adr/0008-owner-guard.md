# ADR 0008 · Owner guard

Date: 2026-09-30 · Status: accepted · Amends [ADR 0001](0001-approval-through-strands-hooks.md) (the tier gate gains a lock check and a tier-2 step-up), [ADR 0005](0005-components-and-entry-point-groups.md) (control routes are protected by default; in-hub channels opt out of the guard in code), [ADR 0006](0006-private-first-topology.md) §5 (on a guarded hub a trusted channel also needs the owner verified at the Mac), [ADR 0007](0007-cloud-mode-and-tau-network.md) (network turns opt out of the guard; cloud mode has no guard sensor). Every other rule of those ADRs stands.

## Context

The owner wants tau to recognise them by face through the Mac's camera and only then start working: one central guard for `tau tui`, `tau chat` and a separate desktop app, and later voice commands answered in text. On 2026-09-30 the owner chose:

- **Door mode.** Guarded local channels stay locked until the owner is verified. A tier-2 call on them also needs a fresh check after the approval (a **step-up**).
- **A separate desktop app**, `apps/tau-desktop`: Tauri, xterm.js and a PTY that runs `tau tui`.

Today anyone at the owner's unlocked Mac who opens the TUI can read every session and all memory, and can approve a tier-2 action with one key. The control API on `127.0.0.1` checks only the `Host` header, so any local process can call any route.

A probe on the owner's Mac (Apple M5, macOS 26.3.1; the camera was never opened) measured the face stack this ADR relies on, and its numbers are quoted below. Four adversarial reviews of a first design (security, architecture, feasibility, completeness) shaped the rules.

## Threat model

Assets: those of ADR 0006 (life data, credentials, the hub, home devices), plus a new one: the owner's **face template**. It is biometric data. It must never leave the hub, and a copy of the data dir must not reveal it.

In scope:

- **T1** Someone at the owner's unlocked Mac using *tau's own surfaces*: the TUI, tau Desktop, the terminal lock prompt, and voice later. They do not run commands or edit files.
- **T2** Other people's speech reaching voice (later).
- **T3** Any local process or any web page calling guard routes or other control routes.
- **T4** A copy of `TAU_DATA_DIR` or a backup revealing the template.
- **T5** A printed photo, or a still or looping clip on a phone held up to the camera.
- **T6** Injected text trying to change guard state.
- **T7** A client claiming to be something it is not (remote, Telegram, web) to skip the check.

Out of scope, stated plainly:

- **Anyone with a shell in the owner's account.** They can edit `tau.toml`, delete files, read `.env` or call `build_agent(guard=None)`. The Mac's screen lock and FileVault are the real boundary for the account. The guard protects tau's surfaces, not the account.
- **Stronger face attacks:** a real-time deepfake, a 3D mask, an identical twin. Close relatives score higher than the LFW numbers below suggest.
- **Coercion, and more than one owner.** The Telegram allowlist counts as the owner's own chats.
- **Telegram Desktop logged in on the same Mac.** This is an accepted residual risk. The guard guide recommends Telegram's local passcode.
- **The `channel` passed to `build_agent` is a label** chosen by tau's own entry points. Code that can call `build_agent` can skip the guard.

## Decision

1. **Door mode, gate only.** Guarded channels refuse every turn until the owner is verified, and a tier-2 call on them needs a step-up after the human approval. In v1 the guard only opens the door; nothing starts by itself on unlock. The TUI keeps a refused prompt in the composer, shows an "Unlocked" notice with the number of failed attempts since the last unlock, and makes no model call. Reacting to the owner's arrival (routines, a greeting) is later work built on `GuardService.subscribe` (121).

2. **One guard, in the hub, with a worker subprocess per attempt.** `tau-guard` (`packages/tau-guard`, import `tau_guard`) is a `tau.hub_services` component named `guard`. Every camera and LocalAuthentication operation runs in a short-lived worker, `python -m tau_guard.worker <op>` with `op` in `verify | enroll | touch_id | selftest`, spawned per attempt. It takes request JSON on stdin and writes JSON lines on stdout: `progress` events, then one final `verdict`. Its stderr goes to `TAU_DATA_DIR/guard/worker.log`. The service kills it on cancel, lock or timeout (SIGTERM, then SIGKILL after 1 s). Running the work in a worker means:
   - a native crash never takes the hub down;
   - OpenCV and AVFoundation output never reaches a TUI's terminal;
   - cancelling is a kill;
   - the Keychain read never blocks the hub's event loop;
   - the hub process never holds a template or an embedding.

   The worker inherits camera permission (TCC) from the hub's responsible process: TauBar, or the terminal that runs `tau hub run`. When no hub runs, guarded channels stay locked with a notice that says how to start one (TauBar → Run the hub, or `tau hub run`). An in-process fallback is later work (124).

3. **tau-core owns the seam and the route contract.** `tau_core.guard` defines the `Guard` protocol, its value types (`GuardStatus`, `GuardVerdict`, `GuardProgress`, `GuardTurn`, `Admission`), `GuardLocked`, and the closed reason lists (`VERDICT_REASONS`, `ADMISSION_REASONS`, `LOCK_TRIGGERS`, `PROGRESS_STEPS`):

   ```python
   class Guard(Protocol):
       name: str
       async def status(self) -> GuardStatus: ...
       async def watch(self, since: int, *, wait: float = 25.0) -> GuardStatus: ...
       async def admit(self, turn: GuardTurn) -> Admission: ...
       async def unlock(self, *, channel: str, client_id: str, kind: str = "unlock",
                        on_progress: Callable[[GuardProgress], None] | None = None) -> GuardVerdict: ...
       async def cancel(self, *, client_id: str) -> None: ...
       async def lock(self, *, channel: str, client_id: str, trigger: str = "command") -> None: ...
       async def step_up(self, request: ApprovalRequest, *, client_id: str,
                         on_progress: Callable[[GuardProgress], None] | None = None) -> bool: ...
   ```

   Every method fails closed: `admit` refuses, `step_up` returns `False`, and `unlock` returns a failed verdict. None of them raises into its caller except `asyncio.CancelledError`. tau-core ships two implementations, and no implementation that allows by default exists anywhere:
   - **`LockedGuard(reason)`** is always `unavailable` and refuses everything.
   - **`HubGuard(config)`** talks to the hub's `/guard/*` routes through `HubClient` (decision 8), and maps the answers strictly. Only an answer that says `unlocked` (or `allowed: true` from `/guard/admit`), with a valid response proof and an `enrollment` id equal to the local marker's, admits a turn. Everything else means locked (`unavailable`): `off`, 404, 403 after one token re-read, 5xx, a timeout, bad JSON, a missing proof or an enrollment mismatch.
     - `admit` has its own 3 s bound.
     - Blocking HTTP runs in daemon threads, never in `asyncio.to_thread`, which is joined at shutdown.
     - `unlock` and `step_up` post `/guard/verify`, long-poll `/guard/status?since=<seq>&attempt=<id>` for their own attempt and call `on_progress` on every change. A cancelled caller posts `/guard/cancel` and re-raises. A 403 is never signed, so its body never picks a verdict (`unavailable`).
     - The client sends its own weakening-sensitive policy (`step_up`, `unlock_liveness`), and the hub applies the stricter of the two.

   `resolve_guard(config)` returns `None` (no guard active), a `LockedGuard` or a `HubGuard`. A found guard is memoized per `(home, data_dir)`; `None` never is, because a remembered "no guard" would fail open for the life of a process that started before `tau guard setup`. The routes are fixed here, like `/health` and `/status`. All of them are protected and speak JSON:

   | Route | Body or query | Answer |
   |---|---|---|
   | `GET /guard/status` | `?since=<seq>&wait=<0..25>[&attempt=<id>]` (long poll) | every `GuardStatus` field, plus the `enrollment` id; with `attempt=<id>`, `attempt` is that attempt's record |
   | `POST /guard/admit` | `{channel, session_id, client_id}` | `{allowed, reason, enrollment}`, with the reflex checks evaluated inline |
   | `POST /guard/verify` | `{channel, client_id, kind: "unlock" \| "recheck" \| "step_up", request_id?, tool?, policy?}` | `202 {attempt, seq}`; joins a running unlock |
   | `POST /guard/cancel` | `{client_id, attempt?}` | `{ok}` |
   | `POST /guard/lock` | `{channel, client_id, trigger}` | `{state: "locked"}`, idempotent |
   | `POST /guard/enroll` | `{client_id}` | `202 {attempt, seq}`; runs LocalAuthentication first |

   An attempt is `{id, kind, step, seq, deadline, hint, done, ok, reason, method, retry_after}`. Its result is read through `GET /guard/status?attempt=<id>`, with the id from the `202` of `/guard/verify`. The `attempt` field then holds that attempt's own record, whether it is queued (a step-up behind a running verification, with `step: "starting"` and `done: false`), running or finished, and it is `null` once the id is unknown or expired. The hub keeps a finished record for at least 60 s. Without the parameter, `attempt` is the running attempt or `null`. A finished attempt with `ok: true` has `reason: "match"` and a `method`, and the same answer carries `state: "unlocked"` and the `enrollment` id; anything else is not a success. A refused `/guard/verify` answers 4xx with `{reason, retry_after?}`, for example `cooldown`. **A route can only ask the hub to look.** No route accepts a verdict, an image or an embedding. The `channel` fields are audit labels and never change policy. cv2 and pyobjc are never imported into a channel process. There is no new entry-point group. Inside the hub, `GuardService` implements `Guard` directly: in-hub callers find it with `hub.find_service("guard")` plus an `isinstance(Guard)` check. It also offers `subscribe(callback)` for state changes and `face_fresh(seconds)` for voice.

4. **Enablement is anchored in the data dir.** The guard is active when the public marker `TAU_DATA_DIR/guard/enrolled` exists **or** `[component.guard] enabled = true`. tau-guard writes the marker as JSON: `{"v": 1, "enrollment": "<id>", "model": "<sha256>", "created": "<iso>"}`. While the marker exists, `enabled = false` is ignored, and `tau doctor` says so. The only off switch is `tau guard forget`, behind LocalAuthentication, which removes the template, the marker and the Keychain key. The guard also fails closed in three cases:
   - a non-bool `enabled` or an unknown key in `[component.guard]` gives `LockedGuard`;
   - any platform but macOS gives `LockedGuard("unsupported_platform")`;
   - enabled but not enrolled means locked (`not_enrolled`), never off.

   A home switched through `TAU_HOME`, a fresh `tau init` or a TauBar setting therefore still finds the guard of the data it would read.

5. **Admission happens in `TauAgent.stream`, with stop reason `locked`.** `TauAgent` gains three fields: `channel`, `guard`, and `client_id`. The client id is random per process; it is an audit label and the key for later per-client grants, never a claim. `build_agent` gains `guard=DISCOVER` and `client_id=None`. `DISCOVER` calls `resolve_guard`, so a caller that does not pass a guard is still guarded when one is active. Channels that own a guard resolve it once per process and pass the same object to every build (`/new`, `/resume`, `/model`, a settings save).

   Admission runs inside the stream lock, before any history, prompt or SDK work. A refused turn:
   - emits a `guard` agent event;
   - yields a `Notice` in the UI language, then `TurnEnd("locked")`;
   - appends nothing to history, calls no model and needs no repair turn.

   `STOP_REASONS` gains `locked`. `TauAgent.ask()` raises `GuardLocked(reason)`. An admission answer of `recheck` makes the channel run the passive presence check (decision 10) and resend the kept prompt.

6. **Identified in-hub channels opt out in code, never by name.** Two in-hub channels pass `guard=None` to `build_agent`:
   - `TelegramService` (chat-id allowlist, polled directly);
   - tau-net network turns (`channel="net"`: no tools, every approval refused).

   A repo-rule test fails when `guard=None` appears in any `packages/*/src` file outside that allowlist. tau-core has no channel-name allowlist, and no CLI flag, environment variable or config key selects a channel. tau Desktop and web tabs (074) run `tau tui`, so they are guarded as `tui`. An out-of-process channel that is identified some other way, such as a remote session, gets in only through a per-client grant that the hub issues and checks (117).

7. **The tier gate checks the lock and steps up, and it can only narrow.** `TierGate` takes `guard=None, client_id=""`. A repo-rule test requires every `TierGate(` call in `packages/*/src` to pass `guard=` explicitly, so the reflex engine (037) and the MCP server (028) decide consciously. With a guard:
   - **Before a tier-1 or tier-2 call**, `admit` runs again. A refusal refuses the call without asking the approver. The tool result is the fixed note "tau was locked before the user answered.", and the `tool_call` event records approval `locked`.
   - **After the approver returns `APPROVED`** for a tier-2 call, still inside the approval lock, `admit` runs once more: a lock that happened while the dialog was open refuses the call the same way (approval `locked`), while `recheck` goes on, since the step-up is itself a face check. Then `step_up` runs. Its progress becomes `guard {"action": "challenge", "step", "hint", "deadline", "request_id"}` agent events, so the channel can show "turn left". Anything but `True` turns the decision into `REJECTED`, with the fixed note "The guard could not confirm the user's identity." The approval event records `step_up: passed | failed`. A `CancelledError` records `failed` and propagates.
   - **Exempt calls** (routines) reach neither check, so reflexes keep working without a camera, an LLM or the cloud.

   No path produces `APPROVED` from the guard. The human still gives the approval; the step-up is an extra factor, never a replacement.

8. **Control routes are protected by default, with signed requests and a response proof.** `ControlApi.add_route` takes `open=False` by default, and only `/health` and `/status` are open. The token never travels: a client signs every protected request with it, and the hub signs every protected answer.
   - **Request.** `X-Tau-Nonce` (fresh per request) and `X-Tau-Auth = hex(HMAC-SHA256(token, "req" | nonce | method | path))`, with the method in upper case and the path without its query string.
   - **Answer.** `X-Tau-Proof = hex(HMAC-SHA256(token, "resp" | nonce | method | path | status | body))`. The `req` and `resp` domains keep a request's auth value from ever passing as a proof.

   Before dispatch, the HTTP handler refuses a protected request with 403 JSON when:
   - the token file is missing or empty, or no longer holds this hub's token;
   - the nonce or `X-Tau-Auth` is missing or wrong (`hmac.compare_digest`); a raw token in a header is never accepted;
   - any `Origin` header is present;
   - a POST's media type is not `application/json` (parameters allowed).

   The hub writes `hub_dir/control.token` in `start()`, after it holds the hub lock. The token is 32 random bytes, urlsafe, in a file created exclusively, renamed into place and kept at mode 0600, and `hub_dir` is chmod 0700. On stop, the hub deletes the file only if it still holds its own token.

   After a hard hub exit (`kill -9`, a crash, a power loss) the token file stays behind, and any local process can bind the free port. Such a squatter sees only nonces and HMAC values it cannot sign with, so its answers fail the proof, and every client treats them as "no hub". The proof alone tells the real hub from a squatter; the enrollment id in the marker is public and is no secret. `HubClient` in tau-core is loopback-only, ignores proxies and refuses redirects (a 3xx is a bad answer). It re-reads the token on every request, retries once after a 403, and checks the proof. Clients never cache the token.

   The existing `GET /spend` becomes protected. The open `/status` gains only `guard: {state, enrolled, available, reason}`: timestamps would tell other local accounts when the owner left.

9. **The state machine.** The states are `off` (guard not active), `locked`, `verifying`, `unlocked` and `unavailable`. Orthogonal to them are `step_up_active`, `failures`, `cooldown_until`, `seq`, `face_seen_at` and the HID idle time since the last face. The code is pure (`tau_guard/state.py`) and unit-tested with a fake clock.

   | Event | From | To / effect |
   |---|---|---|
   | start | – | `locked` (trigger `startup`); an unlock is never restored |
   | unlock request | locked, unlocked | `verifying`; a concurrent unlock joins the running attempt (same attempt id, same verdict) |
   | unlock ok | verifying | `unlocked`; `since` = now, `expires_at` = now + max age, `face_seen_at` = now; failures reset after being reported |
   | unlock fail | verifying | back to the previous state; the failure counter moves (decision 13) |
   | step-up request | unlocked | stays `unlocked` with `step_up_active`; queues behind a running verification, bounded by its timeout |
   | step-up request | locked, or verifying an unlock from locked | returns `False` (`locked`); the camera never opens |
   | step-up ok | – | `face_seen_at` = now; `since` and `expires_at` unchanged |
   | step-up fail with `no_match`, `spoof` or `multiple_faces` | unlocked | `locked` (trigger `step_up_failed`) |
   | any lock trigger | any | `locked`; a running attempt is cancelled (`cancelled`) and the camera released |
   | recheck ok | unlocked | `face_seen_at` = now; idle since the last face = 0 |

10. **Reflex locks.** They are evaluated inline at every `admit` and `step_up`, and by a reflex loop every 2 s. `admit` refuses (`unavailable`) when the loop's last tick is older than 6 s, so a stalled loop fails closed. They need no LLM, no cloud and no mesh:
    - **Max age.** `max_unlock_hours` (default 8, range 1–24) on the UTC wall clock.
    - **Sleep.** A drift of more than 30 s between wall-clock and monotonic time across two ticks locks with trigger `sleep`. The macOS monotonic clock stops during sleep, so it cannot measure an unlock's age on its own.
    - **Idle.** HID idle from `CGEventSourceSecondsSinceLastEventType`; `idle_lock_minutes` (default 10, range 1–240).
    - **Screen lock.** `CGSSessionScreenIsLocked` from `CGSessionCopyCurrentDictionary()`, read inline and every tick. With no GUI session (a hub started over SSH) the state is unknown. It is reported, and while it stays unknown the unlock is capped at `idle_lock_minutes`.
    - **Presence recheck.** Admission answers `recheck` when HID idle since the last face match reached `recheck_after_idle_minutes` (default 3), or when that match is older than `presence_recheck_minutes` (default 30). The channel then runs `unlock(kind="recheck")`: a passive strict match of 3 frames out of 5, with no challenge, in about 1–1.5 s. A recheck that sees a non-matching face locks. This bounds how long someone who sits down at a Mac the owner just left can keep using tau, because anyone's typing resets the idle timer.

    Every lock cancels a running attempt and releases the camera. On guarded channels, a lock also cancels the running turn (notice `guard.locked_during_turn`) and rejects any pending approval.

11. **Guarded channels show the lock.** `/guard [lock|unlock]` joins the slash commands just before `/quit`; without an active guard it answers that the guard is off. While locked, only `ALLOWED_WHILE_LOCKED = {help, lang, quit, guard}` run. Each channel:
    - **TUI.** It resolves the guard once, in `build_app`, and shows an opaque lock screen before the first agent build; the setup wizard and the start-up settings screen never open while locked. While unlocked, it long-polls `guard.watch()`. On a lock it pushes the lock screen, cancels the running turn and dismisses an open approval dialog as rejected.
    - **Terminal.** `tau chat` shows a lock prompt and clears the screen and the scrollback when it enters it. It prints every challenge step, and it subscribes to its agent's event bus so step-up prompts appear.
    - **Telegram.** `/guard` shows the state and `/guard lock` locks, as the owner's remote kill switch. `/guard unlock` answers that unlocking happens only at the Mac.

12. **Verification uses the built-in camera, YuNet and SFace, and a head-turn challenge.**
    - **Camera.** By default only the built-in camera is used: pyobjc picks the device of type `AVCaptureDeviceTypeBuiltInWideAngleCamera` with transport `bltn`. The OpenCV index is its position in the uniqueID-sorted list of video and muxed devices, which is enumerated again right after the open; a changed list aborts with `camera_unavailable`. Keeping Continuity Camera and virtual cameras out is the only defence against injected frames. `[component.guard] camera` may name another camera id. The worker checks camera permission itself, drops 5 warm-up frames, keeps the camera open for at most 20 s and releases it in `finally`.
    - **Models.** YuNet 2023mar (MIT, 232 KB, vendored in the wheel) finds faces and five landmarks. SFace 2021dec (Apache-2.0, 38.7 MB, fp32) makes 128-d embeddings. `tau guard setup` downloads SFace from a URL pinned to one opencv_zoo commit and checks its sha256; `--model-file` covers offline installs. The whole stack needs only `opencv-python-headless` and `numpy`, not onnxruntime.
    - **Quality gates.** A frame counts when the detector score is at least 0.90 (0.75 on challenge frames), the eye distance at least 40 px (else hint `face_too_small`), the mean brightness at least 60 (else `too_dark`) and the sharpness at least 30. A second face counts only when its eye distance is at least 45 % of the primary face's and at least 40 px, so a photo on the wall behind the owner does not block. A counted second face aborts with `multiple_faces`.
    - **Match.** Each embedding is compared with the template by cosine similarity. A match needs 3 of the last 5 quality frames at or above the threshold: `unlock_threshold` 0.50 (floor 0.45), `step_up_threshold` 0.55, within a 15 s timeout. Measured on LFW with a 5-sample template (217 identities, 3,737 genuine and 2,866,739 impostor probes):
      - at 0.50, FAR 3.3e-5 and FRR 0.5 %;
      - at 0.55, FAR 2.8e-6 and FRR 1.1 %.

      On the standard 6,000 LFW pairs, SFace reached 0.9942 accuracy. Requiring 3 of 5 frames lowers FRR but not FAR, because frames of one impostor are correlated.
    - **Head-turn challenge** (against T5). The head's yaw is measured in degrees: `cv2.solvePnP` fits YuNet's five landmarks to a generic 3D head (x and y from YuNet's own landmark layout on frontal faces, depths from MediaPipe's metric canonical face: eyes 38 mm and mouth corners 32 mm behind the nose tip), with the focal length equal to the frame width and the principal point in the middle. On 18 real faces this yaw agrees with MediaPipe's head pose (slope 1.02, r = 0.83). The baseline is the median yaw of the attempt's frontal frames, and enrollment calibrates the sign of a left turn and the owner's amplitude to each side in degrees. A step passes when the turn reaches max(12°, 0.5 × the calibrated amplitude) in the asked direction, holds for a random 0.3–0.6 s (it may sag 3° while held) and comes back within 6° of the baseline or swings past it. The check fails with `spoof`, and the verdict's `liveness` names the rule: 8° the other way before the hold is done (`overshoot_before_target`), more than 3 reversals of 6° within one step (`oscillation`), more than 10° from the baseline while no prompt is up, 20° on the far side of a return swing (`moved_between_prompts`), and a step not done in time (`no_turn`, `too_slow`, `no_return`).
      - **Why degrees** (issue 127). The owner's first live try failed with the proxy: the turn moved it by about 0.07 against a rule of Δp ≥ 0.20, which asks for about 20° of real yaw, and the proxy mixes a head tilt into the yaw. The return swing past the centre, which every real head makes, aborted as an overshoot, and the check could not say which rule had failed.
      - **Against a flat photo.** Turned about the vertical axis, a printed face reads at most about 10° up to 50° of turn (sizes, seats and a 15° tilt; under 4° up to 40° when it faces the camera squarely), and beyond that its landmarks stop fitting a head. Frames whose reprojection error is above 0.10 eye distances (or 1.5 × the frontal frames' error, when that is larger) count for nothing. Real faces fit within 0.02–0.08. Each step sees a running median of the last 3 frames that fit.
      - An enrollment made with the proxy keeps its sign and uses 24° to each side (a 12° target), so nobody has to enroll again; `tau guard enroll` measures the owner's own range.
      - Each prompt follows a random 0.3–0.9 s pause and gets 4 s from the moment it is published. The deadline travels in the progress event.
      - Unlock asks for 2 steps, step-up for 3 (8 possible sequences).
      - Identity is checked on frontal frames before and after the steps. Exactly one face must stay in view, with box IoU above 0.3 from frame to frame.
    - **Modes.** `unlock_liveness = "challenge" | "none"`, default `challenge`; `none` is a doctor warning. Within `step_up_challenge_fresh_seconds` (default 120) of a check that passed the challenge, a step-up is a strict passive match, so a robot task with three tier-2 calls does not cost nine head turns.
    - **Latency.** Detection plus embedding take 7.9 ms per 640×480 frame on OpenCV 5.0 (9.8 ms on 4.14), and the whole per-frame pipeline about 10–13 ms. A 3-of-5 decision needs about 100–170 ms of frames, plus camera start-up (not measured; estimated at 0.5–1.5 s).
    - **Enrollment.** Enrollment is guided and takes 15–20 s, with live text hints and five poses. It keeps 10–20 samples, skipping any with cosine similarity above 0.97 to one already kept, and requires a leave-one-out score of at least 0.55. The template is the renormalised mean of the samples; the yaw calibration is stored with it. On macOS enrollment is always behind LocalAuthentication. It runs through the hub (`POST /guard/enroll`) when a hub runs, so the same process holds the camera permission; otherwise the CLI runs a local worker. It is refused when `SSH_CONNECTION` is set.

13. **Failures, cooldown and audit.** `no_match`, `spoof` and `multiple_faces` count as failures, for unlock, recheck and step-up alike. Three within 10 minutes start a cooldown of 30 s that doubles up to 15 minutes; during it the verdict is `cooldown` with `retry_after`. A step-up that fails with one of these reasons locks the guard, and the next successful unlock shows the count.

    `TAU_DATA_DIR/guard/audit.jsonl` (0600, rotated at 1 MiB, 3 files kept) records verify, step-up, recheck, lock, unlock, enroll, forget, cooldown, camera-open and Touch ID events. Each record carries the channel, client id, trigger, outcome, reason, a score rounded to 2 decimals and the duration. It never holds an embedding, a frame or anything about another person. `tau guard log` reads it.

14. **Storage, encryption and backups.** `TAU_DATA_DIR/guard/` is mode 0700, set explicitly.
    - **The template file** `owner.face.v1.bin` (0600, written atomically) is `b"TAUG1" | nonce(12) | AESGCM(key).encrypt(nonce, payload, aad=b"tau-guard/v1|" + model_sha256)`. The payload is `{v, enrollment, created, model, dim, template, samples, calibration}`.
    - **The key** (256 bits) lives in the macOS Keychain (through `keyring`, service `tau-guard`, account `template-key-v1`) and is read only inside the worker, with a timeout. A copy of the data dir or a backup therefore cannot decrypt the template (T4).
    - **Freshness.** The hub reads the template again for every verification, so `forget` and a re-enrollment take effect at once. A model change gives `model_changed` and asks for a re-enrollment behind LocalAuthentication.
    - **Other people.** Frames of anyone exist only in the worker's memory. There are no intruder snapshots.
    - **Backups.** `TAU_DATA_DIR/guard/` is excluded from backups (018) and from anything else that leaves the hub.

15. **Touch ID.** A `LocalAuthFactor` runs `LAContext` in the worker. It uses the biometrics-only policy with reuse duration 0, pins `domainState` at enrollment (a changed fingerprint set refuses with `touch_id_failed`), and is invalidated after 30 s. A closed lid or a missing sensor gives `touch_id_unavailable`. It serves three purposes:
    - **Enroll and forget.** Touch ID authorises them. The device-owner policy (Touch ID or the Mac password) covers the first enrollment and Macs without Touch ID.
    - **Unlock fallback.** `unlock_fallback = "touch_id" | "touch_id_or_password" | "none"`, default `touch_id` where available, is offered after two face failures or any `camera_*` verdict.
    - **Step-up.** `step_up = "face" | "face_or_touch_id" | "touch_id" | "none"`, default `face`.

    Like the face check, Touch ID only ever narrows.

16. **TauBar holds the camera permission, and tau Desktop holds none.** TauBar runs the hub, so it carries `NSCameraUsageDescription` and `NSMicrophoneUsageDescription`, the camera and audio-input entitlements, and a stable signing identity; an ad-hoc signature resets the camera grant on every build. Both apps deny every webview media request, because wry grants them by default. tau Desktop runs `tau tui` in a PTY. It never uses the camera itself (the guard runs in the hub) and opens no network listener.

17. **Trusted and guarded are separate questions.** ADR 0006 §5 decides which channels may answer a tier-2 approval (**trusted**). The guard decides which channels need the owner verified at the Mac (**guarded**). A channel that opts out of the guard is identified some other way.

    | | Guarded: admission and step-up | Identified elsewhere: `guard=None` |
    |---|---|---|
    | **Trusted** (may approve tier 2) | TUI (local, over SSH or mosh, in tau Desktop, in a web tab), `tau chat` | Telegram (chat-id allowlist, polled directly) |
    | **Not trusted** (never approves) | `tau ask` (refusing approver), voice (later) | network turns (`net`: no tools, approvals refused) |

    Unknown and future channels, such as the MCP server, land in the guarded column, because `DISCOVER` fails closed. Telegram can lock the guard but never unlock it.

18. **Voice rules for later (118, 119).**
    - **The microphone** opens only while `GuardService.face_fresh(seconds)` holds and the screen is unlocked. The voice service asks the guard inside the hub before it opens the microphone, so a transcript sent through the TUI composer cannot skip the check.
    - **Voice routes** are protected control routes.
    - **Voice never vouches.** A speaker-verification mismatch can veto a command; a match never raises assurance.
    - **No approvals by voice.** Tier-2 is never approved by voice. An approval raised by a voice turn goes to the TUI when one is open, else to Telegram.
    - **Replies** follow `reply_mode = "text" | "speech" | "both"`.

19. **Remote sessions share the Mac's unlock.** A TUI or `tau chat` over SSH or mosh, and `tau ask`, work while the owner is verified at the Mac and are locked otherwise. Enrollment is refused over SSH. `tau guard setup` warns that remote use stops while the owner is away. 117 lifts that with per-client grants: the owner issues them from Telegram, they are keyed by `client_id`, and they have their own lifetime, so the Mac's HID idle and screen lock do not revoke a phone's grant.

20. **Cloud mode has no guard sensor.** A container has no camera and no Keychain. In cloud mode only identified channels run (Telegram and network turns), and they opt out of the guard. A guarded channel there resolves to `LockedGuard("unsupported_platform")`. `tau cloud push` (094) uploads config and persona files only, so nothing under `TAU_DATA_DIR/guard/` reaches Cloudflare.

21. **The RPi5 hub, later (122).** A remote verdict is accepted only as a signed attestation. The Mac acts as a camera node whose key is pinned at pairing. Each attestation is bound to a hub-issued nonce with a short expiry, and it travels over the authenticated tailnet mesh. The hub starts every check itself. No route or mesh message ever carries a bare verdict.

22. **macOS only in v1.** Camera selection, the presence signals, the Keychain and LocalAuthentication are macOS APIs, so `tau guard setup` refuses on other platforms. Every pyobjc and cv2 import is lazy, so the package imports and its offline tests run on Linux CI.

23. **Honest limits.** Without an infrared camera, a 2D webcam check is a presence and convenience factor. It keeps a housemate out of tau's own surfaces and stops low-effort photo and screen attacks. It does not stop a real-time deepfake, a determined attacker with a good video, or anyone with a shell. That is why it is only ever required in addition to the human approval, never in place of it, and why the guide names these limits next to the setup steps.

## Consequences

- **New components:**
  - the package `tau-guard` (`numpy`, `opencv-python-headless>=4.14,<5`, `cryptography`, and on macOS `keyring` plus the pyobjc AVFoundation, Quartz and LocalAuthentication frameworks), with the entry points `tau.hub_services: guard` and `tau.commands: guard`;
  - the app `apps/tau-desktop`.

  Both join CI and the release lists. The wheel ships the YuNet model with its MIT license; SFace is credited in the docs.
- **tau-core grows:**
  - `tau_core.guard`, `tau_core.hub.client.HubClient`, protected routes with a proof, the stop reason `locked` and the `/guard` slash command;
  - `FakeGuard` in `tau_core.testing`, which never approves anything.

  The guard's messages register themselves with `register_messages`, so `i18n.py` does not change. Existing installs are unchanged until the owner runs `tau guard setup`.
- **TauBar changes:**
  - its "Lock now" item signs its request with the control token (never sends it);
  - any other future client of a protected route (TauBar, the web UI, voice) reads `hub_dir/control.token` and re-reads it after a 403.
- **Remote use and `tau ask` while the owner is away** are locked until 117. `tau ask` exits with code 2 and the guard notice when it is locked (073).
- **One cv2 distribution.** `opencv-python-headless` is the only cv2 distribution in the workspace. A package that adds mediapipe or another OpenCV build overrides `opencv-contrib-python` at the workspace level (043).
- **Backups** exclude `TAU_DATA_DIR/guard/` (an acceptance criterion of 018).
- **The glossary** gains owner, guard (not the loop guard), guarded channel, identified channel, step-up, face template, presence recheck and cooldown. The docs site gains a guard guide (setup, limits, "locked out") and a reference page. These land in one docs pass after the parallel sessions commit.
- **The roadmap** gains layer L10 · Guard with issues 110–125.
- **Tests never open a camera, the Keychain or Touch ID.** They use `FakeGuard`, and fakes for the frame source, the face engine, the presence signals, LocalAuthentication and the key store. Real-model tests are opt-in, download public-domain portraits by pinned hash into a cache outside the repo, and never commit a face image. LFW is research-only and was used for calibration alone.
- **Cost.** Nothing recurring: one 38.7 MB model download and about 121 MB of installed OpenCV.

## Why not

- **An in-process fallback in v1.** It would bring a second camera owner and a second camera grant (the terminal, tau Desktop), native output written over the TUI, a guard without reflex locks, and state that flips whenever TauBar restarts the hub. Staying locked with a notice is simpler and safe. 124 adds a fallback that runs the same worker and state machine.
- **A `tau.guard` entry-point group.** A single-slot group needs selection rules for zero or several providers, and a test fixture installed in the owner's live workspace venv could win the slot. tau-core owning `HubGuard` and the route contract keeps cv2 out of channel processes and needs no group. The group can come back together with the in-process fallback.
- **Channel-name allowlists.** The names are labels that the code does not match (tau-net says `net`, web tabs and tau Desktop say `tui`), and making a tab say `web` would need a flag that anyone at the Mac can type. Opting out in code, with a repo rule, fails closed.
- **Voice as a factor.** Replay and cheap voice cloning defeat speaker verification, and clips of about 2 s or less, like most spoken commands, were unreliable in the probe. Voice can veto, never vouch.
- **InsightFace (ArcFace).** It is better at a low FAR (a 5-sample template at 0.45 gives FAR 1.4e-6 at FRR 0.7 %), but its models are for non-commercial research only, and the package pulls GUI OpenCV, scipy and scikit-image.
- **dlib and `face_recognition`.** dlib is source-only (a 75 s build on the M5, much longer on an RPi5), the wrapper's last release was in 2020, and the 68-point landmark model may not be used in a commercial product.
- **Apple Vision.** It has no identity embedding. Its feature prints of the same person (L2 up to 0.720) and of different people (from 0.606) overlapped, and it is macOS only.
- **MiniFASNet passive liveness.** It scored every sample as real (0.84–1.00), including a synthetic recapture at 1.000. It would add a model to convert, host and pin without stopping T5; the randomized challenge does that.
- **Continuous camera streaming.** Watching all the time would keep the camera LED and the menu-bar indicator on, process everyone in the room and cost power. The guard opens the camera only for an attempt, and between attempts it relies on HID idle, the screen lock and rechecks.

## Refinement (issue 112, 2026-09-30)

What building and verifying the face check added to the decisions above:

- **Worker and routes (decisions 2 and 3).** The worker also has the op `forget` (the CLI only), so LocalAuthentication and the Keychain stay in the worker. An enroll verdict carries `first` (decided from the Keychain item), a forget verdict `removed` (also when only the key could not go), and any verdict may carry `camera_ms`, from which the hub writes the `camera_open` audit record. `POST /guard/enroll` takes an optional `add: bool` (`tau guard enroll --add`). `PROGRESS_STEPS` gains `look_up`, `look_down` and `turn_more` for the enrollment poses.
- **Abandoned challenges (decision 9).** A lock or a cancel still ends a running attempt, but one whose record shows a head-turn prompt (`turn_left`, `turn_right`, `center`) ends as `spoof`, not `cancelled`: it counts, and a strict attempt locks with `step_up_failed`. Otherwise cancelling whenever the drawn direction does not suit a clip would be a free retry.
- **The challenge (decision 12), read strictly.** Challenge frames near the baseline (within 6° since issue 127; `|Δp| <= 0.10` before) are embedded too; each step needs at least 2 of them at or above the threshold and no more misses than matches, so the turns belong to the owner, not only the frontal frames around them (`step_identity`). From the frontal match on, a face gone for more than 0.2 s aborts (`spoof`, `face_lost`). Movement while no prompt is up aborts too (`moved_between_prompts`; the degree tolerances are in decision 12).
- **The camera's 20 s limit (decision 12).** It bounds the whole check whatever `verify_timeout_seconds` (5-60) says. A prompt is published only when its step, and for the last one the frontal match after it, can end before the camera stops; frames that stop anyway end the check with the verdict its phase would reach (`no_match` after a non-matching quality frame, `spoof` during a published step).
- **Camera choice (decision 12).** More than one device claiming to be the built-in camera, or another device with the chosen one's uniqueID, answers `camera_unavailable`; the doctor warns when `camera = "<id>"` names a device that is not a `bltn` built-in camera.
- **Keychain (decision 14).** The key always goes through keyring's macOS backend, built explicitly; `PYTHON_KEYRING_BACKEND` and `KEYCHAIN_PATH` never reach the worker, and a first enrollment reads the new key back before it writes anything. A template whose enrollment id is not the marker's is `template_invalid`.
- **Accepted limits, for the owner to revisit after the live test.**
  - Synthetic looping clips of natural head turns still pass 4-16 % of 2-step unlocks and 1-9 % of 3-step step-ups (measured again in degrees for issue 127; head shaking at most 3 %). With the cooldown schedule, an attacker gets about 10 counted attempts in an hour and 38 in 8 hours. Stronger options change this ADR: 3 steps for unlock, a wider hold range with a return window, up and down prompts, or a lockout after repeated `spoof` that only Touch ID or the password lifts (114).
  - A second face at 45 % or more of the owner's eye distance but under 40 px is ignored, so at sitting-back distances "exactly one face" is weaker.
  - Every challenge failure, a slow step included, is a counted `spoof`, so a slow owner fails a step-up and locks.

## Refinement (issue 114, 2026-09-30)

What building Touch ID added to decision 15:

- **The factor.** `LocalAuthFactor` stays in `tau_guard/localauth.py`, where 112 put it (the issue says `stepup.py`). Besides `authenticate(policy, reason, domain_state=...)` it has `biometry()`, which never prompts: `available`, `unavailable` (the Mac has Touch ID that cannot be used now: a closed lid, a disconnected Touch ID keyboard, a lockout after failed tries) or `none` (no sensor, or no enrolled finger), with the lid and the fingerprint set's `domainState` as a sha256. The prompt for Touch ID only has no "Use Password…" button. Every `LAContext` is invalidated after 30 s, after an answer and at once on a cancel; enrollment and forget now wait 30 s too (they waited 60 s).
- **The pin.** The template payload gains an optional `touch_id: {"domain_state": "<sha256>"}` (the payload version stays 1). An enrollment pins the fingerprints whenever Touch ID is available. A different set refuses Touch ID only with `touch_id_failed`, before the prompt and again after it. The device-owner policy has no pin: whoever could change the fingerprints knows the password. An enrollment without a pin (made without Touch ID, or before 114) makes Touch ID only refuse until `tau guard enroll --add` with Touch ID pins it.
- **A changed fingerprint set** refuses re-enrollment and `forget` as well, since both need Touch ID only on a Mac that has it. Removing every finger counts as a change: a pinned enrollment is only ever authorised by Touch ID with its pin, so a Mac that then reports no enrolled finger refuses with `touch_id_failed` and one whose pinned Touch ID keyboard is gone with `touch_id_unavailable`, never falling back to the password. The way back is to remove the Keychain key by hand (`security delete-generic-password -s tau-guard -a template-key-v1`): the next enrollment is then a first one, behind the device-owner policy. That needs a shell in the owner's account, which the threat model already leaves out; the doctor names it.
- **A pin that cannot be read** (the marker or the template is there but the template does not decrypt or parse, or one of the two is missing) counts as a pin Touch ID cannot compare: re-enrollment and `forget` refuse Touch ID only (`touch_id_failed`), except on a Mac that reports no Touch ID sensor at all, which keeps the device-owner policy, and the doctor's `touch id pin` line fails with the same way back. A Keychain that does not answer refuses both with `key_unavailable` before any prompt (a denied Keychain prompt must not skip the pin). Only when neither the marker nor the template exists (a key that a failed `forget` left behind) is nothing pinned, so `forget` can still remove the key. Pinning is trust on first use: a first enrollment made while Touch ID cannot be used pins nothing, and the next Touch ID authorisation pins the set it sees; the doctor warns about an enrollment without a pin.
- **Enrollment and forget.** A first enrollment uses the device-owner policy. Otherwise a Mac whose Touch ID is available uses Touch ID only with the pin, one whose Touch ID cannot be used now answers `touch_id_unavailable` (never the password instead), and a Mac without Touch ID uses the device-owner policy. A closed lid makes Touch ID only unavailable even with a Touch ID keyboard attached (decision 15 read literally), on a Mac that has Touch ID; a Mac that reports no sensor stays without Touch ID when its lid is closed, so it keeps the device-owner policy. `unlock_fallback = "touch_id_or_password"` is the opt-in for clamshell use.
- **The fallback offer.** `GuardStatus.fallback` (and the `/guard/status` field) is `unlock_fallback` while `locked`, after two failed face unlocks within the 10-minute failure window (any face-check verdict but a refusal or `cancelled`) or at once after a verdict of any face check in that window that says the face check cannot work (`FALLBACK_NOW`: a `camera_*` verdict, `unavailable` for a missing or changed SFace file, `model_changed` for an enrollment made with another model; Touch ID still works there, since the pin is read with the marker's model); a change of the offer moves `seq`. `Guard.unlock(method="touch_id")` asks for it; the verify body field is `fallback: "touch_id"`, not `method`, which the route rules keep out of every body. The hub refuses it with `touch_id_unavailable` while it is not offered. `unlock_fallback` joins the weakening-sensitive knobs a client sends: the stricter of the hub's and the client's value applies to the attempt (a client's `touch_id` never gets the password from a hub's `touch_id_or_password`, a client's `none` gets no Touch ID), a Touch ID only request never joins one that takes the password, and `HubGuard` narrows the status' offer the same way; the offer itself stays the hub's, since the unlocked state is shared by every client. The hub's second line also refuses a Touch ID success through the device-owner policy for a step-up or under `touch_id`. The face cooldown does not hold it back; a pass ends a running cooldown, clears the offer and unlocks with `method = "touch_id"`, and a Touch ID failure never counts toward it. Touch ID has its own limit instead: macOS only locks Touch ID out after wrong fingers, not after cancelled or timed-out prompts, and the sheet appears on the Mac's screen whichever client asked, so after five Touch ID unlock or recheck prompts that did not pass within the 10-minute window a new one is refused with `cooldown` and `retry_after` until the oldest leaves the window (a pass or a face unlock clears the count). A request that joins a running Touch ID prompt shows none and is not refused.
- **"Where available" is not probed.** The hub never asks LocalAuthentication whether the Mac has Touch ID before it offers the fallback, so with the default `unlock_fallback = "touch_id"` a Mac without Touch ID still shows the offer, and the attempt answers `touch_id_unavailable`. The doctor warns about a Touch ID setting on a Mac without Touch ID. Probing at service start would add a worker run to every hub start for a setting the owner can fix once.
- **The device-owner policy** (`touch_id_or_password`, the first enrollment, re-enrollment and `forget` on a Mac without Touch ID) is answered by Touch ID, the Mac password or a paired Apple Watch, as macOS decides. Its unlocks are recorded with `method = "touch_id"`; the audit's `touch_id` record (`policy: device_owner`) tells them apart.
- **Presence after Touch ID.** A Touch ID success sets a new `checked_at` but not `face_seen_at`: rechecks follow `checked_at`, `face_fresh` (voice) still needs a face. A recheck in a session unlocked with Touch ID is a Touch ID check, so a covered camera or a closed lid does not fail every later turn.
- **Step-up modes.** The hub runs the worker's `touch_id` op (no camera) for `touch_id`, and `verify` for `face` and `face_or_touch_id`; in the latter the worker releases the camera and asks Touch ID after `too_dark`, `no_face`, `timeout`, `face_too_small`, `permission_pending`, a `camera_*` verdict, `unavailable` or `model_changed` (the last two before the camera opens), never after a counted failure. `none` means no fresh check: no worker runs, and the attempt ends at once with `ok` and `method: null`; it takes effect only as the merged value (both the hub's and the client's `tau.toml`, or the hub's alone for an in-hub caller). A client sends every weakening-sensitive knob with the value it uses, so a `tau.toml` that leaves `step_up` out sends `face`, and the hub reads a knob missing from a client's request as that strict default, never as agreement. The worker gets the attempt timeout plus 30 s when a Touch ID prompt may follow the face. A step-up or a recheck whose Touch ID prompt refused the finger (`failed`, which macOS answers after several wrong fingers or a lockout) or found another fingerprint set (`changed`) locks with `step_up_failed`, like a face `no_match`, without counting toward the cooldown; a cancelled, timed-out or unusable prompt does not lock.
- **Audit and the wire.** A verdict after a prompt carries `local_auth: {policy, outcome, ms}` (a Touch ID success without a passed record is a broken verdict); the hub writes a `touch_id` record per prompt, and the audit schema gains `method` and `policy`.
- **The channels' offer.** While `GuardStatus.fallback` is set, the TUI lock screen shows the `guard.fallback.*` text with its key hint and names the key in its hint line; `t` in the empty field runs `unlock(method="touch_id")` (a printable key, so it survives mosh and Termius; it acts only in the empty field while the offer shows, the way `?` acts only in an empty composer, and `t` + Enter works too). The terminal lock prompt prints the offer when it appears and again after each failed attempt, and `t` + Enter runs it. Both say "Confirm in the macOS prompt on the Mac's screen" until the hub's `touch_id` step arrives; Esc and Ctrl-C cancel it like a face check; a pass unlocks like a face unlock, and the Unlocked notice names the method. Without an offer `t` is typed (TUI) or not sent (terminal). Telegram never offers it, since it never unlocks.
