# tau Desktop

A desktop app for talking to tau: every window runs the real `tau tui` in a PTY and renders it
with [xterm.js](https://xtermjs.org/), so every TUI feature works unchanged, and so will the
guard's lock screen once it lands ([ADR 0008](../../docs/adr/0008-owner-guard.md), decision 16).
It is built with Tauri v2, React and TypeScript, `@xterm/xterm` and `portable-pty`.

- **One PTY per window**, running `<TAU_HOME>/.venv/bin/python -m tau_core tui` with
  `TAU_HOME` as its working directory. The TUI's channel is `tui`, as in Terminal; no flag or
  variable changes it.
- **No camera, no microphone.** The guard runs in the hub (TauBar holds the camera
  permission). tau Desktop has no usage descriptions and no device entitlements, and every
  webview permission request is denied.
- **No network listener.** The page loads from the app bundle and talks to Rust over Tauri's
  IPC. The TUI talks to the hub's control API like it does in Terminal.

## Build

Needs macOS 13 or later, Rust (`rustup`), Node 20+ with pnpm, and the Xcode command line tools.

```sh
cd apps/tau-desktop
pnpm install
pnpm tauri build          # → src-tauri/target/release/bundle/macos/tau Desktop.app
cp -R "src-tauri/target/release/bundle/macos/tau Desktop.app" /Applications/
```

The bundle id is `com.tau.desktop`. `pnpm tauri dev` runs the app with hot reload; only in
that mode does Vite serve the page on `localhost:1420`.

### Signing

Like TauBar, `tauri.conf.json` sets `bundle.macOS.signingIdentity` to `"-"`: `tauri build` signs
the app ad hoc, which is enough for your own Mac. tau Desktop uses no camera or microphone, so
no device permission is lost when the ad-hoc signature changes with a new build. macOS does hold
tau Desktop responsible for the TUI it runs, though: a file prompt (Desktop, Documents,
Downloads, removable volumes) or a Local Network prompt caused by the TUI or its tools is granted
to tau Desktop, and a rebuild with a new ad-hoc signature resets those grants. A copy from
another machine is quarantined: open it once with right-click → Open, or run
`xattr -dr com.apple.quarantine "tau Desktop.app"`. For a Developer ID signature, set
`APPLE_SIGNING_IDENTITY` before `pnpm tauri build` (Tauri's
[macOS code signing](https://v2.tauri.app/distribute/sign/macos/) guide).

## How it finds tau

tau Desktop needs `TAU_HOME`: the tau checkout with `tau.toml` and the `.venv` that
`uv sync --all-packages` created. It looks in this order:

1. The `TAU_HOME` environment variable. An app opened from Finder or the Dock does not see your
   shell's variables, so pass it explicitly:
   `open --env TAU_HOME=/path/to/tau -a "tau Desktop"`.
2. The folder chosen on an earlier first run, kept in
   `~/Library/Application Support/com.tau.desktop/settings.json`.
3. Otherwise the window asks. If TauBar runs the hub, it offers TauBar's checkout (read from
   TauBar's `settings.json`, never written) as **Use This Folder**. **Choose Folder…** opens the
   macOS folder picker.

Before tau Desktop uses a folder, it runs `<folder>/.venv/bin/python -m tau_core version` there.
The folder is refused unless that succeeds and reports `tau-core`, for example because the
folder has no `.venv` or the venv has no tau-core. The Python is always the checkout's own
`.venv/bin/python`. There is no field for another interpreter: a configurable executable would
let anyone at the Mac run any program through the app.

The check does not look for `tau.toml`. A fresh checkout that has a venv but no `tau.toml` yet
opens tau's setup wizard in the window, as `tau tui` does in Terminal; run `uv run tau init`
first to skip it. Quitting the wizard ends the TUI with an error code, so the window stays open
with the exit notice, and Enter starts it again.

The TUI starts from an empty environment. It inherits only `HOME`, `USER`, `LOGNAME`, `TMPDIR`,
`SHELL`, `__CF_USER_TEXT_ENCODING` and a UTF-8 `LC_ALL`/`LC_CTYPE`. On top of that it gets
`PATH=/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin`, `TAU_HOME`,
`TERM=xterm-256color`, `COLORTERM=truecolor` and `LANG=en_US.UTF-8`. This is the list TauBar
uses for the hub (`apps/taubar/src-tauri/src/hub/launch.rs`) plus the terminal variables, so
the TUI behaves the same however the app was opened. tau itself reads `.env` and `tau.toml`
from `TAU_HOME`, as always. The UI language comes from `[ui] language` there, because `TAU_LANG`
is not passed through.

From TauBar's settings tau Desktop reads only the checkout (`hub.tau_home`), and only as the
first-run hint. TauBar's other hub settings (data folder, port, extra environment) reach only
the hub TauBar starts. Keep `TAU_DATA_DIR` and the hub port (`TAU_HUB_PORT`, or
`[hub] control_port` in `tau.toml`) in the checkout's `.env` and `tau.toml`, where both the hub
and the TUI read them. Set only in TauBar, they give the TUI in tau Desktop (and `tau tui` in
Terminal) another data folder or hub port than the hub TauBar runs: a separate session store,
and with the guard on, a lock that never opens because the TUI cannot reach the hub.

## Using it

| Key | What it does |
|---|---|
| ⌘N | A new window with its own `tau tui` |
| ⌘W | Close the window (see below) |
| ⌘Q | Quit: every window closes the same way |
| ⌘C / ⌘V | Copy the terminal selection / paste (bracketed paste) |
| ⌘A | Select everything in the terminal |
| ⌘M, ⌃⌘F | Minimize, full screen |

Every other key goes to the TUI: ctrl keys (`ctrl+q` quits the TUI and closes its window,
`ctrl+n` starts a new session, `ctrl+r` the session picker), Esc, and the F-keys. On a Mac
keyboard the F-keys need fn, unless System Settings → Keyboard → "Use F1, F2, etc. keys as
standard function keys" is on.

- **Option types characters.** Option is never Meta, so Option+Q gives `@` and Option+7 gives `{`
  on a Turkish layout, and the other Option characters (`# $ [ ] | \ ~`) work too. tau's
  bindings are ctrl and F-keys.
- **Selecting text.** Textual captures the mouse, so a plain drag goes to the TUI. Hold Option
  while dragging to select text, then press ⌘C. Textual's own copy (its selection plus
  ctrl+c) goes through OSC 52, which xterm.js does not handle without its clipboard addon.
- **Links.** ⌘-click an `http`/`https` link to open it in your browser. Other schemes are
  ignored.
- **Font.** The system monospace fonts (Menlo, then SF Mono). Nothing is downloaded.

**Closing a window** writes ctrl+q to its PTY, so the TUI goes through its own quit path, the
same as pressing ctrl+q in Terminal. The window hides at once. If the TUI has not exited
after one second, its whole process group gets SIGKILL, so nothing the TUI started stays
behind. tau Desktop does not ask before closing a window whose TUI is in the middle of a turn:
the TUI's state cannot be read cheaply from outside, and the quit path handles a running turn
as the TUI always does.

When the TUI exits on its own with an error, the window stays open, shows how it ended, and
Enter starts it again. After a clean exit (ctrl+q) the window closes. Closing the last window
leaves the app running, like Terminal. ⌘N or a click on the Dock icon opens a new window.

**A page reload keeps the TUI.** Tauri reloads a window's page when its web content process
crashes, and `pnpm tauri dev` reloads it after some edits. The TUI keeps running in its PTY
through that, and the new page takes it over: it first gets the terminal modes the TUI had
switched on (alternate screen, mouse reporting, focus events, bracketed paste, cursor), then the
PTY changes size (one row smaller for 150 ms if the size is the same), which makes the TUI paint
its whole screen again. A running turn or guard check carries on. The webview's right-click menu,
which offers Reload, is switched off outside the terminal; inside it, the text menu (Copy,
Paste) stays.

### Checks

After closing a window, or quitting, no TUI started by tau Desktop should remain:

```sh
pgrep -fl "tau_core tui"            # nothing, unless you run tau tui elsewhere
```

The app listens on no port, and asks for no camera or microphone access:

```sh
lsof -nP -a -iTCP -sTCP:LISTEN -p "$(pgrep -x tau-desktop | paste -sd, -)"   # nothing
plutil -p "/Applications/tau Desktop.app/Contents/Info.plist" | grep -i UsageDescription   # nothing
codesign -d --entitlements - "/Applications/tau Desktop.app"                   # no entitlements
```

## Development

```sh
pnpm test                          # vitest: output coalescing, input order, terminal and key options, resize, context menu
pnpm build                         # tsc + vite
(cd src-tauri && cargo test)       # Rust: environment, TAU_HOME discovery and validation, PTY sessions
(cd src-tauri && cargo clippy --all-targets -- -D warnings)
```

The PTY tests run `/bin/sh` scripts as stand-in TUIs in real PTYs. They cover raw bytes,
split UTF-8, resizing, the ctrl+q quit, the process-group kill, and a reloaded page taking over
a running TUI (modes replayed, a real size change). They need no tau checkout, and they run on
Linux too; CI runs all of the above on Ubuntu (`.github/workflows/ci.yml`, job `desktop`).

| File | Job |
|---|---|
| `src-tauri/src/lib.rs` | app setup, windows, menu, close and quit, signal handling, permission deny |
| `src-tauri/src/commands.rs` | the commands a window may call (its own PTY, the first-run choice, links) |
| `src-tauri/src/home.rs` | finding and validating `TAU_HOME`, TauBar's hint, the saved choice |
| `src-tauri/src/launch.rs` | the TUI command and its environment |
| `src-tauri/src/pty.rs` | one PTY session: raw output batching, input, resize, exit, shutdown, a new page taking over |
| `src-tauri/src/modes.rs` | the terminal modes the TUI switched on, replayed for a reloaded page |
| `src-tauri/capabilities/terminal.json` | what `term-*` windows may call; nothing else is granted |
| `src/TerminalView.tsx`, `src/FirstRun.tsx`, `src/App.tsx` | the window |
| `src/output.ts`, `src/input.ts`, `src/terminal.ts`, `src/api.ts` | output coalescing, ordered input, terminal options and helpers, command wrappers |

How output travels: the Rust reader forwards raw PTY bytes and batches output that keeps coming
into at most one message per 8 ms. Each message crosses a `tauri::ipc::Channel` as bytes. The
page gathers them for another 8 ms and calls `term.write(Uint8Array)`. Nothing decodes text on
the way, so a character split between two reads reaches xterm.js's decoder whole. Input goes the
other way as raw bytes, one `pty_write` in flight at a time, so keys arrive in order.

The icons are generated from `docs/brand/tau-app-icon.svg` (`pnpm tauri icon`), the same
source as TauBar's: the PNGs are byte-identical to TauBar's, and `icon.icns` holds the same
images (only its container bytes differ). The window's mark is `docs/brand/tau-mark.svg`,
imported as is.

The UI is English only for now. tau's other UIs take their strings from the `tau_core.i18n`
table, which the Tauri apps cannot read yet (issue 086).
