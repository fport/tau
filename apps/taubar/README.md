# TauBar

tau's macOS menu bar app: Tauri v2 with a Rust core and a small React/TypeScript UI (the panel
and the settings window). Tray only, no Dock icon.

What it does today:

- **Runs the hub:** with "Run the hub" switched on, TauBar starts `tau hub run`, restarts it
  after a crash, leaves it stopped after `tau hub stop`, stops it when TauBar quits, and never
  starts a second hub. It shows whether the hub is up, its Telegram poller and its last crash.
- **Shows the owner guard** when the hub runs one ([ADR 0008](../../docs/adr/0008-owner-guard.md)):
  its state, **Lock now**, and **Grant camera access…** when the hub cannot use the camera.
  TauBar holds the camera and microphone permission for the hub it runs.
- **Sleep modes:** Normal, Keep awake on AC power (default), Keep awake with the lid closed.
- **Launch at login:** a switch that registers TauBar as a login item.
- A **panel** under the τ with all of that (left click), the same items as a native **menu**
  (right click), and a **window** (Settings…) with the same switches, the hub's settings and
  TauBar's own log.

The status panel for nodes, spend and approvals, and voice come with later roadmap issues (025,
031).

```text
Hub                                      [ on]
(τ)  Up 2 h 5 min
     pid 1234 · started by TauBar
(➤)  Telegram
     polling as @your_bot
(!)  Last crash
     none
(▣)  Guard                          (only with a guard)
     unlocked
     Lock now                       (only with a guard)
──────────────────────────────────────────────
Sleep
( )  Normal
(●)  Keep awake on AC power
( )  Keep awake with the lid closed    Set up…
──────────────────────────────────────────────
Launch at login                          [ on]
Open Hub Log
Open TauBar Log
Settings…                                   ⌘,
──────────────────────────────────────────────
Quit TauBar                                 ⌘Q
```

## The panel

A left click on the τ opens the panel under the icon; another click, Esc, or clicking anywhere
else closes it, as with a menu, and the icon stays pressed while it is open. It is a borderless,
transparent window with macOS's popover material behind the page, so it follows light and dark
mode and the wallpaper shows through; its height follows its content. ⌘, opens the settings
window and ⌘Q quits TauBar while it has focus. The coin next to the hub status carries the state:
Ember when the hub is up, Flare when it needs attention, Signal on an error, dimmed otherwise.

The right click shows the old native menu with the same items, so every action stays reachable
if the panel ever fails to open (TauBar then also shows the menu on the left click and says why
in its log). Transparent windows use a private macOS API (`app.macOSPrivateApi` in
`tauri.conf.json`): fine for a Mac that builds its own TauBar, not allowed in the App Store.

## Build

Needs macOS 13 or later, Rust (`rustup`), [Bun](https://bun.sh), and the Xcode command line tools.

```sh
cd apps/taubar
bun install
bun run tauri build       # → src-tauri/target/release/bundle/macos/TauBar.app
```

`bun run tauri dev` runs it with hot reload for development. Launch at login needs the built
`.app` installed in `/Applications` (see below), so test that part with an installed build.

Only one TauBar runs at a time (`tauri-plugin-single-instance`, keyed by the bundle id): a
second launch, whether from Spotlight, Finder, `open -n` or the build folder, hands over to the
running TauBar, which shows its window, and exits before it touches the hub or the sleep
assertion. To run a development build, quit the installed TauBar first. Opening the build
folder's `TauBar.app` registers that copy with LaunchServices, and Spotlight may then prefer
it; after testing, `lsregister -u src-tauri/target/release/bundle/macos/TauBar.app` (the tool
lives in `/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/`)
removes it again.

### Signing

`src-tauri/tauri.conf.json` sets `bundle.macOS.signingIdentity` to `"-"`: `tauri build` signs
the app **ad hoc** (`codesign -dv TauBar.app` shows `Signature=adhoc`). That is enough for your
own Mac: an app you built yourself carries no quarantine flag, so Gatekeeper opens it. A copy
that arrives from another machine (a download, AirDrop) is quarantined; open it once with
right-click → Open, or clear the flag with `xattr -dr com.apple.quarantine TauBar.app`.

An ad-hoc signature changes with every build, so macOS sees each build as a new app. After
replacing TauBar.app with a new build, check that "Launch at login" is still ticked.

For a Developer ID signature and notarization, set `APPLE_SIGNING_IDENTITY` (and `APPLE_ID`,
`APPLE_PASSWORD`, `APPLE_TEAM_ID` for notarization) before `bun run tauri build`; see Tauri's
[macOS code signing](https://v2.tauri.app/distribute/sign/macos/) guide.

Every build is signed with the hardened runtime (Tauri's default) and the entitlements in
[`src-tauri/Entitlements.plist`](src-tauri/Entitlements.plist): the camera
(`com.apple.security.device.camera`) and the microphone
(`com.apple.security.device.audio-input`). `src-tauri/Info.plist` adds
`NSCameraUsageDescription` and `NSMicrophoneUsageDescription`. Without them macOS refuses the
camera and the microphone to the hub TauBar runs, without asking.

### A stable signing identity (for the camera grant)

macOS keeps a camera grant for an app's *designated requirement*. For an ad-hoc signature that
is the hash of the build itself, so every rebuild is a new app to macOS: the camera grant is
gone, and the next camera use asks again or is refused silently. A self-signed code-signing
certificate gives a designated requirement that stays the same from build to build
(`identifier "com.tau.taubar" and certificate leaf = H"..."`), so the grant survives rebuilds.

Set it up once (this is a step for you; nothing in the repo does it):

1. Keychain Access → Keychain Access menu → Certificate Assistant → **Create a Certificate…**
   - Name: any name, for example `TauBar Local Signing` (it stays in your keychain);
   - Identity Type: **Self Signed Root**;
   - Certificate Type: **Code Signing**.
2. Check that it is there: `security find-identity -p codesigning` lists `TauBar Local Signing`.
   If `codesign` later says the certificate is not trusted, open it in Keychain Access and set
   Trust → Code Signing to **Always Trust**.
3. Build with it. The committed `tauri.conf.json` keeps `"signingIdentity": "-"` (a certificate
   name can be personal, so it never goes into the repo); `APPLE_SIGNING_IDENTITY` wins over it
   for the build:

   ```sh
   cd apps/taubar
   export APPLE_SIGNING_IDENTITY="TauBar Local Signing"   # your certificate's name
   bun run tauri build
   ```

   To keep the name out of your shell history and profile, put the `export` line in a file the
   repo ignores (`*.local`), for example `apps/taubar/signing.local`, and run
   `source signing.local && bun run tauri build`. The first build asks whether `codesign` may use
   the key: choose **Always Allow**. Without the notarization variables Tauri skips
   notarization, which a build for your own Mac does not need.
4. Check the build:

   ```sh
   APP=src-tauri/target/release/bundle/macos/TauBar.app
   codesign -dv "$APP" 2>&1 | grep -E 'Authority|Signature'   # Authority=TauBar Local Signing
   codesign -d -r- "$APP"                  # designated => identifier "com.tau.taubar" and certificate leaf = H"..."
   codesign -d --entitlements - "$APP"     # com.apple.security.device.camera, ...device.audio-input
   plutil -p "$APP/Contents/Info.plist" | grep UsageDescription
   ```

   The `designated =>` line stays the same across rebuilds as long as the certificate does.

### The camera grant

TauBar runs the hub as its child, so macOS asks for the camera in TauBar's name the first time
the hub's guard opens it ("TauBar would like to access the camera"). Allow it. The grant then
lives in System Settings → Privacy & Security → **Camera**, where TauBar has its own switch; the
menu's **Grant camera access…** opens that pane. The camera indicator in the menu bar names
TauBar while the guard checks.

- **After changing the signing identity** (ad hoc → the certificate above, or a new
  certificate), macOS sees a new app: grant the camera again.
- **To start over while testing:** `tccutil reset Camera com.tau.taubar` (and
  `tccutil reset Microphone com.tau.taubar`), then restart the hub from TauBar (untick and tick
  **Run the hub**). The next camera use asks again.
- **Who holds the grant** depends on how the hub runs: TauBar's **Run the hub** → TauBar;
  `bun run tauri dev` → the terminal that runs it; `uv run tau hub run` in a terminal → that
  terminal app; the `com.tau.hub` launchd agent or a hub started over SSH or in tmux → nobody,
  so the camera is refused.
- `tau guard doctor` (roadmap 112) reports the camera state; with TauBar running the hub it
  should say `ok`.
- **The grant covers whatever TauBar starts as the hub:** the Python and the checkout in
  TauBar's settings. Whoever can change those settings (the window, or any process running as
  you) can have TauBar start another program with its camera grant, without a prompt. ADR 0008
  puts anyone with a shell in your account out of scope; this is one more thing they can do.

## Install

```sh
cp -R src-tauri/target/release/bundle/macos/TauBar.app /Applications/
open -a TauBar
```

The first start opens TauBar's window; after that it lives in the menu bar as **τ**. Then:

1. Pick a sleep mode (Keep awake on AC power is the default).
2. Tick **Launch at login**.
3. Run `infra/remote/setup.sh` once: with TauBar.app in `/Applications` it removes the
   `com.tau.keepawake` agent, whose job TauBar now does. `infra/remote/doctor.sh` accepts
   either one.
4. Let TauBar run the hub (next section).

**No τ in the menu bar?** On a MacBook with a notch, macOS hides menu bar icons that do not fit
next to the notch; new ones go first. Open TauBar again (Spotlight, Finder or
`open -a TauBar`) and its window appears, with every switch and a Quit button. To bring the icon
back, make room: quit other menu bar apps, or switch some off under System Settings → Menu Bar →
Allow in the Menu Bar (and check that TauBar is allowed there).

## The hub

With **Run the hub** ticked, TauBar is the hub's supervisor on this Mac (the job the
`com.tau.hub` launchd agent did; see [`infra/services/README.md`](../../infra/services/README.md)
for why TauBar is now the default):

| When | TauBar |
|---|---|
| You tick the switch, or TauBar starts with it ticked | starts `<python> -m tau_core hub run` in `TAU_HOME` as its own child; the menu shows `Hub: starting…`, then `Hub: up …` once `GET /health` answers (about a second) |
| The hub crashes or is killed (`kill -9`) | restarts it after 1 s; while it keeps failing the wait doubles up to 60 s, and goes back to 1 s after a run of a minute. The new hub reports the crash (`Last crash: unexpected exit (no clean shutdown)`) |
| `tau hub stop` (exit 0 without TauBar asking) | leaves it stopped; the switch shows off until you tick it again or TauBar starts again |
| You untick the switch | stops it (SIGTERM; SIGKILL after 15 s) |
| TauBar quits | stops the hub it started (SIGKILL after 10 s) |
| A hub TauBar did not start is running (by hand, or launchd) | shows it (`started outside TauBar`, `run by launchd`) and never starts a second one; unticking the switch tells you how to stop it. With the switch ticked, TauBar starts its own hub as soon as that one is gone, unless a loaded `com.tau.hub` launchd agent owns the same data dir |
| TauBar itself crashed and is started again | takes over the hub it had started (its pid is in `state.json` and still holds the hub lock) |

How the hub is started comes from the window (**How TauBar starts the hub**):

| Field | Default |
|---|---|
| Python | none: a Python with tau-core, normally `<checkout>/.venv/bin/python` |
| `TAU_HOME` | none: the directory with `tau.toml`; also the working directory |
| `TAU_DATA_DIR` | empty: what `tau.toml` / `.env` say (`~/.local/share/tau`) |
| Control port (`TAU_HUB_PORT`) | empty: `[hub] control_port` (7877) |
| `PATH` | `/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin` |
| More environment | `KEY=value` lines; they win over `.env` |

**Use a tau checkout…** fills in the first two from a folder. On its first start TauBar copies
Python, `TAU_HOME`, `TAU_DATA_DIR` and `PATH` from an installed `com.tau.hub` launchd agent, so a
Mac that ran the hub under launchd needs no typing. The hub inherits only `HOME`, `USER`,
`LOGNAME`, `TMPDIR`, `SHELL` and the locale from TauBar; `.env` in `TAU_HOME` is read by the hub
itself, as always.

Before every start TauBar runs `tau hub status --json` to learn which lock and port the
configuration resolves to, and probes that lock. Hub output: `<TAU_DATA_DIR>/hub/logs/taubar.{out,err}.log`;
the hub's log: `<TAU_DATA_DIR>/logs/tau.log` (**Open Hub Log**); every start, exit and restart
also lands in TauBar's own log.

Moving from the launchd agent to TauBar:

```sh
cd /path/to/tau
uv run tau hub uninstall      # stops the launchd hub and removes the agent
```

Then tick **Run the hub** (with it already ticked, TauBar starts its hub once the launchd one is
gone). To go back: untick the switch, then `uv run tau hub install`.

## The owner guard

When the hub runs the owner guard ([ADR 0008](../../docs/adr/0008-owner-guard.md)), the panel,
the menu and the window show it under the hub lines, from the `guard` block of the hub's open
`/status` (`{state, enrolled, available, reason}`). The panel has a **Guard** row (Flare when
the guard cannot check) with **Lock now** and **Grant camera access…** under it; the right-click
menu shows the same as lines:

```text
├─ Guard: unavailable (camera denied)
├─   Lock now
├─   Grant camera access…
```

| Guard line (the panel's row shows the same without `Guard:`) | When |
|---|---|
| `Guard: locked` | guarded channels (`tau tui`, `tau chat`) refuse turns until the owner's face is checked at the Mac |
| `Guard: checking…` | a face check is running |
| `Guard: unlocked` | the owner was verified |
| `Guard: unavailable (camera denied)` | the guard cannot check; the reason says why |
| `Guard: locked (not enrolled)` | no face is enrolled yet (`tau guard setup`) |

The whole section is hidden when the hub reports no guard or the state `off`. It is also hidden
while TauBar cannot tell that the hub itself answers: `/status` is open and unsigned, so any
local process that binds the free port can answer it. TauBar shows the guard block only when
its own hub is up, or when the pid that answers `/health` holds the hub lock (checked once per
pid); not while its hub is still starting. The state must be one TauBar knows and the reason
must look like tau-core's (`a-z`, `0-9`, `_`, at most 48 characters); anything else is dropped.
**Grant camera access…** appears when the reason is `camera_denied` or `camera_unavailable`
and opens System Settings → Privacy & Security → Camera.

**Lock now** asks the hub to lock (`POST /guard/lock`, `{"channel": "taubar", "client_id": …,
"trigger": "command"}`). TauBar reads `<TAU_DATA_DIR>/hub/control.token` for every request and
never sends it: it signs the request with it (`X-Tau-Nonce`, `X-Tau-Auth`) and trusts the answer
only with a valid `X-Tau-Proof`, exactly as tau-core's `HubClient` does. After a 403 it reads
the token again once (the hub writes a new one on every start). A missing or wrong proof, a
redirect (never followed) or no answer means the hub is unavailable, and TauBar says that tau
may not be locked. TauBar never unlocks: that is a face check at the Mac.

**No webview gets the camera.** wry grants a page's `getUserMedia` by default, and TauBar holds
the camera grant, so every TauBar webview denies every permission request (the app builder and
each window, the panel included, install the same handler, `src-tauri/src/webview.rs`). To
check by hand: in
`bun run tauri dev`, right-click the window → Inspect Element → Console, and run
`await navigator.mediaDevices.getUserMedia({video: true})`; it rejects with `NotAllowedError`
and no camera turns on.

## Sleep modes

| Mode | What TauBar does | Check |
|---|---|---|
| Normal | nothing | no TauBar line in `pmset -g assertions` |
| Keep awake on AC power | holds an IOKit `PreventSystemSleep` assertion, like `caffeinate -s`; macOS honours it only on AC power, so on battery or with the lid closed the Mac still sleeps | `pmset -g assertions` shows `PreventSystemSleep 1` and `pid …(taubar): … named: "TauBar keeps the Mac awake for tau"` |
| Keep awake with the lid closed | the assertion plus `sudo -n pmset -a disablesleep 1` through a narrow sudoers rule | `pmset -g` shows `SleepDisabled 1` |

The choice is saved and applied again at the next start. **Quitting restores normal sleep:**
TauBar releases the assertion and, if it set it, runs `pmset -a disablesleep 0`. The same
happens on SIGTERM, SIGINT and SIGHUP (logout, `kill <pid>`, Ctrl-C in `bun run tauri dev`). A
`kill -9` cannot be caught: macOS drops the assertion with the process, and `disablesleep` stays
until TauBar's next start resets it (or `sudo pmset -a disablesleep 0`).

### The lid-closed mode

It needs one sudoers rule, and TauBar shows the mode as unavailable ("needs setup") until the
rule is there. TauBar never runs sudo to find out: it looks for the file
`/etc/sudoers.d/tau-taubar`, and it only calls `sudo -n` (never a password prompt) after you pick
the mode. Install the rule from the checkout, in your own terminal:

```sh
apps/taubar/sudoers/install-sudoers.sh --print   # show the rendered rule and check it with visudo
apps/taubar/sudoers/install-sudoers.sh           # install it (sudo asks for your password)
```

The rule allows your user exactly two commands, with fixed arguments:

```text
<you> ALL=(root) NOPASSWD: /usr/bin/pmset -a disablesleep 0, /usr/bin/pmset -a disablesleep 1
```

The script renders [`sudoers/tau-taubar.sudoers`](sudoers/tau-taubar.sudoers) for `id -un`,
checks it with `visudo -c`, installs it as `/etc/sudoers.d/tau-taubar` (`root:wheel`, `0440`),
checks the whole sudoers configuration again (and removes the file if it does not parse), and
confirms with `sudo -n -l` that the command is allowed. TauBar notices the rule within five
seconds.

To remove it (this re-enables sleep first):

```sh
apps/taubar/sudoers/uninstall-sudoers.sh
```

A closed MacBook that does not sleep still makes heat. Use this mode on AC power with the Mac in
the open air, not in a bag.

## Launch at login

The checkbox registers TauBar with `SMAppService.mainApp` (macOS 13+), the same list as System
Settings → General → Login Items → Open at Login; you can switch it off there too, and TauBar's
checkbox follows within a few seconds. TauBar does not use a LaunchAgent with `RunAtLoad`: on
the Mac it was built on, launchd pended every automatic spawn of user agents (roadmap issues
057 and 052), and `tauri-plugin-autostart` offers only a LaunchAgent or an AppleScript login
item.

The registration points at the app where it is when you tick the box, so TauBar only turns it
on when it runs from `/Applications` or `~/Applications`; a copy anywhere else (the build folder
of a checkout, Downloads) shows "Launch at login needs TauBar.app installed in /Applications"
instead. With **Run the hub** ticked, this is also how the hub starts at login.

Verified on macOS 26.3.1: ticking the box registers TauBar (status `Enabled`), unticking removes
it (`NotRegistered`). Not verified yet: that it actually starts at the next login, because
nobody logged out while this was built; check it after your next login.

## Files

| Path | What |
|---|---|
| `~/Library/Application Support/com.tau.taubar/settings.json` | your choices: `sleep_mode`, `run_hub`, `hub` (how the hub is started) |
| `~/Library/Application Support/com.tau.taubar/state.json` | what TauBar changed and must undo or take over: `lid_engaged`, `hub_pid` |
| `~/Library/Logs/com.tau.taubar/taubar.log` | TauBar's short log (rotated once at 256 KB) |
| `<TAU_DATA_DIR>/hub/logs/taubar.{out,err}.log` | the hub's stdout and stderr while TauBar runs it |

`TAUBAR_HOME=/some/dir` keeps everything in one directory instead (`settings.json`,
`state.json`, `logs/taubar.log`): for tests or a second copy.

## Uninstall

1. Untick **Launch at login** (or remove TauBar in System Settings → Login Items).
2. Quit TauBar: it restores normal sleep and stops the hub it started. If the hub should keep
   running without TauBar, install the launchd agent: `uv run tau hub install`.
3. If you installed the sudoers rule: `apps/taubar/sudoers/uninstall-sudoers.sh`.
4. Delete `/Applications/TauBar.app` and the files above.
5. Run `infra/remote/setup.sh` if the Mac should still stay awake on AC power without TauBar:
   it installs `com.tau.keepawake` again.

## Development

```sh
bun run test                       # vitest: the display and form logic of the panel and window
bun run build                      # tsc + vite
(cd src-tauri && cargo test)       # Rust: supervisor, restart policy, sleep modes, settings, …
```

To work on the UI without the app, run `bun run dev` and open http://localhost:1420/ (the settings
window) or http://localhost:1420/#panel (the panel) in a browser: outside Tauri a development
build answers the commands from `src/devmock.ts`, a stand-in with example values. No build
contains it.

The supervisor tests run real `/bin/sh` children as stand-in hubs (crash, `kill -9`, clean
exit, a SIGTERM-deaf hub, a foreign lock holder, an orphan to adopt) against a fake probe, so
they need no tau checkout and never touch a real hub. The signing tests use the byte vectors
tau-core pins, and "Lock now" runs against a fake hub on a loopback port (a 403 and a token
re-read, a missing or wrong proof, a redirect).

| File | Job |
|---|---|
| `src-tauri/src/lib.rs` | app setup (tray only), menu actions, window, ticker and hub threads |
| `src-tauri/src/core.rs` | state shared by the panel, the menu and the window |
| `src-tauri/src/hub/supervisor.rs` | the hub supervisor (start, reap, restart, stop, adopt, never a second hub) |
| `src-tauri/src/hub/policy.rs` | which exits are restarted, and the backoff |
| `src-tauri/src/hub/probe.rs`, `launch.rs`, `display.rs` | lock/control API/launchd probes, the command and environment, the menu lines and panel rows |
| `src-tauri/src/hub/control.rs`, `guard.rs` | signed control requests (token, nonce, proof); the guard line and "Lock now" |
| `src-tauri/src/webview.rs` | denies every webview permission request |
| `src-tauri/Info.plist`, `Entitlements.plist` | usage descriptions and the camera/microphone entitlements (checked by `tests/bundle_config.rs`) |
| `src-tauri/src/sleep.rs` | the three modes behind a `Power` trait (a fake in tests) |
| `src-tauri/src/login.rs` | `SMAppService.mainApp` |
| `src-tauri/src/tray.rs` | the icon and the native menu (right click) |
| `src-tauri/src/panel.rs` | the panel's window: open under the icon, hide on focus loss, fit its height |
| `src-tauri/src/settings.rs`, `eventlog.rs`, `signals.rs`, `commands.rs` | settings files, TauBar's log, quit on signals, the commands the UI calls |
| `src/Panel.tsx`, `src/panel.css`, `src/icons.tsx` | the panel |
| `src/App.tsx`, `src/styles.css` | the settings window |
| `src/main.tsx`, `src/api.ts`, `src/format.ts`, `src/devmock.ts` | which view a window shows, the commands, display helpers, the browser stand-in |
| `sudoers/` | the lid-closed rule and its install/uninstall scripts |

The UI is English only for now; tau's other UIs take their strings from the `tau_core.i18n`
table, which TauBar cannot read yet.
