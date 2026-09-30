# 127 · Tune the head-turn challenge on real captures

Status: ready-for-agent
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

- [ ] The failing rule of the 2026-09-30 try is identified from `--explain` output and fixed
- [ ] The verdict and audit say which liveness rule failed (a reason code, no raw values)
- [ ] Synthetic tests for a flat photo, a looping head-shake clip and wrong-direction motion still fail the challenge; number-only fixtures from real passes pass
- [ ] (user) Five natural unlocks in a row pass at the owner's normal seat, with and without glasses

## Blocked by

- [112 · Face verification](112-face-verification.md)

## Comments

- 2026-09-30: filed from the owner's first live try (`verify` ended with `spoof` after the return from a right turn).
