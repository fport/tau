# 114 · Touch ID: authorises enrollment and forget, unlock fallback, optional step-up

Status: in-progress
Type: AFK
Layer: L10 · Guard
Packages: tau-guard, tau-tui, tau-core
Blocked by: 112

## What to build

Touch ID becomes the guard's second factor at the Mac. It is used in three places:

- it authorises enrollment, re-enrollment and `forget` with the biometrics-only policy;
- it is an unlock fallback when the face check cannot work (dark room, glare, a camera the hub may not use, a new beard);
- it can serve as the tier-2 step-up.

It runs in the worker subprocess like the camera, and like the face check it can only narrow: it never produces an approval. The decisions are in [ADR 0008](../../docs/adr/0008-owner-guard.md) (decision 15).

### `LocalAuthFactor` (`stepup.py`)

- **macOS implementation.** `LAContext` inside the worker, through `pyobjc-framework-LocalAuthentication` imported lazily.
- **Biometrics-only policy.** Policy 1 uses reuse duration 0 and pins `domainState` at enrollment, stored in the encrypted template payload. A changed fingerprint set refuses with `touch_id_failed`.
- **Time limit.** Every context is invalidated after 30 s (`LAContext.invalidate()`); a cancelled attempt invalidates it at once.
- **Unavailable.** A closed lid (clamshell), a Mac without a sensor or a policy that cannot be evaluated gives `touch_id_unavailable`.
- **Reason string.** The `localizedReason` shown by macOS is UI chrome: it goes through an i18n key in `en` and `tr`.
- **Fake.** A fake factor exists for tests; no test ever opens a real Touch ID prompt.

### Uses

- **Enroll and forget.**
  - The first enrollment uses the device-owner policy (Touch ID or the Mac password), from 112.
  - Re-enrollment and `forget` use policy 1 (biometrics only) when Touch ID exists, else policy 2.
  - First enrollment or re-enrollment is decided from the Keychain item, never from the template file.
- **Unlock fallback.** `[component.guard] unlock_fallback = "touch_id" | "touch_id_or_password" | "none"`; the default is `touch_id` where available.
  - The lock screen and the terminal lock prompt offer it after two face failures in one attempt window, or after any `camera_*` verdict.
  - The unlock is recorded with `method = "touch_id"` in the status and the audit.
  - `touch_id_or_password` is the opt-in for clamshell use.
- **Step-up.** `[component.guard] step_up = "face" | "face_or_touch_id" | "touch_id" | "none"`; the default is `face`.
  - `face_or_touch_id` offers Touch ID when the face step-up fails for a non-counted reason, such as `too_dark` or a `camera_*` verdict.
  - `touch_id` is the accessible alternative for an owner who cannot turn their head.
  - `none` takes effect only when both the client and the hub policy say `none`: the stricter of the two applies.
  - The doctor warns about `none`.
- **Routes.** `POST /guard/verify` carries the method the client may offer. The hub decides and runs LocalAuthentication itself, so the sheet appears on the Mac screen. No route accepts a Touch ID result.

### Channels

- **Offer.** The TUI lock screen and the terminal lock prompt show the fallback option when the status says it is available.
- **Progress.** `PROGRESS_STEPS` already has `touch_id`: the channels render "confirm with Touch ID" when it arrives.
- **Doctor.** `tau guard doctor` reports Touch ID availability, clamshell and whether `domainState` changed.

## Acceptance criteria

- [x] `LocalAuthFactor` has a macOS implementation and a fake; `pyobjc-framework-LocalAuthentication` is imported lazily; tests on Linux pass without it
- [x] Re-enrollment and `forget` require the biometrics-only policy when Touch ID exists (fake factor), and the device-owner policy otherwise
- [x] A changed `domainState` refuses with `touch_id_failed`; a context is invalidated after 30 s and on cancel; clamshell or no sensor gives `touch_id_unavailable`
- [ ] After two face failures or a `camera_*` verdict, the lock screen and the terminal prompt offer the fallback (scripted `FakeGuard`); a passing fallback unlocks with `method = "touch_id"`, which is recorded in the audit
- [x] `step_up = "face_or_touch_id"` falls back to Touch ID only after a non-counted face failure; `step_up = "touch_id"` never opens the camera; `none` applies only when the client and hub policies both say `none`
- [x] No Touch ID path turns a `REJECTED` or unanswered approval into `APPROVED` (gate test with the fake factor)
- [x] The LocalAuthentication reason string and all new chrome are i18n keys in `en` and `tr`
- [ ] (user) On the owner's Mac, Touch ID authorises a re-enrollment and a `forget`, unlocks `tau tui` as the fallback with the camera covered, and passes a tier-2 step-up with `step_up = "face_or_touch_id"`; the result goes under Comments

## Blocked by

- [112 · Face verification](112-face-verification.md)

## Comments

- 2026-09-30: filed with ADR 0008.
- 2026-09-30: built on `guard/service` (112's branch, without 113), everything but the channels'
  offer. Commits: ad0125a (tau-core seam), 0dd7935 (worker: factor, pin, `touch_id` op),
  9b798fb (hub: offer, Touch ID unlock and recheck, step-up modes, audit), 6e59408 (doctor,
  status, CLI hints), 9981648 (README, ADR 0008 "Refinement (issue 114)"), 636426c (an intact
  enrollment for any Touch ID unlock). Full suite: 1841 passed, 8 skipped, and the known
  `test_no_personal_paths_in_tracked_files` failure (issue 130); tau-guard also passes with
  pyobjc and keyring blocked. `git merge-tree` with `feat/guard` (which now holds 113) is clean,
  and the merged tree's suite passed there (two tau-net universe tests failed once and pass on
  a rerun; they are timing-flaky on `feat/guard`, not guard code).
  - **What exists.** `MacLocalAuth` (`localauth.py`): `biometry()` never prompts
    (`available`, `unavailable` with why: lid, keyboard, lockout; `none`), Touch ID only
    without the password button and with reuse duration 0, `domainState` as a sha256 pinned in
    the encrypted payload (`touch_id.domain_state`) and compared before and after the prompt,
    every `LAContext` invalidated after 30 s, after an answer and on SIGTERM, a closed lid read
    from `ioreg`. Tested against a fake `LocalAuthentication` module. Enrollment: first →
    device owner; else Touch ID only with the pin where Touch ID is available,
    `touch_id_unavailable` while it cannot be used, device owner without Touch ID; forget the
    same. The hub: `GuardStatus.fallback` after two failed face unlocks in the 10-minute window
    or a `camera_*` verdict; `unlock(method="touch_id")` / verify body `fallback: "touch_id"`
    runs the worker's `touch_id` op; a pass unlocks with `method = "touch_id"` (status, audit
    `verify`/`unlock` with `method`, a `touch_id` record per prompt with `policy`). Step-up:
    `face`, `face_or_touch_id` (Touch ID after `too_dark`, `no_face`, `timeout`,
    `face_too_small`, `permission_pending` or `camera_*`), `touch_id` (no camera), `none`
    (no check, merged value only). Doctor: Touch ID, the lid, the pin (`changed` fails with the
    way back), `step_up = none`, a Touch ID setting on a Mac without Touch ID.
  - **Deviations and choices** (all in ADR 0008's new refinement):
    - `LocalAuthFactor` stays in `localauth.py` (112 created it), not `stepup.py`.
    - The verify body field is `fallback: "touch_id"`, not `method`: the route rules (a 112
      test) keep `method` out of every body; the Python API is `unlock(method=...)`.
    - `step_up = "none"` now means no fresh check (no worker; `ok` with `method: null`), as the
      review's sec-15 meant it; 112 had run a passive face match for it.
    - A changed fingerprint set refuses re-enrollment and forget too (both need Touch ID only
      on a Mac that has it). The way back is removing the Keychain key by hand, which the doctor
      names; a shell is outside the threat model anyway. An enrollment without a pin (no Touch
      ID then, or before 114) refuses Touch ID only until `tau guard enroll --add` pins it.
    - A closed lid makes Touch ID only unavailable even with a Touch ID keyboard (decision 15
      read literally); `touch_id_or_password` is the clamshell opt-in.
    - A Touch ID unlock is presence but not a face: new `checked_at` drives rechecks,
      `face_seen_at` (and `face_fresh` for voice) stays face-only, and a Touch ID session
      rechecks with Touch ID, so the covered-camera case keeps working after 3 idle minutes.
    - The face cooldown does not hold the Touch ID fallback back, and a Touch ID pass ends it
      (the "lockout that only Touch ID lifts" of 112's notes, in its mildest form).
    - Enrollment and forget prompts now end after 30 s (they had 60 s): every context is
      invalidated after 30 s.
    - The hub does not probe Touch ID: with the default `unlock_fallback = "touch_id"` on a Mac
      without Touch ID the offer still appears and the attempt answers `touch_id_unavailable`;
      the doctor warns about that setting.
  - **Left (why the issue is not done).** The fourth criterion's channel half: the TUI lock
    screen and the terminal lock prompt of 113 are not on this branch, so they do not offer the
    fallback yet. On a branch with both (`feat/guard` after this merge) the wiring is small:
    when `status.fallback` is set, show `t("guard.fallback.<mode>", how=<the channel's key
    hint>)` (`guard.fallback.confirm` for the prompt text), let a key or `t` + Enter call
    `guard.unlock(method="touch_id", on_progress=...)`, and test it with
    `FakeGuard(..., fallback="touch_id")` (it offers after two face failures or a `camera_*`
    verdict, and records `unlock_methods`). 113's `method_text` already translates
    `touch_id`.
  - **For the owner (the user criterion).** Enable Touch ID for the live test with
    `unlock_fallback = "touch_id"` (default) and `step_up = "face_or_touch_id"`; enroll again
    first (`tau guard enroll --add` with the lid open) so the fingerprints are pinned, then run
    `tau guard doctor` (the `touch id pin` line should say `ok`). Check that the macOS sheet
    appears from TauBar's hub (LocalAuthentication from a background process was not tried on
    a real Mac here).
