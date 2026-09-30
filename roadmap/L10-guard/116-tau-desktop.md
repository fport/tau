# 116 · tau Desktop v0: Tauri app hosting `tau tui` in xterm.js + PTY

Status: ready-for-agent
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

- [ ] `pnpm tauri build` produces the app bundle (bundle id `com.tau.desktop`, product name "tau Desktop"); `pnpm test` (vitest) and `cargo test` / `cargo clippy` are green
- [ ] A window runs `<TAU_HOME>/.venv/bin/python -m tau_core tui` in a PTY with the documented environment and cwd; the TUI renders with colours and box drawing, and ğüşıöç typed and printed survive chunk boundaries (test feeding split UTF-8 through the coalescer)
- [ ] Resizing the window resizes the PTY; ⌘N opens a second independent window
- [ ] Option-typed characters on a Turkish layout reach the TUI as text (`macOptionIsMeta: false`); Option-click selects text
- [ ] Closing a window sends ctrl+q, then kills the process group after 1 s; no orphan `tau_core tui` process stays behind (test or documented check with `pgrep`)
- [ ] First run without `TAU_HOME` offers TauBar's home as a hint or a folder picker, and refuses a folder where `-m tau_core version` fails; there is no free-form Python path field
- [ ] The app denies webview media permission requests, declares no camera or microphone usage, and opens no listening socket (`lsof -i` check documented)
- [ ] Icons come from `docs/brand`; the README covers build and run with example values
- [ ] (user) One live session in tau Desktop on the owner's Mac: open, chat, `/sessions`, resize, close; the result goes under Comments

## Blocked by

None - can start immediately. The guard's lock screen (113) appears in the app without changes here once it lands.

## Comments

- 2026-09-30: filed with ADR 0008. `apps/tau-desktop` still has to be added to the repo map in CLAUDE.md and to the layout in `docs/ARCHITECTURE.md` in the final docs pass.
