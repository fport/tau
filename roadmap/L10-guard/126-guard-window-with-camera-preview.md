# 126 · Guard window: the worker shows the camera and the step on the Mac's screen

Status: done
Type: AFK
Layer: L10 · Guard
Packages: tau-guard, tau-core
Blocked by: 112, 115

## What to build

The owner tried enrollment and verification from the terminal on 2026-09-30 and failed again and again because they could not see themselves: "Look at the camera. It is too dark", "Turn a little further", "Move closer to the camera" scrolled by as text. They asked for a screen-covering UI instead of the terminal ("ekrana bir şey gelse kaplasa ve orda ui olsa görsem, terminalde bunu yapmasak").

**Re-scoped (2026-09-30).** The first plan was a TauBar window that opened the camera a second time from its webview (or got preview frames over a pipe). Instead, the **guard worker itself** shows a full-screen window while an attempt runs. It already owns the frames, so there is no second camera session and no frame transport, frames never leave the worker, and it works for every path: `tau guard setup`/`enroll`/`verify` in a local worker, and every check through the hub (TUI, `tau chat`, tau Desktop, step-ups, rechecks) whether the hub runs under TauBar or a terminal.

### Shape

- **Where.** `tau_guard/overlay.py` (pyobjc AppKit, darwin only, imported lazily; `pyobjc-framework-Cocoa` joins the dependencies): an `NSApplication` with the Accessory policy (no Dock icon) and one borderless window over the main screen below the menu bar, at the status window level, activated, Void at 90 %, excluded from screen capture where macOS allows it. The AppKit loop runs on the worker's main thread and the operation in a second thread; the path without a window is unchanged.
- **Frames.** A `WatchedSource` hands every frame to the verifier and at most 20 per second to the window (dropped only for the picture). The main thread converts the newest one (BGR → BGRA → `CGImage`, at most 720 px wide) and draws it mirrored.
- **The look** (tau brand, docs/brand): the mirrored picture in a circle inside a thin neon τ ring, instrument ticks, the countdown to the step's deadline as a comet arc (the brand's thinking motion), the step as a large neon triangle (left/right for turns, up/down for the enrollment tilts, hollow and pointing at the camera for "look"), a bold uppercase monospaced line (`TURN LEFT` / `SOLA ÇEVİR`), the live hint in Flare, the τ guard wordmark and the purpose (unlock, presence check, step-up for `<tool>`, enrollment with `n/10 SAMPLES` and a segmented bar), an Ember ring fill with a check (`UNLOCKED`, `ENROLLED`, ...) or a Signal flash with a cross and the reason, closing 1.2 s after the verdict. Sharp corners, no emoji; macOS "Reduce motion" stops the motion.
- **Touch ID.** While LocalAuthentication asks (the `touch_id` op, an enrollment's prompt, the Touch ID half of `face_or_touch_id`) the window becomes a small panel at the top of the screen and the app deactivates, so the macOS prompt is never covered.
- **Esc** (or a click on the ESC · CANCEL chip) writes `{"type": "cancel"}`; the hub withdraws every client from the attempt through the usual cancel path (`cancelled`, or `spoof` when a head-turn prompt was up), the CLI answers `cancelled`.
- **Strings** go through the message table (`guard.window.*`, en + tr). The worker never imports tau-core, so the hub and the CLI put the lines, in the owner's UI language, into the request's `window` object.
- **Config:** `[component.guard] window = true | false` (default `true`; `window` joins `tau_core.guard.GUARD_CONFIG_KEYS`); `--no-window` on `setup`, `enroll` and `verify` for checks the command runs itself (a check through the hub follows the hub's setting, and the CLI says so). Without a GUI session (`SSH_CONNECTION`, no window server, no pyobjc AppKit, not macOS) or with `TAU_GUARD_WINDOW=0` the worker runs headless as before and logs why.
- **Demo:** `tau guard window` says whether the window can open here; `tau guard window --demo` plays a scripted unlock, a failed step-up and an enrollment on a synthetic dark picture, without the camera.
- **Channels keep their text prompts;** `verify --explain` shows the window too (the picture the numbers belong to), `--no-window` turns it off.

## Acceptance criteria

- [x] The worker shows the window for `verify`, `enroll` and `touch_id` when the request asks for it; the AppKit loop runs on the main thread, the check in a second thread; the headless path is unchanged
- [x] The verifier gets every frame and the window a throttled subset (test with a recording view); the view gets start, the steps with their deadlines, the hints, the samples, the result and the close
- [x] Esc cancels through the existing cancel path (hub: every client withdrawn, a head-turn prompt counts as `spoof`; CLI: `cancelled`); SIGTERM in window mode closes the window and releases the camera
- [x] The Touch ID step uses a small panel that never covers the macOS prompt
- [x] Brand look per docs/brand, strings in en + tr through the message table, Reduce motion respected
- [x] `[component.guard] window` and `--no-window`; headless without a GUI session, over SSH, without pyobjc or with `TAU_GUARD_WINDOW=0`, with the reason in `worker.log`
- [x] `tau guard window --demo` plays a scripted check without the camera
- [x] ADR 0008 has a "Refinement (issue 126)"; the guard guide and the reference describe the window, the key and the flag
- [ ] (user) One unlock and one step-up done through the window on the hub Mac, after a look at `tau guard window --demo`

## Blocked by

- [112 · Face verification](112-face-verification.md)
- [115 · TauBar guard plumbing](115-taubar-guard-plumbing.md)

## Comments

- 2026-09-30: filed from the owner's first live try ("guard açılınca bir ekranda gözükse orda yapsak iyi olacak").
- 2026-09-30: re-scoped to a window drawn by the guard worker (the owner: "ekrana bir şey gelse kaplasa ve orda ui olsa görsem, terminalde bunu yapmasak"); the TauBar webview and the concurrent-capture spike are no longer needed. ADR 0008 decisions 2 and 16 stay as they are.
- 2026-09-30: built on `guard/window` (from main cc4ffa7). Commits: 0b47651 (tau-core key), 89cb65a (the window in the worker, the cancel line, the service and the knob), cf0c3ba (`--no-window`, `tau guard window --demo`), a3930d3 (guide, reference, ADR 0008 "Refinement (issue 126)"). 57 new tests; the full suite passed (2564 passed, 8 skipped) but for the two timing-flaky tau-net universe tests, which pass when run alone. New modules `window.py` (the view seam, the frame tee, the model, the layout, the request field, the demo script), `overlay.py` (AppKit, lazily) and `cli_window.py`; small hooks in `worker.py` (`_Progress`, `_watched`, `run(view=, cancel=)`, the windowed `main`), `runner.py` and `local.py` (the cancel line; `EXIT_GRACE` 2 s so the result stays up), `service.py` (the request field, `_on_worker_cancel`), `config.py` (`window`), `cli_face.py` (`--no-window`), and `window` in tau-core's `GUARD_CONFIG_KEYS`. The challenge logic (`verify.py`, `liveness.py`, `enroll.py`) is untouched, so 127's branch merges around it. Tests never open a window: `RecordingView` fakes the view, the tests' `conftest.py` sets `TAU_GUARD_WINDOW=0` for any real worker, and the painter was checked by rendering scenes offscreen to PNG (`python -m tau_guard.overlay demo` with `snapshot`, also `tau guard window --demo --snapshot DIR`). A HUD frame paints in about 12 ms at Retina scale offscreen (the picture conversion about 1.4 ms), so 30 fps leaves the main thread room; the check runs in its own thread. Not verified here, for the owner: the live window itself (focus taking, Esc reaching it under macOS's cooperative activation, the frame rate on the hub Mac, the Touch ID panel next to the macOS prompt).
