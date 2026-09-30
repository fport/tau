# 127 · Tune the head-turn challenge on real captures

Status: done
Type: AFK
Layer: L10 · Guard
Packages: tau-guard
Blocked by: 112

## What to build

The owner's first live try on 2026-09-30 enrolled fine (score 0.77) but the verification right after it failed with `spoof`: the prompts were "look at the camera", "turn your head right", "look straight at the camera again", then the check ended. The challenge thresholds were set from still images and synthetic landmark sequences ([ADR 0008](../../docs/adr/0008-owner-guard.md) decision 12), and at least one rule is too strict for a real head. Likely candidates:

- the overshoot rule: coming back from a right turn, a real head swings past the baseline; an overshoot of more than 0.15 the other way aborts as `spoof`;
- the rule added in 112's fixes that fails a head moving while no prompt is up (natural small movements during the random pause);
- the return-within-0.10-of-baseline window and the hold time.

Tune them on real data without weakening what they stop:

- Run `tau guard verify --explain` with the owner (it prints the per-frame yaw proxy, eye distance, brightness and sharpness and saves no frames) for a few natural passes, including glasses and a slightly off-centre seat.
- Make the overshoot and idle-movement rules relative to the owner's calibrated amplitude and to the direction of the previous step (a return swing is expected; a swing *before* the prompt or a repeated oscillation is what a looping clip does), and keep a hard abort for motion that reverses direction repeatedly within one step.
- Say which rule failed in the verdict for `--explain` and in the audit (`liveness` field: `overshoot`, `moved_between_prompts`, `no_return`, `too_slow`, …) without logging raw values.
- Keep the synthetic regression tests for a flat photo, a looping clip and wrong-direction motion, and add sequences recorded (as numbers only, never frames) from the owner's passes as fixtures.

## Acceptance criteria

- [x] The failing rule of the 2026-09-30 try is identified from `--explain` output and fixed
- [x] The verdict and audit say which liveness rule failed (a reason code, no raw values)
- [x] Synthetic tests for a flat photo, a looping head-shake clip and wrong-direction motion still fail the challenge; number-only fixtures from real passes pass
- [ ] (user) Five natural unlocks in a row pass at the owner's normal seat, with and without glasses

## Blocked by

- [112 · Face verification](112-face-verification.md)

## Comments

- 2026-09-30: filed from the owner's first live try (`verify` ended with `spoof` after the return from a right turn).
- 2026-09-30: built on `guard/tune` (commits 10872f7, ee0b01e, db677e6, 875a2fd, 3d5e840, 25196ba). tau-guard has 610 tests (8 opt-in skipped); the whole suite passes (2344 passed, 9 skipped); ruff check, ruff format --check and `mkdocs build --strict` are clean. The opt-in `-m models` tests pass on the Mac from the existing cache (9 passed, nothing downloaded into the repo).
  - **What failed.** The owner's `--explain` paste shows the yaw proxy `(nose_x - eye_mid_x) / eye distance` moving by about 0.07 on the prompted turn, against a reach of Δp ≥ 0.20 (about 20 degrees of real yaw, and the proxy also mixes a head tilt into the yaw): the reach rule could not be met. The earlier try's `spoof` right after the return from a right turn fits the overshoot rule (a return swing past the centre by more than 0.15); without a reason code at the time this is the likely rule, not a certainty. The per-frame lines also buried the prompts.
  - **Head pose.** `cv2.solvePnP` (ITERATIVE from a frontal guess; focal length = frame width, principal point in the middle) fits YuNet's five landmarks to a generic head: x/y from YuNet's own median landmark layout on frontal portraits (eye distance 64 mm), depths from MediaPipe's metric canonical face (eyes 38 mm, mouth corners 32 mm behind the nose tip). Synthetic projections at ±10/20/30 degrees come back within 1 degree (median error under 3 degrees with a pixel of noise). On 18 real faces it agrees with MediaPipe's head pose (slope 1.02, r 0.83); real faces fit within 0.02-0.08 eye distances.
  - **New rules (degrees, relative to the attempt's frontal baseline).** Reach max(12, 0.5 x calibrated amplitude), hold 0.3-0.6 s with 3 degrees of slack, return within 6 degrees or past the centre (no longer an abort), 4.0 s per step from the prompt, 2 steps for unlock and 3 for step-up. Aborts: 8 degrees the wrong way before the hold is done (`overshoot_before_target`), more than 3 reversals of 6 degrees in a step (`oscillation`), more than 10 degrees between prompts, 20 on the far side of a return swing (`moved_between_prompts`); deadlines give `no_turn`, `too_slow`, `no_return`; verify adds `face_lost` and `step_identity`, the hub `abandoned`. Frames go through a 3-frame running median, and frames whose landmarks fit the head worse than 0.10 eye distances (or 1.5 x the frontal fit) count for nothing.
  - **Flat photo versus head.** A head turned by φ reads φ. A flat photo turned by 10/20/30/40/50 degrees reads 0.7/1.4/2.4/3.8/7.8 degrees square to the camera and at most 2.3/5.1/6.9/8.5/9.0 (10.1 at 45) over eye distances 45-120 px, three seats, two heights and a ±15 degree tilt; from 55 degrees on no frame fits a head. Real YuNet on a real portrait turned ±40 degrees (squeeze and perspective warps): the frames that fit span 7.5 and 8.8 degrees, and the check ends as `no_turn`.
  - **Synthetic probe, 200 runs each** (not in the repo). A noisy owner (turns 14-30 degrees, a seat ±15 degrees off, 0.3-1.2 px landmark noise, 0-10 degree return swing, sway, 0.3-1.05 s latency) passes 100 % of unlocks and step-ups. By turn size: 12 degrees 73 %, 13 degrees 90 %, 14-15 degrees 97.5 %, 17 and more 100 %. Looping clips of natural turns pass 4-16.5 % of 2-step unlocks and 1-9 % of 3-step step-ups (about as before: 4-16 % and 1-7 %); head shaking 0-3 %; a flat photo 0 %.
  - **The owner fixture.** The recorded dip (proxy +0.14 to +0.07, eyes 44-58 px, frontal proxy +0.13, which is 12 degrees with this head) is what two heads give: a real 14 degree turn with the head tilting 8 degrees into it (the pose reads 14 and the challenge passes) or a pure 6.5 degree turn (the pose reads 6.5: `no_turn`). Both are tests. If the owner's turn was the small one, the new prompt line should fix it; if live tries show that the owner's natural turn stays below 12 degrees, lower `TURN_FLOOR` (the flat photo stays under 10).
  - **Migration.** A template with the old proxy calibration keeps loading: its sign stays and it uses 24 degrees to each side (a 12 degree target); the doctor says so, and `tau guard enroll` measures the owner's range in degrees. No re-enrollment is forced.
  - **Diagnostics.** The verdict's `liveness` carries the rule code on a `spoof`, the hub accepts only the known codes, the audit keeps it and `tau guard log` shows it. `verify --explain` prints each prompt as a highlighted line (`>>> TURN YOUR HEAD LEFT <<<`), tags every frame line with the prompt on screen, prints every 3rd frame (`--explain=all`: every frame) with yaw, turn and pitch in degrees and the fit error, and names the failed rule; new chrome is in tau_guard's message table (en, tr).
  - **For the owner (the open criterion).** Run `tau guard verify --explain` at the normal seat, with and without glasses, and turn clearly (15-20 degrees) when the `>>>` line appears. Watch `turn=` (it must pass ±12) and `fit=` (it must stay under 0.10; a higher value on turned frames means the generic head fits this face poorly and the fit gate needs a look). If a check still fails, the last line names the rule.
