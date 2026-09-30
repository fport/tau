# 112 · Face verification: built-in camera, YuNet + SFace, head-turn challenge, enrollment, encrypted template, `tau guard` CLI

Status: ready-for-agent
Type: AFK
Layer: L10 · Guard
Packages: tau-guard
Blocked by: 111

## What to build

The worker's real `verify` and `enroll` operations, and the `tau guard` command group. After this slice the owner can:

1. run `tau guard setup`;
2. enroll their face in about 20 seconds;
3. unlock `tau tui` or `tau chat` with a face check and a head-turn challenge;
4. pass a tier-2 step-up, with everything local.

The decisions are in [ADR 0008](../../docs/adr/0008-owner-guard.md) (decisions 12–14); the service, routes, cooldown and audit are 111. Every frame lives only in the worker's memory.

### Camera (`camera.py`)

- **Device.** Only the built-in camera is used by default. pyobjc picks the device of type `AVCaptureDeviceTypeBuiltInWideAngleCamera` with transport `bltn`.
- **Index.** The cv2 index is that device's position in the uniqueID-sorted `video + muxed` list, which is the order OpenCV's AVFoundation backend uses. The list is enumerated again right after `isOpened()`; if it changed, the attempt aborts with `camera_unavailable`. That keeps Continuity Camera and virtual cameras (OBS) out, which is the only defence against injected frames. A test pins the enumeration to the OpenCV version in use.
- **Environment.** The worker sets `OPENCV_AVFOUNDATION_SKIP_AUTH=1` and `OPENCV_LOG_LEVEL=ERROR`.
- **Permission.** The worker checks `authorizationStatusForMediaType_` itself:
  - `0`: request access and answer `permission_pending`;
  - `2`: answer `camera_denied`.
- **Frames.** It drops 5 warm-up frames, keeps the camera open for at most 20 s and calls `release()` in `finally`.
- **Configuration.** `[component.guard] camera = "builtin" | "<camera id>"`.
- **Seam.** A `FrameSource` protocol with a synthetic fake for tests; 043 may reuse the source later.

### Engine (`engine.py`)

- **Detector.** YuNet 2023mar fp32, vendored in the wheel: `tau_guard/models/face_detection_yunet_2023mar.onnx`, sha256 `8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4`, with `tau_guard/models/LICENSE-yunet` (MIT) in the wheel.
- **Recognizer.** SFace 2021dec fp32. `tau guard setup` downloads it from `https://media.githubusercontent.com/media/opencv/opencv_zoo/47534e27c9851bb1128ccc0102f1145e27f23f98/models/face_recognition_sface/face_recognition_sface_2021dec.onnx` (sha256 `0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79`, Apache-2.0, credited in the docs) into `TAU_DATA_DIR/guard/models/`.
  - `--model-file PATH` installs it offline.
  - A checksum failure is a clear error, and the file is not kept.
- **Embeddings** are L2-normalised and compared with the template by cosine similarity.
- **Seam.** A `FaceEngine` protocol (detection rows and embeddings) with a fake for tests.

### Quality gates and match (`verify.py`)

- **Gates.** A frame counts when the YuNet score is at least 0.90 (0.75 on challenge frames), the eye distance at least 40 px (else hint `face_too_small`), the mean brightness at least 60 (else `too_dark`) and the Laplacian variance at least 30.
- **Second faces.** A second face counts only when its eye distance is at least 45 % of the primary face's and at least 40 px. A counted second face aborts with `multiple_faces`.
- **Match.** At least 3 of the last 5 quality frames reach the threshold.
  - `unlock_threshold` is 0.50, with a floor of 0.45; a lower value is refused.
  - `step_up_threshold` is 0.55.
  - `verify_timeout_seconds` is 15.
- **Why these numbers.** They come from an LFW calibration with a 5-sample template: FAR 3.3e-5 and FRR 0.5 % at 0.50, and FAR 2.8e-6 and FRR 1.1 % at 0.55.

### Head-turn challenge (`liveness.py`)

- **The signal.** The yaw proxy is `p = (nose_x − eye_mid_x) / eye distance`. The baseline is the median `p` over the attempt's frontal frames. Enrollment calibrates the sign and the owner's amplitude from the left and right poses.
- **A step passes** when Δp reaches at least max(0.20, 0.6 × the calibrated amplitude) in the asked direction, holds for a random 0.4–0.8 s, then returns within 0.10 of the baseline.
- **Abort.** An overshoot of more than 0.15 in the opposite direction aborts with `spoof`.
- **Timing.**
  - A random pause of 0.3–0.9 s comes before each prompt.
  - Each step gets 3.5 s, measured from when its prompt is published, and the progress event carries that deadline.
  - Unlock asks for 2 steps, step-up for 3.
- **Identity** is checked on frontal frames before and after the steps. Box IoU from frame to frame stays above 0.3, and exactly one face stays in view throughout.
- **`unlock_liveness`** is `"challenge"` (default) or `"none"`; `none` warns in the doctor.
- **Fresh challenge.** Within `step_up_challenge_fresh_seconds` (default 120) of a check that passed the challenge, a step-up is a strict passive match.
- **Recheck.** The recheck (`kind="recheck"`) is always a passive strict match: 3 of 5 frames, no challenge, about 1–1.5 s.

### Enrollment (`enroll.py`)

- **Capture.** Guided, 15–20 s, with live text hints through i18n keys: too dark, too far, turn more, one face only. Five poses, 10–20 samples.
- **Sample checks.** A sample is skipped when its cosine similarity to one already kept is above 0.97. Leave-one-out requires at least 0.55.
- **Template.** The template is the renormalised mean of the samples, stored with the yaw calibration.
- **LocalAuthentication.** On macOS enrollment always runs behind LocalAuthentication. This slice ships the `LocalAuthFactor` protocol and the device-owner policy (Touch ID or the Mac password) for both enroll and forget. 114 adds the biometrics-only policy with `domainState` pinning for re-enrollment and forget.
- **First enrollment or re-enrollment** is decided from the Keychain item, not from the template file, so deleting the file never turns the next enrollment into a first one.
- **Where it runs.** When a hub runs, enrollment goes through it (`POST /guard/enroll`: the same worker, the prompt on the Mac screen, one camera permission). Otherwise it runs in a local worker from the CLI. It is refused when `SSH_CONNECTION` is set.

### Storage (`store.py`)

- **Directory.** `TAU_DATA_DIR/guard/`, mode 0700, set with chmod explicitly.
- **Template file.** `owner.face.v1.bin`, mode 0600, written atomically: `b"TAUG1" | nonce(12) | AESGCM(key).encrypt(nonce, payload, aad=b"tau-guard/v1|" + model_sha)`. The payload is JSON: `{v, enrollment, created, model: {name, sha256}, dim, template, samples, calibration}`.
- **Key.** The key lives in the macOS Keychain through `keyring` (service `tau-guard`, account `template-key-v1`). It is read only inside the worker, with a timeout; a timeout or failure gives `key_unavailable`. A `KeyStore` protocol has an in-memory fake, so no test touches the real Keychain.
- **Marker.** The public marker `enrolled` holds `{"v": 1, "enrollment", "model", "created"}`. tau-core's `resolve_guard` reads it.
- **Freshness.** The template is read again for every verification, so `forget` takes effect at once.
- **Model changes.** A model change gives `model_changed`, and a re-enrollment behind LocalAuthentication fixes it. A template that does not decrypt gives `template_invalid`.

### CLI (`tau guard`, interactive output through i18n keys; click help stays English)

- **`setup`:**
  1. check the platform (it refuses on anything but macOS);
  2. download the model;
  3. enroll;
  4. run one verify;
  5. write `[component.guard] enabled = true` through `tau_core.settings.load_document/save_document`;
  6. tell the owner to restart the hub.

  It also warns that remote TUI, chat and `tau ask` are locked while the owner is away, until 117.
- **`enroll [--add]`.** `--add` adds samples under other light.
- **`verify [--explain]`.** `--explain` shows, per frame, the score, eye distance, brightness, sharpness and yaw proxy. No frame is saved.
- **`status`, `lock`, `log`.**
- **`forget`.** Behind LocalAuthentication, it removes the template, the samples, the marker and the Keychain key.
- **`doctor`** reports the platform, the model sha, whether the template decrypts, a Keychain read, the modes, the camera device, the camera permission of the responsible process (naming TauBar or the terminal), Touch ID availability and clamshell (from 114 on), and the failures of the last 24 h.

### Tests

- **Offline, in CI.**
  - The verify and liveness state machines over synthetic YuNet rows and embeddings.
  - The YuNet file loads and its sha256 matches.
  - A blank frame gives `no_face`.
  - A two-face synthetic composite at several scales gives `multiple_faces` only when the second face is large enough.
- **Opt-in (`-m models`, not in CI).**
  - Download SFace and a few public-domain portraits by pinned URL and sha256 into a cache outside the repo.
  - Genuine and impostor cosines fall on the right sides of the threshold.
  - A horizontally scaled or perspective-warped still fails the challenge.
- **Never** commit a face image, and never use LFW.

## Acceptance criteria

- [ ] The camera selection picks only a `bltn` built-in wide-angle device; a changed device list after the open aborts with `camera_unavailable` (fake enumerations); permission status 0 gives `permission_pending` and 2 gives `camera_denied`; the camera is released in `finally` on every path, including a kill
- [ ] The vendored YuNet file's sha256 is checked at load; `tau guard setup` downloads SFace and refuses a file with a wrong checksum; `--model-file` works offline
- [ ] Quality gates and the second-face rule behave as specified on synthetic detections, with hints `too_dark` and `face_too_small` reaching `/guard/status` as progress hints
- [ ] Match needs 3 of the last 5 quality frames at or above the threshold; `unlock_threshold` below 0.45 is refused
- [ ] The head-turn challenge passes a synthetic owner sequence and fails on: the wrong direction, an overshoot beyond 0.15 the other way (`spoof`), no hold, no return to baseline, a step past its deadline, a second face, and an IoU break; unlock uses 2 steps and step-up 3; within `step_up_challenge_fresh_seconds` a step-up runs passively
- [ ] Enrollment rejects inconsistent samples (leave-one-out below 0.55), stores the calibration, runs only after LocalAuthentication passes (fake factor), and is refused with `SSH_CONNECTION` set
- [ ] The template file starts with `TAUG1`, decrypts only with the key and the matching model sha (AAD), is 0600 in a 0700 directory, and a copy of `guard/` without the key cannot be decrypted (test); nothing in `guard/` or the logs contains an embedding or a frame
- [ ] `forget` removes the template, the marker and the key, and the next verify in a running hub answers `not_enrolled` without a restart; deleting only the template file does not make the next enrollment a first enrollment
- [ ] `tau guard verify --explain` prints the per-frame numbers and saves nothing; `tau guard doctor` covers every item listed above
- [ ] The offline tests run in CI on Linux; the opt-in `-m models` tests pass on a Mac and download nothing into the repo
- [ ] (user) Live on the owner's Mac: `tau guard setup` enrolls, `tau tui` unlocks with the head-turn challenge, and a tier-2 call passes the step-up; the numbers go under Comments
- [ ] (user) A printed photo and a phone playing a looping clip of the owner are held up to the camera and both fail; the result goes under Comments

## Blocked by

- [111 · `tau-guard` service](111-tau-guard-service.md)

## Comments

- 2026-09-30: filed with ADR 0008.
