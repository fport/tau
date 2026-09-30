# 115 · TauBar: camera and microphone permission plumbing, webview media deny, guard line, "Lock now"

Status: done
Type: AFK
Layer: L10 · Guard
Packages: apps/taubar
Blocked by: 111

## What to build

TauBar runs the hub (084), so macOS attributes the hub's camera use, and later its microphone use, to TauBar. For that to work, TauBar needs:

- usage descriptions and device entitlements;
- a signing identity that stays stable across rebuilds;
- a deny for every webview media request, because wry grants `getUserMedia` by default and TauBar is about to hold a camera grant.

The menu also gains a guard line and a "Lock now" item. The decisions are in [ADR 0008](../../docs/adr/0008-owner-guard.md) (decisions 2, 8 and 16).

### Permission plumbing

- **Usage descriptions.** `apps/taubar/src-tauri/Info.plist` gains `NSCameraUsageDescription` and `NSMicrophoneUsageDescription` in English. They say that the hub TauBar runs uses the camera to check the owner's face and the microphone for voice. The texts go through `InfoPlist.strings` once 086 lands; until then they are English only.
- **Entitlements.** A new `Entitlements.plist` holds `com.apple.security.device.camera` and `com.apple.security.device.audio-input`, wired through `bundle.macOS.entitlements` in `tauri.conf.json`. The hardened runtime is on by default, so without them the grant is refused.
- **Webview media.** Every webview's `on_permission_request` answers Deny for camera and microphone. The TauBar window never needs them, because the guard runs in the hub.
- **Signing.** `apps/taubar/README.md` gets a section on creating and using a stable self-signed code-signing identity. With an ad-hoc signature (`"signingIdentity": "-"`), the designated requirement is a cdhash that changes on every build, and macOS resets the camera grant each time. The section also covers how to re-grant (the Privacy_Camera pane, `tccutil reset Camera <bundle id>`). This part is a human step. The committed config never contains a personal identity name: it reads the identity from an environment variable or a local, gitignored file, with an example value in the docs.

### Guard line and "Lock now"

- **Guard line.** The menu and the window show a guard line from the open `/status` `guard` block (`{state, enrolled, available, reason}`), such as "Guard: locked" or "Guard: unavailable (camera denied)". The line is hidden when there is no guard block or the state is `off`.
- **"Lock now".** It sends `POST /guard/lock` with `{channel: "taubar", client_id, trigger: "command"}` through a new `http_post` next to `http_get` in `src-tauri/src/hub/probe.rs`.
  - It reads `hub_dir/control.token` on every request and never sends it. It signs the request instead: a fresh `X-Tau-Nonce` and `X-Tau-Auth = hex(HMAC-SHA256(token, "req" | nonce | method | path))`, with `Content-Type: application/json` and no `Origin` (ADR 0008 decision 8; the exact bytes are pinned in tau-core's `test_request_auth_and_proof_are_separate_hmac_domains`).
  - It retries once after reading the token again on a 403.
  - It checks `X-Tau-Proof = hex(HMAC-SHA256(token, "resp" | nonce | method | path | status | body))`. A bad proof or a redirect is treated as "hub unavailable"; redirects are never followed.
- **Camera denied.** On `reason` `camera_denied` or `camera_unavailable`, a "Grant camera access…" item opens `x-apple.systempreferences:com.apple.preference.security?Privacy_Camera`.
- **Language.** The chrome stays English until 086 moves TauBar to the message table.

### Why 084 is not a blocker

084 (TauBar runs the hub) is `in-progress` only because of one acceptance criterion: that TauBar starts at a real login, which cannot be verified until the Mac restarts or the user logs out. The supervisor, the switches and the hub probe this issue builds on are done and live (see 084's comments). This issue changes the bundle metadata, the webview permission handler and the menu, none of which depend on the login start, so it is not blocked by 084.

## Acceptance criteria

- [x] The built `TauBar.app` Info.plist contains `NSCameraUsageDescription` and `NSMicrophoneUsageDescription`; `codesign -d --entitlements -` on the built app shows the camera and audio-input entitlements
- [x] Every webview media permission request is denied (a unit test on the permission handler, or a documented manual check with `getUserMedia` in the window returning `NotAllowedError`)
- [x] The guard line follows the `/status` guard block (tests with canned `/status` bodies: absent, `off`, `locked`, `unlocked`, `unavailable` with a reason), and is hidden without a guard
- [x] "Lock now" posts `/guard/lock` signed with the token read from the file (the token itself never leaves TauBar), retries once after a 403 with a re-read token, and treats a missing or wrong proof or a redirect as unavailable (tests against a local fake server)
- [x] On `camera_denied` the "Grant camera access…" item appears and opens the Privacy_Camera pane
- [x] The README documents the stable signing identity and the re-grant steps with example values only; no personal identity name is committed
- [x] `cargo test`, `cargo clippy` and `pnpm test` are green
- [ ] (user) TauBar is signed with a stable self-signed identity, rebuilt once, and the camera grant survives the rebuild; the hub TauBar runs gets the camera (`tau guard doctor` reports camera `ok` with TauBar as the responsible process). In the live menu, the guard items appear under the hub lines when the hub reports a guard and disappear when it stops or turns the guard `off`, and "Grant camera access…" (with the camera denied) opens the Privacy_Camera pane

## Blocked by

- [111 · `tau-guard` service](111-tau-guard-service.md)

## Comments

- 2026-09-30: filed with ADR 0008. Not blocked by 084, whose only open acceptance criterion is the start at a real login.
- 2026-09-30: built on the guard/taubar branch (commits eb4ead2, 9440ab0, 0aee791, 59d4f51, 669a1fb, c7c2986; 130's test-path fix is dba2f6d).
  - **Bundle.** `Info.plist` has `NSCameraUsageDescription` and `NSMicrophoneUsageDescription` (English); `Entitlements.plist` holds exactly `com.apple.security.device.camera` and `com.apple.security.device.audio-input`, wired through `bundle.macOS.entitlements`; `signingIdentity` stays `"-"`. `tests/bundle_config.rs` pins all of it, and the debug binary's embedded plist (`launchctl plist __TEXT,__info_plist target/debug/taubar`) shows both keys. The first criterion stays open: it needs a built `TauBar.app`, and this session was told not to build a bundle. The owner's next `pnpm tauri build` for the user criterion checks it with the README's `plutil` and `codesign -d --entitlements -` lines.
  - **Webview.** `webview::permission` denies every kind. It is installed on the app builder and on the settings window's `WebviewWindowBuilder`, so wry never falls back to its grant-by-default or to WebKit's prompt. A test checks the handler, and a source scan checks that every `WebviewWindowBuilder::new` installs it. The README documents the manual `getUserMedia` check.
  - **Signed requests.** `hub::control` mirrors tau-core's `request_auth`, `response_proof` and `HubClient` byte for byte. `hmac` 0.12 and its dependency `subtle` 2.6.1 are new in `Cargo.lock`; `getrandom`, `hex` and `sha2` became direct dependencies of taubar (they were already in the lock). The tests pin tau-core's vectors plus three more computed with tau-core itself, and run against a fake loopback hub: a 403 followed by a token re-read, a second 403 with no third try, a missing, foreign, body-mismatched or echoed-auth proof, a redirect, no token file, nothing listening. A manual end-to-end run of a throwaway Rust client against a real `tau_core.hub.control.ControlApi` (ephemeral port, temp `hub_dir`) passed: the lock was accepted, the proof verified, and the hub saw no `Origin`.
  - **Menu and window.** `HubView.guard` parses the open `/status` block. The state must be one of tau-core's states and the reason is shape-filtered (`[a-z0-9_]{1,48}`, not a closed list), because any local process can answer `/status`. The guard line, "Lock now" and "Grant camera access…" are inserted under the hub lines only while a guard runs. The camera item appears for `camera_denied` or `camera_unavailable`, in any state, and opens the Privacy_Camera pane through the opener plugin; that click is not exercised by a test. "Lock now" is always offered while a guard runs (locking is idempotent, and the menu can lag the hub by a poll). It runs off the main thread, logs the result, shows an error dialog when tau may not be locked, and polls `/status` at once. The window shows the same line and buttons (`lock_guard`, `open_camera_settings`).
  - **For later issues:** 086 moves these English strings to the message table and `InfoPlist.strings`. 025 and any other TauBar client of a protected route can reuse `ControlClient` (POST only for now; a GET is a few lines). Check the (user) criterion from TauBar's hub once 112 lands (`tau guard doctor`).
- 2026-09-30: verification fixes on guard/taubar (commits 84225a3, e4e0d8e, 9b775b8, bc633ee, dceacf7, ef04ec0).
  - **Menu deadlock (major).** `update_guard` held a std `Mutex` across `menu.remove`/`insert`; off the main thread each Tauri menu call blocks until the main thread runs it, so the hub thread (refresh every second) and a main-thread handler could freeze the event loop. `refresh` now posts `TrayMenu::update` with a non-blocking `run_on_main_thread` (it runs in place on the main thread), and the lock is never held across a menu call. `apply_guard_items` records only what the menu holds, so a failed insert or removal is retried. Tests drive it against a fake menu, and a source scan pins that the menu is only updated from `refresh`'s posted task (no unit test can reach a Tauri menu).
  - **Deadline.** `http_get` and `http_post` now give a whole request one deadline (connect, write and every read), so a listener that drips bytes cannot stretch "Lock now" or a supervisor step; a test drips an answer and expects an error within twice the timeout.
  - **Trust in the open `/status`.** The guard block reaches the menu only when TauBar's own hub is up, or when the pid that answers `/health` holds the hub lock (checked once per pid, again after `/health` went quiet); never while TauBar's hub is still starting.
  - **Smaller fixes.** A proof counts only as 64 lower-case hex digits, as in tau-core's `compare_digest`. The window's `lock_guard` runs in `spawn_blocking`. ADR 0008's TauBar bullet now says "Lock now" signs with the token and never sends it. The README notes that the camera grant covers whatever TauBar starts as the hub.
  - **First criterion.** Ticked on the verifiers' two bundle builds from this branch (`pnpm tauri build --bundles app --ci`, and `--debug --bundles app`, both into scratch `CARGO_TARGET_DIR`s): the Info.plist has both usage descriptions and `LSUIElement`, `codesign -d --entitlements -` lists exactly `com.apple.security.device.camera` and `com.apple.security.device.audio-input`, the flags are `adhoc,runtime`, and `codesign -vvv --strict` is valid. These fixes do not touch the plist, the entitlements or the bundle config.
  - **Order of work.** 115 went ahead of 111 on purpose, against the 110 contract in tau-core (`/status` guard block, `/guard/lock`, the signing); the only real server exercised is tau-core's `ControlApi` with a stand-in `/guard/lock`. For 111: the open block must be exactly `{state, enrolled, available, reason}` with snake_case reasons, and `POST /guard/lock` must always answer a proven `{"state": "locked"}`, also while the guard is unavailable, or TauBar shows "tau may not be locked". Once 111 lands, check the menu line and "Lock now" against the real `GuardService`. 130 (then `needs-triage`) was fixed here in dba2f6d because the repo-rule test failed without it; check for a parallel fix of `login.rs` before merging.
  - **Not done.** An app ACL manifest for the commands (optional; it would deny any command not listed, and this session cannot run the window to check it).
