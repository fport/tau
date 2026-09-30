# 126 · Guard window in TauBar: live camera preview and head-turn prompts

Status: ready-for-agent
Type: AFK
Layer: L10 · Guard
Packages: apps/taubar, tau-guard
Blocked by: 112, 115

## What to build

The owner tried the face check from the terminal on 2026-09-30 and asked for it to happen on a screen instead: following "turn your head left" from text, without seeing the camera, is hard. When a verification starts (unlock, recheck, step-up or enrollment, from any channel: `tau tui`, `tau chat`, tau Desktop), TauBar opens a small **Guard window** that shows what the check sees and what to do, then closes itself.

### Shape

- **Trigger.** TauBar already runs the hub and polls it. It long-polls the protected `GET /guard/status?since=<seq>&wait=25` with its signed client (115) and opens the window when an attempt starts, whichever channel started it. It closes the window about 1.5 s after the attempt is done.
- **Content, in the TauBar visual language (the 089 panel tokens):**
  - the camera picture, mirrored, with an oval face guide;
  - a large direction mark for the current step (`look`, `turn_left`, `turn_right`, `center`, and the enrollment poses), from the attempt's `step`;
  - a countdown ring from the attempt's `deadline`;
  - the live hint (`too_dark`, `face_too_small`, `multiple_faces`, …) as one short line;
  - the result: a pass mark or the verdict reason, with the next action (try again, Touch ID, `tau guard doctor`).
  - The window is always on top, non-activating where macOS allows it, and has no controls besides Cancel (which posts `/guard/cancel`).
- **Where the picture comes from.** The verdict stays in the worker (ADR 0008 decision 2); the window only displays. First choice: the Guard window's own webview opens the camera with `getUserMedia`, and TauBar's `on_permission_request` grants camera **only** to that window's bundled page and still denies every other webview and every other origin. Nothing is recorded, stored or sent; the stream stops when the window closes.
  - **Spike first:** confirm that macOS lets the TauBar webview and the worker (a child of the hub, itself a child of TauBar) capture from the built-in camera at the same time, and measure the effect on the worker's frame rate. If concurrent capture fails, the fallback is the worker sending low-resolution preview frames (for example 320×240 JPEG at 10 fps) to TauBar over a local pipe, never through the hub process or the control API; decide in the spike and record it.
- **ADR 0008 amendment.** Decision 2 ("frames exist only in the worker's memory") and decision 16 (TauBar denies every webview media request) change: TauBar's Guard window may show the camera, display-only, during an attempt. Record the new rule and why it keeps the threat model (the picture never leaves TauBar's process; no route carries frames; other webviews stay denied).
- **Channels keep their text prompts.** The TUI busy line and the terminal lines stay as they are; the window is an addition. Without TauBar (hub from a terminal), nothing changes.
- **i18n.** The window's strings follow the language decision of 086; until then English, with the Turkish texts prepared from `tau_core.guard`'s message keys.

## Acceptance criteria

- [ ] A spike records whether concurrent capture (TauBar webview + worker) works on the hub Mac and which preview path is used
- [ ] An attempt started from `tau tui`, `tau chat` or tau Desktop opens the Guard window within 0.5 s; it shows the mirrored picture, the oval, the current step's direction mark, the countdown and the live hint, and closes about 1.5 s after the verdict
- [ ] Cancel in the window cancels the attempt (`/guard/cancel`) and the channel shows `cancelled`
- [ ] Only the Guard window's bundled page can get the camera; every other webview and origin is still denied (test)
- [ ] The camera stream stops when the window closes; nothing is recorded or stored; no route or pipe through the hub carries frames
- [ ] ADR 0008 is amended (decisions 2 and 16) and the guard guide shows the window
- [ ] (user) One unlock and one step-up done through the window on the hub Mac

## Blocked by

- [112 · Face verification](112-face-verification.md)
- [115 · TauBar guard plumbing](115-taubar-guard-plumbing.md)

## Comments

- 2026-09-30: filed from the owner's first live try ("guard açılınca bir ekranda gözükse orda yapsak iyi olacak").
