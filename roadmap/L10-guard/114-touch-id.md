# 114 · Touch ID: authorises enrollment and forget, unlock fallback, optional step-up

Status: ready-for-agent
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

- [ ] `LocalAuthFactor` has a macOS implementation and a fake; `pyobjc-framework-LocalAuthentication` is imported lazily; tests on Linux pass without it
- [ ] Re-enrollment and `forget` require the biometrics-only policy when Touch ID exists (fake factor), and the device-owner policy otherwise
- [ ] A changed `domainState` refuses with `touch_id_failed`; a context is invalidated after 30 s and on cancel; clamshell or no sensor gives `touch_id_unavailable`
- [ ] After two face failures or a `camera_*` verdict, the lock screen and the terminal prompt offer the fallback (scripted `FakeGuard`); a passing fallback unlocks with `method = "touch_id"`, which is recorded in the audit
- [ ] `step_up = "face_or_touch_id"` falls back to Touch ID only after a non-counted face failure; `step_up = "touch_id"` never opens the camera; `none` applies only when the client and hub policies both say `none`
- [ ] No Touch ID path turns a `REJECTED` or unanswered approval into `APPROVED` (gate test with the fake factor)
- [ ] The LocalAuthentication reason string and all new chrome are i18n keys in `en` and `tr`
- [ ] (user) On the owner's Mac, Touch ID authorises a re-enrollment and a `forget`, unlocks `tau tui` as the fallback with the camera covered, and passes a tier-2 step-up with `step_up = "face_or_touch_id"`; the result goes under Comments

## Blocked by

- [112 · Face verification](112-face-verification.md)

## Comments

- 2026-09-30: filed with ADR 0008.
