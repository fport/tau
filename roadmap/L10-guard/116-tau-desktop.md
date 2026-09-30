# 116 · tau Desktop v0: Tauri app hosting `tau tui` in xterm.js + PTY

Status: done
Type: AFK
Layer: L10 · Guard
Packages: apps/tau-desktop (new)
Blocked by: none

## What to build

A separate desktop app for talking to tau, as the owner asked: `apps/tau-desktop`, built with Tauri v2, React and TypeScript, `@xterm/xterm` and `portable-pty`. Each window runs the real `tau tui` in a PTY and renders it with xterm.js, so every TUI feature, and later the guard's lock screen, works unchanged. The TUI's channel is `tui`, and no flag or environment variable ever changes it ([ADR 0008](../../docs/adr/0008-owner-guard.md), decisions 6 and 16). The app never uses the camera itself (the guard runs in the hub) and opens no network listener.

### App

- **Stack.** Tauri v2 with React/TS (pnpm), `@xterm/xterm` with the `fit`, `unicode11` and `web-links` addons, and `portable-pty` 0.9. The bundle id is `com.tau.desktop`.
- **The process.** One PTY per window runs `<python> -m tau_core tui` with cwd `TAU_HOME`.
- **Environment.** It is built like TauBar's `src-tauri/src/hub/launch.rs`, plus `TERM=xterm-256color`, `COLORTERM=truecolor` and `LANG=en_US.UTF-8`. A GUI app gets launchd's minimal environment, so nothing may be assumed from it.
- **Finding Python and the home.** Python is `<TAU_HOME>/.venv/bin/python`. `TAU_HOME` comes from the environment variable; failing that, from TauBar's `settings.json`, read-only and as a hint only; failing that, from a first-run folder picker. The picker validates the choice by running `<python> -m tau_core version`. There is no editable Python field: an arbitrary executable there would be a code-execution primitive.
- **I/O.** Raw PTY bytes go over `tauri::ipc::Channel`, coalesced every 8–16 ms, into `term.write(Uint8Array)`. The bytes are never decoded to strings per chunk, which would corrupt multi-byte characters such as ğüşıöç or box drawing split across reads. A resize calls `master.resize`.
- **Keys and selection.** `macOptionIsMeta: false`, because Option types `@ # $ [ ] { } | \ ~` on Turkish and other layouts, and tau's bindings are ctrl and F-keys. `macOptionClickForcesSelection: true` lets text be selected even though Textual turns on mouse tracking.
- **Font.** The system monospace stack (Menlo, SF Mono). No remote fonts, per ADR 0006.
- **Closing.** Closing a window writes ctrl+q to the PTY, waits 1 s, then kills the process group; the TUI's own quit path releases a running guard attempt. The app asks for confirmation before closing a window whose TUI is mid-turn, if that can be detected cheaply; otherwise it documents the behaviour.
- **Windows.** ⌘N opens a new window with its own PTY.
- **No listeners.** The app opens no network listener.
- **Permissions.** Every webview's `on_permission_request` answers Deny. The app has no camera or microphone usage description and no device entitlements.
- **Capabilities** are scoped per window.
- **Chrome.** English (menu, errors, the first-run picker), with a pointer to 086 for the message table.
- **Icons** come from `docs/brand`; never redraw them.
- **README.** It covers build, run and first run, with example values only.

### Tests

- vitest covers the frontend helpers: output coalescing, resize debouncing and the key options.
- `cargo test` covers the environment builder and Python/home discovery: the env var, TauBar's settings as a hint, the picker validation and rejection of a folder without a venv.

## Acceptance criteria

- [x] `pnpm tauri build` produces the app bundle (bundle id `com.tau.desktop`, product name "tau Desktop"); `pnpm test` (vitest) and `cargo test` / `cargo clippy` are green
- [x] A window runs `<TAU_HOME>/.venv/bin/python -m tau_core tui` in a PTY with the documented environment and cwd; the TUI renders with colours and box drawing, and ğüşıöç typed and printed survive chunk boundaries (test feeding split UTF-8 through the coalescer)
- [x] Resizing the window resizes the PTY; ⌘N opens a second independent window
- [x] Option-typed characters on a Turkish layout reach the TUI as text (`macOptionIsMeta: false`); Option-click selects text
- [x] Closing a window sends ctrl+q, then kills the process group after 1 s; no orphan `tau_core tui` process stays behind (test or documented check with `pgrep`)
- [x] First run without `TAU_HOME` offers TauBar's home as a hint or a folder picker, and refuses a folder where `-m tau_core version` fails; there is no free-form Python path field
- [x] The app denies webview media permission requests, declares no camera or microphone usage, and opens no listening socket (`lsof -i` check documented)
- [x] Icons come from `docs/brand`; the README covers build and run with example values
- [ ] (user) One live session in tau Desktop on the owner's Mac: open, chat, `/sessions`, resize, close; the result goes under Comments

## Blocked by

None - can start immediately. The guard's lock screen (113) appears in the app without changes here once it lands.

## Comments

- 2026-09-30: filed with ADR 0008. `apps/tau-desktop` still has to be added to the repo map in CLAUDE.md and to the layout in `docs/ARCHITECTURE.md` in the final docs pass.
- 2026-09-30: built in `apps/tau-desktop` (commits 047ff6b Rust core, 24a1fa0 window, b1883ff README). Green: `pnpm test` (23 vitest tests), `pnpm build`, `cargo test` (28 tests, stable over 5 runs), `cargo clippy --all-targets -- -D warnings`, and `cargo check`/`clippy` with `--features tauri/custom-protocol` (the production context with the CSP and embedded assets compiles). Not run, as the task instructed: `pnpm tauri build` and launching the app, so the first criterion stays open until the owner builds it for the live session. A scratch harness (not committed) ran the real `python -m tau_core tui` in a PTY with this environment, a scratch `TAU_HOME`/`TAU_DATA_DIR` and an unused hub port. It rendered truecolor, box drawing and blocks, the alternate screen and mouse tracking with no U+FFFD, and ctrl+q ended it cleanly in 0.29 s. Resize, ⌘N, Option typing and Option-click are implemented and tested below the GUI (PTY resize test, key-option tests); seeing them in the window is part of the live session.
  - Deviations and choices: the brief's `-m tau_core --version` does not exist, so the check runs `-m tau_core version` as the issue says. `LC_ALL`/`LC_CTYPE` are inherited only when they are UTF-8. `TAU_LANG` is not passed (TauBar parity); the language comes from `[ui] language`. There is no confirmation before closing mid-turn, because the TUI's state is not readable cheaply from outside; the README documents it. A clean TUI exit (ctrl+q) closes its window. An error exit keeps the window with "Enter starts it again". Closing the last window keeps the app running, like Terminal. Output is batched on both sides: Rust sends at most one Channel message per 8 ms while output keeps coming, and a chunk after a quiet spell at once; the page coalesces for 8 ms. `pty_write` runs off the main thread, so the page keeps one write in flight (`InputQueue`) to preserve key order. Closing writes ctrl+q from its own thread, and the process group is killed only under the exit lock (waitid `WNOWAIT`), so a recycled pid is never signalled. Links open only on ⌘-click, http(s) only, through Rust; the capability grants the page no core, dialog or opener permission. The icons are generated from `docs/brand/tau-app-icon.svg`, the same images as TauBar's (the PNGs are byte-identical; `icon.icns` holds identical images in a different container); a distinct icon would need a brand decision. `apps/tau-desktop` is not in CI, like TauBar (`.github/workflows/ci.yml` runs only Python and docs).
  - For later issues: 113's lock screen shows up unchanged, and the desktop relies on the TUI's ctrl+q path releasing a running guard attempt (it never calls `/guard/cancel` itself). 086 now also covers the desktop chrome: the menu, the first-run page, notices and errors. Possible follow-ups: `@xterm/addon-clipboard`, so Textual's own OSC 52 copy works (today only Option-drag + ⌘C does); a cheap busy signal from the TUI (an OSC sequence) for a close confirmation; the WebGL renderer if the DOM renderer is slow in big windows. `test_no_personal_paths_in_tracked_files` still fails on this branch because of issue 130 (TauBar's `login.rs` and 130's own file), which predates this work.
  - Final docs pass: add `apps/tau-desktop/  # Tauri v2 + React/TS + xterm.js: tau tui in a native window (#116)` to the CLAUDE.md repo map and the `docs/ARCHITECTURE.md` layout, add tau Desktop to CONTEXT.md's Channel entry (it is the `tui` channel), and add a short docs-site guide or a section in `docs/guides/taubar.md` pointing to `apps/tau-desktop/README.md` (build, first run, keys).
- 2026-09-30: verification fixes (1389ae7, d9a3949, a3a8223, e911ef8, 3fdf0c5, b7a55e7, 7f9647a). The release build is verified: `pnpm tauri build --ci` (build only, nothing launched) produces `src-tauri/target/release/bundle/macos/tau Desktop.app` (6.2 MiB) with CFBundleIdentifier `com.tau.desktop`, CFBundleName and CFBundleDisplayName `tau Desktop`, executable `tau-desktop`, no `*UsageDescription` keys, and an ad-hoc signature with hardened runtime and no entitlements. So criterion 1 is ticked and the issue is done; the (user) live session stays open. Green: `pnpm test` (26 vitest tests), `pnpm build`, `cargo test` (43 tests; the 15 PTY tests passed 20 runs in a row), `cargo clippy --all-targets -- -D warnings` with and without `--features tauri/custom-protocol`.
  - Reload (major): a page reload (Tauri reloads a page whose web content process crashed; `pnpm tauri dev`; WKWebView's right-click Reload) used to leave the TUI running out of reach while every Enter failed with "already running". Now `pty_start` hands the running session to the new page: the output sink and the exit report are swapped under one lock, a tracker of DEC private modes replays what the TUI switched on (alternate screen, mouse, focus, bracketed paste, cursor; never 2026), and a real size change makes Textual repaint (the new grid size, or one row smaller for 150 ms when it is the same, because Textual ignores a SIGWINCH with an unchanged size). Checked against the real `tau tui` in a scratch PTY: a same-size resize repaints 2 rows, the nudge all 40. After the exit has been reported nothing can take over, and Enter starts a new TUI. The page resizes after start only if the grid changed (so it cannot cut the repaint short), and the webview context menu is suppressed outside `.xterm`. A reload during a turn keeps the turn and any guard attempt running.
  - CI (major): `.github/workflows/ci.yml` has a `desktop` job on Ubuntu (WebKitGTK dev packages, pnpm install --frozen-lockfile, vitest, `pnpm build`, `cargo test --locked`, `cargo clippy --locked --all-targets -D warnings`); the same steps pass in an Ubuntu 24.04 container. ADR 0008 also says the app joins "the release lists", but `release.yml` only publishes the PyPI wheels; the final docs pass should either amend that sentence or file an issue for a macOS release artifact. TauBar is still not in CI.
  - Minors fixed: `open_link` opens the parsed canonical URL, not the raw text; the version check runs in its own process group and a timeout kills the group and gives the pipes 1 s instead of waiting for EOF (the new test fails on the old code after 30 s); New Window and Quit are `Cmd+N`/`Cmd+Q`, never `CmdOrCtrl`; the TAU_HOME rules moved to `home::resolve`/`accept`/`accept_hint` with tests for a broken TAU_HOME, a broken saved choice, a missing hint and saving; the env test no longer calls USER and LC_ALL off-list and a new test shows the whole allowlist passing through. README: reloads, the TCC note (file and Local Network grants caused by the TUI go to tau Desktop and reset with a new ad-hoc signature), a checkout without `tau.toml` opening tau's setup wizard, TauBar's data dir and port not being passed on (keep `TAU_DATA_DIR` and the hub port in the checkout's `.env`/`tau.toml`), and the icon wording.
  - For 111/113: the desktop still relies on the TUI's ctrl+q path to release a running guard attempt; a TUI killed after the 1 s grace, or an interpreter exit that kills `HubGuard`'s fire-and-forget `/guard/cancel` thread, leaves a hub-side check running until its deadline. The TUI's quit path should await a bounded cancel (about 0.5 s, inside the desktop's grace), and the hub should keep attempts short-deadlined or cancel them when the client's long-poll goes away.
  - The final docs pass entries listed above are unchanged (CLAUDE.md repo map, ARCHITECTURE layout, CONTEXT Channel note, a docs-site pointer to `apps/tau-desktop/README.md`).
