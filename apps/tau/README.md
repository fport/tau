# tau (the Mac app)

tau's Mac app: a **τ** in the menu bar, the hub's supervisor, and chat windows that run
`tau tui`. It is what TauBar (the menu bar app) and tau Desktop (the chat windows) were, merged
into one app with one set of permissions ([ADR 0014](../../docs/adr/0014-one-installer-and-onboarding.md)
§3, roadmap 170). Tauri v2 with a Rust core, a small React/TypeScript UI and xterm.js.

What it does:

- **Runs the hub:** with "Run the hub" switched on, tau starts `tau hub run`, restarts it after a
  crash, leaves it stopped after `tau hub stop`, stops it when tau quits, and never starts a
  second hub. It shows whether the hub is up, its Telegram poller and its last crash.
- **Chat windows:** every window runs the real `tau tui` in a PTY and renders it with
  [xterm.js](https://xtermjs.org/), so every TUI feature works unchanged, the owner guard's lock
  screen included. **New Chat Window** (⌘N) is in the menu, the panel and the settings window.
- **Shows the owner guard** when the hub runs one ([ADR 0008](../../docs/adr/0008-owner-guard.md)):
  its state, **Lock now**, and **Grant camera access…** when the hub cannot use the camera. tau
  holds the camera and microphone permission for the hub it runs.
- **Sleep modes:** Normal, Keep awake on AC power (default), Keep awake with the lid closed.
- **Launch at login:** a switch that registers tau as a login item.
- **Updates:** release builds from GitHub update themselves (the Tauri updater), signed with the
  same identity every time, so macOS keeps the camera permission.

tau starts in the menu bar with no Dock icon. While a chat window is open it is a regular app,
with a Dock icon and the menu bar (tau, File, Edit, Window); closing the last chat window takes
it back to the menu bar only.

```text
Hub                                      [ on]
(τ)  Up 2 h 5 min
     pid 1234 · started by the app
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
New Chat Window                             ⌘N
──────────────────────────────────────────────
Launch at login                          [ on]
Open Hub Log
Open App Log
Settings…                                   ⌘,
Check for Updates…
──────────────────────────────────────────────
Quit tau                                    ⌘Q
```

## Install a release

1. Download `tau.dmg` from the [latest release](https://github.com/fport/tau/releases/latest),
   open it and drag **tau** to **Applications**.
2. Open tau from Applications. The first time, macOS says it cannot check tau for malicious
   software: the app is signed, but not notarised by Apple (ADR 0014 §6). Open **System
   Settings → Privacy & Security**, find the line about tau near the bottom and click **Open
   Anyway**, then confirm. On macOS 14 and earlier, right-click tau.app → **Open** does the
   same. In a terminal: `xattr -dr com.apple.quarantine /Applications/tau.app`.
3. The first start opens tau's settings window. Pick your tau checkout under **How tau starts
   the hub**, tick **Run the hub** and **Launch at login**.
4. The first time the hub's guard uses the camera, macOS asks in tau's name: allow it.

Updates come by themselves: a release build looks for one a minute after it starts and then
once a day, and asks before it installs (**Check for Updates…** asks at once; the settings
window can switch the daily check off). The update is signed with the same identity, so the
camera permission stays.

## Replacing TauBar and tau Desktop

tau has a new bundle id, `com.tau.app` (TauBar was `com.tau.taubar`, tau Desktop
`com.tau.desktop`), so it installs next to them rather than over them:

1. Quit TauBar (**Quit TauBar**: it stops the hub it runs and restores normal sleep) and tau
   Desktop.
2. In System Settings → General → Login Items, remove TauBar. Delete `/Applications/TauBar.app`
   and `/Applications/tau Desktop.app`.
3. Open tau. On its first start it takes over TauBar's settings (sleep mode, "Run the hub", how
   the hub is started) and tau Desktop's folder, read from
   `~/Library/Application Support/com.tau.taubar/settings.json` and `…/com.tau.desktop/settings.json`
   and never changed; then it opens its settings window once.
4. Tick **Launch at login** again: the login item belongs to the app.
5. macOS asks for the camera once more, now for tau: permissions belong to an app, and tau is a
   new one. TauBar's old entry can go: `tccutil reset Camera com.tau.taubar`.
6. The lid-closed sudoers rule keeps working (its file, `/etc/sudoers.d/tau-taubar`, keeps
   TauBar's name).
7. When all is well, delete the old files: `~/Library/Application Support/com.tau.taubar`,
   `~/Library/Logs/com.tau.taubar` and `~/Library/Application Support/com.tau.desktop`.

## Build from the checkout

Needs macOS 13 or later, Rust (`rustup`), [Bun](https://bun.sh), and the Xcode command line tools.

```sh
cd apps/tau
bun install
bun run tauri build       # → src-tauri/target/release/bundle/macos/tau.app
cp -R src-tauri/target/release/bundle/macos/tau.app /Applications/
open -a tau
```

`bun run tauri dev` runs it with hot reload for development. Launch at login needs the built
`.app` installed in `/Applications` (see below), so test that part with an installed build.

Only one tau runs at a time (`tauri-plugin-single-instance`, keyed by the bundle id): a second
launch, whether from Spotlight, Finder, `open -n` or the build folder, hands over to the running
tau, which shows a window, and exits before it touches the hub or the sleep assertion. To run a
development build, quit the installed tau first. Opening the build folder's `tau.app` registers
that copy with LaunchServices, and Spotlight may then prefer it; after testing,
`lsregister -u src-tauri/target/release/bundle/macos/tau.app` (the tool lives in
`/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/`)
removes it again.

**Opening tau again** (Spotlight, Finder, the Dock, `open -a tau`) brings its front window
forward; with none open it opens a chat window, or the settings window while no checkout is set
up yet. That is also the way in when macOS hides the menu bar icon behind the notch.

## Signing

Every build is signed with the hardened runtime and the entitlements in
[`src-tauri/Entitlements.plist`](src-tauri/Entitlements.plist): the camera
(`com.apple.security.device.camera`) and the microphone
(`com.apple.security.device.audio-input`). `src-tauri/Info.plist` adds
`NSCameraUsageDescription` and `NSMicrophoneUsageDescription`. Without them macOS refuses the
camera and the microphone to the processes tau starts, without asking. `tests/bundle_config.rs`
keeps these files right.

- **A build from the checkout** is signed **ad hoc** (`bundle.macOS.signingIdentity` is `"-"`):
  enough for the Mac that built it, which puts no quarantine flag on it.
- **A release build** is signed in CI with one stable self-signed identity, **tau
  (self-signed)** (next section). It is not notarised: Gatekeeper warns on first open (see
  Install).

### Why a stable identity keeps the camera permission

macOS keeps a privacy grant (the camera, the microphone, notifications) for an app's *designated
requirement*, the rule in its signature that says which code counts as "this app". For an
ad-hoc signature that is the hash of the build itself (`cdhash H"…"`), so every build is a new
app to macOS: the camera grant is gone, and the next camera use asks again or is refused
silently. A certificate gives a requirement that names the certificate instead of the build:

```text
designated => identifier "com.tau.app" and certificate leaf = H"<the certificate's SHA-1>"
```

As long as every build is signed with the same certificate, every build satisfies the same
requirement, and the grant survives updates. The certificate needs no Apple account and no
trust setting; codesign signs with it as it is. Moving to a Developer ID later changes only the
signing step (and the requirement once, with one more permission prompt).

### Releases (CI)

[`.github/workflows/app.yml`](../../.github/workflows/app.yml) runs on every `v*` tag (and by
hand, as a dry run by default) on a macOS runner:

1. builds a **universal** app (`--target universal-apple-darwin`: Apple silicon and Intel) with
   the tag's version, and with `TAU_APP_RELEASE=1`, which turns the daily update check on;
2. runs [`scripts/pack-release.sh`](scripts/pack-release.sh): imports the identity into a
   temporary keychain, runs `codesign --force --deep --options runtime` with the entitlements,
   checks the signature, and packs `tau.dmg`, `tau.app.tar.gz` with its updater signature
   (`.sig`, bound to the version) and `latest.json`;
3. attaches them to the tag's GitHub release, creating it when `release.yml` has not yet.

It needs four repository secrets, which the owner creates once on their own Mac:

```sh
apps/tau/scripts/make-signing-identity.sh
```

The script creates, in `apps/tau/.signing/` (gitignored; the directory 0700, the files 0600):

| File | What |
|---|---|
| `tau-signing.p12`, `.p12.base64`, `.p12.password` | the self-signed code-signing identity "tau (self-signed)" (RSA 3072, 10 years, `codeSigning` extended key usage) |
| `tau-signing.cert.pem` | its certificate, public |
| `updater.key`, `updater.key.password`, `updater.key.pub` | the Tauri updater's key pair (`tauri signer generate`) |

It writes the updater's public key into `src-tauri/tauri.conf.json` (`plugins.updater.pubkey`;
commit that change) and prints the commands that feed the files to the secrets on stdin, never
the secrets themselves:

```text
gh secret set MACOS_SIGNING_P12 < apps/tau/.signing/tau-signing.p12.base64
gh secret set MACOS_SIGNING_PASSWORD < apps/tau/.signing/tau-signing.p12.password
gh secret set TAURI_SIGNING_PRIVATE_KEY < apps/tau/.signing/updater.key
gh secret set TAURI_SIGNING_PRIVATE_KEY_PASSWORD < apps/tau/.signing/updater.key.password
```

Keep a copy of `.signing/` in your password manager. A new certificate means one more camera
prompt after the next update; a new updater key needs a release with the new public key before
older installs can update past it. Running the script again keeps what exists (`--force`
replaces it).

Without the secrets (a fork) the workflow still succeeds: the app is signed ad hoc and there is
no `.sig` and no `latest.json`, and warnings say so.

To sign a build from the checkout with the same identity, double-click
`.signing/tau-signing.p12` to import it into your login keychain (the password is in
`.signing/tau-signing.p12.password`) and build with
`APPLE_SIGNING_IDENTITY="tau (self-signed)" bun run tauri build`; the first build asks whether
codesign may use the key (**Always Allow**). Such a build is the same app to macOS as the
releases.

Check a build:

```sh
APP=/Applications/tau.app
codesign -dv "$APP" 2>&1 | grep -E 'Identifier|Signature|Authority'
codesign -d -r- "$APP"                  # designated => identifier "com.tau.app" and certificate leaf = H"..."
codesign -d --entitlements - "$APP"     # com.apple.security.device.camera, ...device.audio-input
plutil -p "$APP/Contents/Info.plist" | grep UsageDescription
```

### The updater

`src-tauri/tauri.conf.json`:

```json
"plugins": {
  "updater": {
    "pubkey": "<written by make-signing-identity.sh>",
    "endpoints": ["https://github.com/fport/tau/releases/latest/download/latest.json"],
    "requireSignedVersion": true
  }
}
```

The app fetches `latest.json` from the latest (non-pre-) release, compares versions, downloads
`tau.app.tar.gz`, checks its signature against the public key and the version the signature is
bound to, replaces itself, and opens again through its own quit path: the chat windows' TUIs
quit, the hub stops and restarts with the new app, normal sleep comes back in between. The
check runs from **Check for Updates…** in any build with a public key, and by itself (a minute
after the start, then once a day) only in release builds, while **Look for an update once a
day** is ticked. A check sends GitHub the usual request headers and nothing else.

## The camera grant

tau runs the hub as its child, so macOS asks for the camera in tau's name the first time the
hub's guard opens it ("tau would like to access the camera"). Allow it. The grant then lives in
System Settings → Privacy & Security → **Camera**, where tau has its own switch; **Grant camera
access…** opens that pane. The camera indicator in the menu bar names tau while the guard
checks.

- **The chat windows' TUIs** are tau's children too, so macOS attributes their camera use to
  tau as well: `tau guard setup` in a chat window enrols with tau's grant. The pages themselves
  never get a device: every webview denies every permission request (see below).
- **After changing the signing identity** (ad hoc → the certificate, or a new certificate), macOS
  sees a new app: grant the camera again.
- **To start over while testing:** `tccutil reset Camera com.tau.app` (and
  `tccutil reset Microphone com.tau.app`), then restart the hub from tau (untick and tick **Run
  the hub**). The next camera use asks again.
- **Who holds the grant** depends on how the hub runs: tau's **Run the hub** → tau;
  `bun run tauri dev` → the terminal that runs it; `uv run tau hub run` in a terminal → that
  terminal app; the `com.tau.hub` launchd agent or a hub started over SSH or in tmux → nobody,
  so the camera is refused.
- `tau guard doctor` (roadmap 112) reports the camera state; with tau running the hub it
  should say `ok`.
- **The grant covers whatever tau starts as the hub:** the Python and the checkout in tau's
  settings. Whoever can change those settings (the settings window, or any process running as
  you) can have tau start another program with its camera grant, without a prompt. ADR 0008
  puts anyone with a shell in your account out of scope; this is one more thing they can do. A
  chat window's page cannot change them: its capability grants it only its own PTY.

## The panel

A left click on the τ opens the panel under the icon; another click, Esc, or clicking anywhere
else closes it, as with a menu, and the icon stays pressed while it is open. It is a borderless,
transparent window with macOS's popover material behind the page, so it follows light and dark
mode and the wallpaper shows through; its height follows its content. ⌘N opens a chat window,
⌘, the settings window, and ⌘Q quits tau while the panel has focus. The coin next to the hub
status carries the state: Ember when the hub is up, Flare when it needs attention, Signal on an
error, dimmed otherwise.

The right click shows the native menu with the same items, so every action stays reachable if
the panel ever fails to open (tau then also shows the menu on the left click and says why in its
log). Transparent windows use a private macOS API (`app.macOSPrivateApi` in `tauri.conf.json`):
fine outside the App Store.

**No τ in the menu bar?** On a MacBook with a notch, macOS hides menu bar icons that do not fit
next to the notch; new ones go first. Open tau again (Spotlight, Finder or `open -a tau`) and a
window appears, with the app menu (tau → Settings…) while a chat window is open. To bring the
icon back, make room: quit other menu bar apps, or switch some off under System Settings → Menu
Bar → Allow in the Menu Bar (and check that tau is allowed there).

## Chat windows

**New Chat Window** (⌘N in the app menu and the panel, or the menu bar icon's menu) opens a
window with its own PTY running `<TAU_HOME>/.venv/bin/python -m tau_core tui` in `TAU_HOME`. The
TUI's channel is `tui`, as in Terminal; no flag or variable changes it.

### How a chat window finds tau

It needs `TAU_HOME`: the tau checkout with `tau.toml` and the `.venv` that
`uv sync --all-packages` created. It looks in this order:

1. The `TAU_HOME` environment variable. An app opened from Finder or the Dock does not see your
   shell's variables, so pass it explicitly: `open --env TAU_HOME=/path/to/tau -a tau`.
2. The folder chosen for the chat windows earlier, kept in
   `~/Library/Application Support/com.tau.app/chat.json`.
3. Otherwise the window asks. If tau runs the hub, it offers the hub's checkout (the settings'
   `tau_home`, never its Python) as **Use This Folder**. **Choose Folder…** opens the macOS
   folder picker.

Before a window uses a folder, tau runs `<folder>/.venv/bin/python -m tau_core version` there.
The folder is refused unless that succeeds and reports `tau-core`. The Python is always the
checkout's own `.venv/bin/python`; there is no field for another interpreter, so a chat window
cannot be turned into a launcher for any program. The check does not look for `tau.toml`: a
fresh checkout opens tau's setup wizard in the window, as `tau tui` does in Terminal. Quitting
the wizard ends the TUI with an error code, so the window stays open with the exit notice, and
Enter starts it again.

The TUI starts from an empty environment. It inherits only `HOME`, `USER`, `LOGNAME`, `TMPDIR`,
`SHELL`, `__CF_USER_TEXT_ENCODING` and a UTF-8 `LC_ALL`/`LC_CTYPE`. On top of that it gets
`PATH=/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin`, `TAU_HOME`,
`TERM=xterm-256color`, `COLORTERM=truecolor` and `LANG=en_US.UTF-8`: the list the hub gets
(`src-tauri/src/hub/launch.rs`) plus the terminal variables, so the TUI behaves the same however
the app was opened. tau itself reads `.env` and `tau.toml` from `TAU_HOME`, as always. The UI
language comes from `[ui] language` there, because `TAU_LANG` is not passed through.

The hub settings reach only the hub (data folder, port, extra environment). Keep `TAU_DATA_DIR`
and the hub port (`TAU_HUB_PORT`, or `[hub] control_port` in `tau.toml`) in the checkout's `.env`
and `tau.toml`, where both the hub and the TUI read them. Set only in tau's settings, they give
the TUI another data folder or hub port than the hub tau runs: a separate session store, and
with the guard on, a lock that never opens because the TUI cannot reach the hub.

### Keys

| Key | What it does |
|---|---|
| ⌘N | A new chat window with its own `tau tui` |
| ⌘W | Close the window (see below) |
| ⌘Q | Quit tau; while tau runs the hub it asks first, because the hub stops too |
| ⌘C / ⌘V | Copy the terminal selection / paste (bracketed paste) |
| ⌘A | Select everything in the terminal |
| ⌘, | The settings window |
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
behind. tau does not ask before closing a window whose TUI is in the middle of a turn: the
TUI's state cannot be read cheaply from outside, and the quit path handles a running turn as
the TUI always does.

When the TUI exits on its own with an error, the window stays open, shows how it ended, and
Enter starts it again. After a clean exit (ctrl+q) the window closes.

**A page reload keeps the TUI.** Tauri reloads a window's page when its web content process
crashes, and `bun run tauri dev` reloads it after some edits. The TUI keeps running in its PTY
through that, and the new page takes it over: it first gets the terminal modes the TUI had
switched on (alternate screen, mouse reporting, focus events, bracketed paste, cursor), then the
PTY changes size (one row smaller for 150 ms if the size is the same), which makes the TUI paint
its whole screen again. A running turn or guard check carries on. The webview's right-click menu,
which offers Reload, is switched off outside the terminal; inside it, the text menu (Copy,
Paste) stays.

After closing a window, or quitting, no TUI started by tau remains
(`pgrep -fl "tau_core tui"` shows nothing, unless you run `tau tui` elsewhere), and tau listens
on no port (`lsof -nP -a -iTCP -sTCP:LISTEN -p "$(pgrep -x tau-app)"` shows nothing).

## The hub

With **Run the hub** ticked, tau is the hub's supervisor on this Mac (the job the `com.tau.hub`
launchd agent did; see [`infra/services/README.md`](../../infra/services/README.md) for why the
app is the default):

| When | tau |
|---|---|
| You tick the switch, or tau starts with it ticked | starts `<python> -m tau_core hub run` in `TAU_HOME` as its own child; the menu shows `Hub: starting…`, then `Hub: up …` once `GET /health` answers (about a second) |
| The hub crashes or is killed (`kill -9`) | restarts it after 1 s; while it keeps failing the wait doubles up to 60 s, and goes back to 1 s after a run of a minute. The new hub reports the crash (`Last crash: unexpected exit (no clean shutdown)`) |
| `tau hub stop` (exit 0 without tau asking) | leaves it stopped; the switch shows off until you tick it again or tau starts again |
| You untick the switch | stops it (SIGTERM; SIGKILL after 15 s) |
| tau quits | stops the hub it started (SIGKILL after 10 s) |
| A hub tau did not start is running (by hand, launchd, or TauBar) | shows it (`started outside the app`, `run by launchd`) and never starts a second one; unticking the switch tells you how to stop it. With the switch ticked, tau starts its own hub as soon as that one is gone, unless a loaded `com.tau.hub` launchd agent owns the same data dir |
| tau itself crashed and is started again | takes over the hub it had started (its pid is in `state.json` and still holds the hub lock) |

How the hub is started comes from the settings window (**How tau starts the hub**):

| Field | Default |
|---|---|
| Python | none: a Python with tau-core, normally `<checkout>/.venv/bin/python` |
| `TAU_HOME` | none: the directory with `tau.toml`; also the working directory |
| `TAU_DATA_DIR` | empty: what `tau.toml` / `.env` say (`~/.local/share/tau`) |
| Control port (`TAU_HUB_PORT`) | empty: `[hub] control_port` (7877) |
| `PATH` | `/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin` |
| More environment | `KEY=value` lines; they win over `.env` |

**Use a tau checkout…** fills in the first two from a folder. On its first start tau takes
TauBar's settings over (see above), or copies Python, `TAU_HOME`, `TAU_DATA_DIR` and `PATH` from
an installed `com.tau.hub` launchd agent, so a Mac that ran the hub before needs no typing. The
hub inherits only `HOME`, `USER`, `LOGNAME`, `TMPDIR`, `SHELL` and the locale from tau; `.env` in
`TAU_HOME` is read by the hub itself, as always.

Before every start tau runs `tau hub status --json` to learn which lock and port the
configuration resolves to, and probes that lock. Hub output: `<TAU_DATA_DIR>/hub/logs/app.{out,err}.log`;
the hub's log: `<TAU_DATA_DIR>/logs/tau.log` (**Open Hub Log**); every start, exit and restart
also lands in tau's own log.

Moving from the launchd agent to tau:

```sh
cd /path/to/tau
uv run tau hub uninstall      # stops the launchd hub and removes the agent
```

Then tick **Run the hub** (with it already ticked, tau starts its hub once the launchd one is
gone). To go back: untick the switch, then `uv run tau hub install`.

## The owner guard

When the hub runs the owner guard ([ADR 0008](../../docs/adr/0008-owner-guard.md)), the panel,
the menu and the settings window show it under the hub lines, from the `guard` block of the
hub's open `/status` (`{state, enrolled, available, reason}`). The panel has a **Guard** row
(Flare when the guard cannot check) with **Lock now** and **Grant camera access…** under it;
the right-click menu shows the same as lines:

```text
├─ Guard: unavailable (camera denied)
├─   Lock now
├─   Grant camera access…
```

| Guard line (the panel's row shows the same without `Guard:`) | When |
|---|---|
| `Guard: locked` | guarded channels (`tau tui`, `tau chat`, the chat windows) refuse turns until the owner's face is checked at the Mac |
| `Guard: checking…` | a face check is running |
| `Guard: unlocked` | the owner was verified |
| `Guard: unavailable (camera denied)` | the guard cannot check; the reason says why |
| `Guard: locked (not enrolled)` | no face is enrolled yet (`tau guard setup`) |

The whole section is hidden when the hub reports no guard or the state `off`. It is also hidden
while tau cannot tell that the hub itself answers: `/status` is open and unsigned, so any local
process that binds the free port can answer it. tau shows the guard block only when its own hub
is up, or when the pid that answers `/health` holds the hub lock (checked once per pid); not
while its hub is still starting. The state must be one tau knows and the reason must look like
tau-core's (`a-z`, `0-9`, `_`, at most 48 characters); anything else is dropped. **Grant camera
access…** appears when the reason is `camera_denied` or `camera_unavailable` and opens System
Settings → Privacy & Security → Camera.

**Lock now** asks the hub to lock (`POST /guard/lock`, `{"channel": "app", "client_id": …,
"trigger": "command"}`). tau reads `<TAU_DATA_DIR>/hub/control.token` for every request and
never sends it: it signs the request with it (`X-Tau-Nonce`, `X-Tau-Auth`) and trusts the answer
only with a valid `X-Tau-Proof`, exactly as tau-core's `HubClient` does. After a 403 it reads
the token again once (the hub writes a new one on every start). A missing or wrong proof, a
redirect (never followed) or no answer means the hub is unavailable, and tau says that tau may
not be locked. tau never unlocks: that is a face check at the Mac.

**No webview gets the camera.** wry grants a page's `getUserMedia` by default, and tau holds the
camera grant, so every webview of the app denies every permission request: the app builder and
each window (the settings window, the panel, every chat window) install the same handler,
`src-tauri/src/webview.rs`. To check by hand: in `bun run tauri dev`, right-click the settings
window → Inspect Element → Console, and run
`await navigator.mediaDevices.getUserMedia({video: true})`; it rejects with `NotAllowedError`
and no camera turns on.

## Sleep modes

| Mode | What tau does | Check |
|---|---|---|
| Normal | nothing | no tau line in `pmset -g assertions` |
| Keep awake on AC power | holds an IOKit `PreventSystemSleep` assertion, like `caffeinate -s`; macOS honours it only on AC power, so on battery or with the lid closed the Mac still sleeps | `pmset -g assertions` shows `PreventSystemSleep 1` and `pid …(tau-app): … named: "tau keeps the Mac awake"` |
| Keep awake with the lid closed | the assertion plus `sudo -n pmset -a disablesleep 1` through a narrow sudoers rule | `pmset -g` shows `SleepDisabled 1` |

The choice is saved and applied again at the next start. **Quitting restores normal sleep:**
tau releases the assertion and, if it set it, runs `pmset -a disablesleep 0`. The same happens
on SIGTERM, SIGINT and SIGHUP (logout, `kill <pid>`, Ctrl-C in `bun run tauri dev`). A `kill -9`
cannot be caught: macOS drops the assertion with the process, and `disablesleep` stays until
tau's next start resets it (or `sudo pmset -a disablesleep 0`).

### The lid-closed mode

It needs one sudoers rule, and tau shows the mode as unavailable ("needs setup") until the rule
is there. tau never runs sudo to find out: it looks for the file `/etc/sudoers.d/tau-taubar`
(the name dates from TauBar, so a rule installed then keeps working), and it only calls
`sudo -n` (never a password prompt) after you pick the mode. Install the rule from the checkout,
in your own terminal:

```sh
apps/tau/sudoers/install-sudoers.sh --print   # show the rendered rule and check it with visudo
apps/tau/sudoers/install-sudoers.sh           # install it (sudo asks for your password)
```

The rule allows your user exactly two commands, with fixed arguments:

```text
<you> ALL=(root) NOPASSWD: /usr/bin/pmset -a disablesleep 0, /usr/bin/pmset -a disablesleep 1
```

The script renders [`sudoers/tau-taubar.sudoers`](sudoers/tau-taubar.sudoers) for `id -un`,
checks it with `visudo -c`, installs it as `/etc/sudoers.d/tau-taubar` (`root:wheel`, `0440`),
checks the whole sudoers configuration again (and removes the file if it does not parse), and
confirms with `sudo -n -l` that the command is allowed. tau notices the rule within five
seconds.

To remove it (this re-enables sleep first):

```sh
apps/tau/sudoers/uninstall-sudoers.sh
```

A closed MacBook that does not sleep still makes heat. Use this mode on AC power with the Mac in
the open air, not in a bag.

## Launch at login

The checkbox registers tau with `SMAppService.mainApp` (macOS 13+), the same list as System
Settings → General → Login Items → Open at Login; you can switch it off there too, and tau's
checkbox follows within a few seconds. tau does not use a LaunchAgent with `RunAtLoad`: on the
Mac it was built on, launchd pended every automatic spawn of user agents (roadmap issues 057
and 052), and `tauri-plugin-autostart` offers only a LaunchAgent or an AppleScript login item.

The registration points at the app where it is when you tick the box, so tau only turns it on
when it runs from `/Applications` or `~/Applications`; a copy anywhere else (the build folder of
a checkout, Downloads, the mounted `tau.dmg`) shows "Launch at login needs tau.app installed in
/Applications" instead. With **Run the hub** ticked, this is also how the hub starts at login.

## Files

| Path | What |
|---|---|
| `~/Library/Application Support/com.tau.app/settings.json` | your choices: `sleep_mode`, `run_hub`, `hub` (how the hub is started), `check_updates` |
| `~/Library/Application Support/com.tau.app/chat.json` | the folder chosen for the chat windows: `tau_home` |
| `~/Library/Application Support/com.tau.app/state.json` | what tau changed and must undo or take over: `lid_engaged`, `hub_pid` |
| `~/Library/Logs/com.tau.app/app.log` | tau's short log (rotated once at 256 KB) |
| `<TAU_DATA_DIR>/hub/logs/app.{out,err}.log` | the hub's stdout and stderr while tau runs it |

`TAU_APP_HOME=/some/dir` keeps everything in one directory instead (`settings.json`,
`chat.json`, `state.json`, `logs/app.log`), and takes nothing over from TauBar: for tests or a
second copy.

## Uninstall

1. Untick **Launch at login** (or remove tau in System Settings → Login Items).
2. Quit tau: it closes the chat windows, restores normal sleep and stops the hub it started. If
   the hub should keep running without tau, install the launchd agent: `uv run tau hub install`.
3. If you installed the sudoers rule: `apps/tau/sudoers/uninstall-sudoers.sh`.
4. Delete `/Applications/tau.app` and the files above.
5. Run `infra/remote/setup.sh` if the Mac should still stay awake on AC power without tau: it
   installs `com.tau.keepawake` again.

## Development

```sh
bun run test                       # vitest: the panel's and window's display and form logic; the chat windows' output coalescing, input order, terminal and key options
bun run build                      # tsc + vite
(cd src-tauri && cargo test)       # Rust: supervisor, restart policy, sleep modes, settings, the chat windows' PTYs and TAU_HOME, the migration, the bundle config
(cd src-tauri && cargo clippy --all-targets -- -D warnings)
```

To work on the settings window or the panel without the app, run `bun run dev` and open
http://localhost:1420/ (the settings window) or http://localhost:1420/#panel (the panel) in a
browser: outside Tauri a development build answers the commands from `src/devmock.ts`, a
stand-in with example values. No build contains it. A chat window (`#chat`) needs the app.

The supervisor tests run real `/bin/sh` children as stand-in hubs (crash, `kill -9`, clean exit,
a SIGTERM-deaf hub, a foreign lock holder, an orphan to adopt) against a fake probe, so they need
no tau checkout and never touch a real hub. The signing tests use the byte vectors tau-core pins,
and "Lock now" runs against a fake hub on a loopback port (a 403 and a token re-read, a missing
or wrong proof, a redirect). The PTY tests run `/bin/sh` scripts as stand-in TUIs in real PTYs:
raw bytes, split UTF-8, resizing, the ctrl+q quit, the process-group kill, and a reloaded page
taking over a running TUI.

| File | Job |
|---|---|
| `src-tauri/src/lib.rs` | app setup (menu bar first), menu actions, windows, quit and restart, ticker and hub threads |
| `src-tauri/src/app_menu.rs` | the macOS menu bar while a chat window is open (tau, File, Edit, Window) |
| `src-tauri/src/core.rs` | state shared by the panel, the menu and the settings window |
| `src-tauri/src/hub/supervisor.rs` | the hub supervisor (start, reap, restart, stop, adopt, never a second hub) |
| `src-tauri/src/hub/policy.rs` | which exits are restarted, and the backoff |
| `src-tauri/src/hub/probe.rs`, `launch.rs`, `display.rs` | lock/control API/launchd probes, the command and environment, the menu lines and panel rows |
| `src-tauri/src/hub/control.rs`, `guard.rs` | signed control requests (token, nonce, proof); the guard line and "Lock now" |
| `src-tauri/src/chat/mod.rs` | chat windows: open, close (ctrl+q, then a kill), the Dock icon while one is open |
| `src-tauri/src/chat/commands.rs` | the commands a chat window may call (its own PTY, the first-run choice, links) |
| `src-tauri/src/chat/home.rs`, `launch.rs` | finding and validating `TAU_HOME`; the TUI command and its environment |
| `src-tauri/src/chat/pty.rs`, `modes.rs` | one PTY session: raw output batching, input, resize, exit, shutdown, a new page taking over; the terminal modes replayed for it |
| `src-tauri/src/update.rs` | the Tauri updater: check, ask, install, restart |
| `src-tauri/src/migrate.rs` | the first start: TauBar's and tau Desktop's settings taken over |
| `src-tauri/src/webview.rs` | denies every webview permission request |
| `src-tauri/capabilities/` | what each window may call: `settings.json`, `panel.json`, `chat.json` (`chat-*`) |
| `src-tauri/Info.plist`, `Entitlements.plist` | usage descriptions and the camera/microphone entitlements (checked by `tests/bundle_config.rs`) |
| `src-tauri/src/sleep.rs` | the three modes behind a `Power` trait (a fake in tests) |
| `src-tauri/src/login.rs` | `SMAppService.mainApp` |
| `src-tauri/src/tray.rs` | the icon and the native menu (right click) |
| `src-tauri/src/panel.rs` | the panel's window: open under the icon, hide on focus loss, fit its height |
| `src-tauri/src/settings.rs`, `eventlog.rs`, `signals.rs`, `commands.rs` | settings files, tau's log, quit on signals, the commands the settings window and the panel call |
| `src/main.tsx` | which view a window shows: `#panel`, `#chat`, else the settings window |
| `src/Panel.tsx`, `src/panel.css`, `src/icons.tsx` | the panel |
| `src/App.tsx`, `src/styles.css` | the settings window |
| `src/api.ts`, `src/format.ts`, `src/devmock.ts` | the commands, display helpers, the browser stand-in |
| `src/chat/` | the chat window: `Chat.tsx`, `FirstRun.tsx`, `TerminalView.tsx`; output coalescing, ordered input, terminal options (`output.ts`, `input.ts`, `terminal.ts`, `api.ts`) |
| `scripts/make-signing-identity.sh`, `scripts/pack-release.sh` | the release signing material (once, by the owner); signing and packing a release (CI) |
| `sudoers/` | the lid-closed rule and its install/uninstall scripts |

How chat output travels: the Rust reader forwards raw PTY bytes and batches output that keeps
coming into at most one message per 8 ms. Each message crosses a `tauri::ipc::Channel` as bytes.
The page gathers them for another 8 ms and calls `term.write(Uint8Array)`. Nothing decodes text
on the way, so a character split between two reads reaches xterm.js's decoder whole. Input goes
the other way as raw bytes, one `pty_write` in flight at a time, so keys arrive in order.

The icons are generated from `docs/brand/tau-app-icon.svg` (`bun run tauri icon`); the menu bar
icon is `src-tauri/icons/tray-template.png`, and the chat window's mark is
`docs/brand/tau-mark.svg`, imported as is.

The UI is English only for now; tau's other UIs take their strings from the `tau_core.i18n`
table, which the app cannot read yet (roadmap 086).
