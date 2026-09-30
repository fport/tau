# 123 · Owner notifications from the guard: failed attempts, cooldown, guard disabled

Status: ready-for-agent
Type: AFK
Layer: L10 · Guard
Packages: tau-core, tau-guard
Blocked by: 111

## What to build

The owner hears about attempts to get past the guard, even when they are away from the Mac. The guard records failures and cooldowns in its audit log (111), but nobody reads the log in the moment. This issue sends short notices to the owner's Telegram chats through a small, public owner-notice seam in tau-core, so tau-guard never reaches into Telegram's internals. 101 (network notifications) needs the same seam.

### Seam (tau-core)

- **The protocol.** `tau_core.hub` gains `OwnerNotifier`: `name`, plus `async notify(key: str, params: dict, *, urgent: bool = False) -> bool`.
  - `key` is an i18n message key, and each notifier renders it in the UI language.
  - The return value says whether any channel delivered it.
- **Finding notifiers.** In-hub services find notifiers by scanning started services for `isinstance(OwnerNotifier)`, looked up lazily. No new entry-point group.
- **Telegram.** `TelegramService` implements it and sends to every allowlisted chat. It is rate-limited to one notice per key per 5 minutes, except urgent ones.
- **Doctor.** `tau doctor` warns when the guard is active and no notifier is running.

### What the guard sends

- **Repeated failures:** a notice after the fifth counted failure (`no_match`, `spoof`, `multiple_faces`) within 10 minutes, and whenever a cooldown starts. For example, "Someone tried to unlock tau at the Mac 5 times; tau is in cooldown for 2 min". The notice holds counts and times only, never a score or an image.
- **A failed step-up that locked the guard:** the tool name and the time.
- **Guard off, or not running:** a notice when the guard should be active and is not.
  - `GuardService` records `last_active_at` in `TAU_DATA_DIR/guard/state.json`.
  - At hub start, tau-core checks for the enrollment marker. If the marker exists but no `guard` service started, the hub itself sends "the guard is not running" once it is up: tau-guard missing, the service skipped, or `[components.hub] services` without `guard`. So does a guard that resolves to `LockedGuard`.
  - `tau guard forget` sends a notice that the guard was turned off, with the time.
- **Camera permission lost:** when `camera` changes to `denied`, with the fix (grant the camera to TauBar).
- **Telegram's own `/guard lock`:** only a confirmation in the same chat.

### Rules

- Notices are chrome: i18n keys in `en` and `tr`, rendered in the UI language, never model output.
- No notice ever contains a chat id, a score, an embedding, a frame or a description of a person.
- Notices never change guard state and never unlock. Buttons are limited to "Lock now" (trigger `telegram`).
- Owner notification preferences move to settings when 019 lands; until then they live in `[component.guard] notify = true | false`, default `true`.

## Acceptance criteria

- [ ] `OwnerNotifier` is exported from `tau_core.hub`; `TelegramService` implements it and sends to the allowlisted chats with a per-key rate limit (fake Telegram)
- [ ] The fifth counted failure within 10 minutes and every cooldown start send one notice each; the text holds counts and times only (test on the rendered text)
- [ ] A failed step-up that locks sends a notice naming the tool
- [ ] A hub start with the marker present but no running `guard` service, or with a `LockedGuard`, sends "the guard is not running"; `tau guard forget` sends "the guard was turned off"
- [ ] A change of the camera permission to `denied` sends one notice with the fix
- [ ] `[component.guard] notify = false` silences the guard's notices; `tau doctor` warns when the guard is active and no notifier runs
- [ ] No notice contains a chat id, a score or anything biometric; every notice key exists in `en` and `tr`

## Blocked by

- [111 · `tau-guard` service](111-tau-guard-service.md)

## Comments

- 2026-09-30: filed with ADR 0008. 101 should reuse the `OwnerNotifier` seam instead of adding its own.
