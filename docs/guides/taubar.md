# The tau app (macOS)

tau's Mac app, called **tau**: a **τ** in the menu bar, the supervisor of the hub (the service tau
runs on this Mac), and chat windows that run `tau tui`. It keeps the Mac awake the way you
choose, starts at login and updates itself. It replaced two earlier apps, TauBar (the menu bar
app this page used to describe) and tau Desktop (the chat windows), so that one app holds the
permissions ([ADR 0014](https://github.com/fport/tau/blob/main/docs/adr/0014-one-installer-and-onboarding.md)).
The source and the full reference (signing, releases, files, development) are in
[`apps/tau/README.md`](https://github.com/fport/tau/blob/main/apps/tau/README.md).

A left click on the τ opens the panel below; the right click shows the same items as a plain
menu. The panel follows light and dark mode and closes when you click elsewhere or press Esc.

```text
Hub                                      [ on]
(τ)  Up 2 h 5 min
     pid 1234 · started by the app
(➤)  Telegram
     polling as @your_bot
(!)  Last crash
     none
(▣)  Guard                (only when the hub runs the owner guard)
     unlocked
     Lock now
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

## Install

### From a release

1. Download `tau.dmg` from the [latest release](https://github.com/fport/tau/releases/latest),
   open it and drag **tau** to **Applications**.
2. Open tau. The first time, macOS says it cannot check tau for malicious software: the app is
   signed, but not notarised by Apple. Open **System Settings → Privacy & Security**, find the
   line about tau near the bottom and click **Open Anyway**, then confirm. On macOS 14 and
   earlier, right-click tau.app → **Open** does the same. This happens once per install, not
   after updates.
3. tau opens its settings window. Under **How tau starts the hub**, pick your tau checkout
   (**Use a tau checkout…**), then tick **Run the hub** and **Launch at login**.

### From the checkout

You need macOS 13 or later, Rust (`rustup`), [Bun](https://bun.sh), and the Xcode command line
tools.

```sh
cd apps/tau
bun install
bun run tauri build
cp -R src-tauri/target/release/bundle/macos/tau.app /Applications/
open -a tau
```

This build is signed ad hoc, which is enough for the Mac that built it. The first start opens
tau's settings window; after that it lives in the menu bar.

!!! note "No τ in the menu bar?"
    On a MacBook with a notch, macOS hides menu bar icons that do not fit next to the notch, and
    the newest go first. Open tau again (Spotlight, Finder or `open -a tau`): a window appears,
    and while a chat window is open the menu bar has tau's own menu with **Settings…** and
    **Quit tau**. Only one tau ever runs: a second launch hands over to the running one and
    exits. Make room by quitting other menu bar apps or switching some off under **System
    Settings → Menu Bar → Allow in the Menu Bar**. A menu bar manager such as Hidden Bar hides
    everything left of its separator: expand it and Cmd-drag the τ to the right of the separator.

Then switch on **Launch at login** and run `infra/remote/setup.sh` once: with tau in
`/Applications` it removes the `com.tau.keepawake` agent from the
[remote access setup](phone-tailscale-termius.md), because tau does the same job.
`infra/remote/doctor.sh` accepts either.

### Coming from TauBar or tau Desktop

tau has its own bundle id (`com.tau.app`), so it does not replace the old apps by itself:

1. Quit TauBar (**Quit TauBar** stops the hub it runs) and tau Desktop.
2. Remove TauBar from System Settings → General → Login Items, and delete `TauBar.app` and
   `tau Desktop.app` from Applications.
3. Open tau. Its first start takes TauBar's settings (sleep mode, **Run the hub**, how the hub is
   started) and tau Desktop's folder over, without changing the old files.
4. Tick **Launch at login** again.
5. macOS asks for the camera once more, now for tau: a permission belongs to one app, and tau is
   a new one.

## First launch

The tau app, which TauBar and tau Desktop became ([ADR 0014](../adr/0014-one-installer-and-onboarding.md)),
opens a **setup wizard** on its first start. **Set up tau…** in its menu, its panel, its settings
window and an empty chat window opens it again, to add or remove features later. It drives the
same engine as `tau setup` in a terminal, through its [JSON protocol](../reference/setup.md#the-json-protocol),
so both ways end with the same tau. The steps are on the left, and every step can be skipped.

1. **Language:** English or Turkish, for the wizard and everything tau says in it.
2. **Install tau:** the wizard looks for tau first: the app's hub settings, a checkout's
   `.venv`, a `uv tool install tau-core` (`uv tool dir`, `UV_TOOL_DIR`, `~/.local/share/uv/tools`)
   or a `tau` command, and points the hub and the chat windows at what it finds. Without tau it
   installs it with [uv](https://docs.astral.sh/uv/) (`uv tool install tau-core --with tau-tui`)
   in your home folder; without uv it says so, then downloads and runs Astral's official
   installer, the way the [one-line installer](../reference/setup.md#the-installer) does. Nothing
   asks for an administrator password.
3. **Model key:** choose the provider and paste the key into a hidden field. tau checks it with
   one small request and keeps it in `.env`, which only you can read; a refused key is shown
   there and nothing is written. No key yet? The scripted `fake` provider lets you look around.
4. **About you** (optional): your name, how tau should address you, your languages.
5. **Features:** what tau should do on this Mac, with what is on already and why a feature is
   missing. The app installs the packages of the ones you choose.
6. **Permissions:** only those your features need, each with one sentence of why: the camera
   for the owner guard, notifications for the app. **Allow…** shows macOS's own question, in
   tau's name; the app never grants anything itself, and **Open System Settings** changes an
   earlier answer.
7. **Feature steps:** each feature's steps, live. The guard's enrollment runs in the wizard's
   own terminal, so macOS asks for the camera for tau. Telegram asks for the bot token and shows
   the code to send your bot, with its link. The spine opens Cloudflare's token page and takes
   the token. Remote access shows its checks, and the one command only you run in Terminal
   (with `sudo`, it asks for your password there): copy it, run it, then **Done, check again**.
   The app never runs it. Start at login means the app runs the hub and opens at login.
8. **Summary:** what is on, `tau doctor`'s checks, **Open a chat window** and **Start the hub**.
## Chat windows

**New Chat Window** (⌘N, in the panel, the menu and the settings window) opens a window that
runs the real `tau tui`, so everything the TUI does works there, the owner guard's lock screen
included. While a chat window is open, tau has a Dock icon and its own menu bar; closing the
last one takes it back to the menu bar only.

A chat window runs the checkout's own `.venv/bin/python -m tau_core tui`. It takes the checkout
from `TAU_HOME` when tau was opened with it, else from the folder chosen earlier; the first time
it offers the hub's checkout (**Use This Folder**) or a folder picker, and checks the folder with
`python -m tau_core version` before using it. Keep `TAU_DATA_DIR` and the hub port in the
checkout's `.env` and `tau.toml`, where the hub and the TUI both read them.

Keys: ⌘N a new window, ⌘W closes one (the TUI quits the way ctrl+q quits it), ⌘C/⌘V copy and
paste, Option-drag selects text, ⌘-click opens a link. Every other key, ctrl and Option
included, goes to the TUI. ⌘Q quits tau and, while tau runs the hub, asks first, because the hub
stops with it; to keep tau running, close the chat windows instead.

## Run the hub

Switch on **Run the hub** and tau becomes the hub's supervisor on this Mac, the macOS default (a
launchd agent is the [alternative](hub-service.md#macos-alternative-launchd-user-agent)):

- it starts `tau hub run` as its own child and shows `Hub: up …` once the control API answers;
- a crash or a `kill -9` is restarted after a second (longer waits while it keeps failing), and
  the new hub reports the crash;
- `tau hub stop` leaves the hub stopped; switching it off stops it; quitting tau stops the hub
  it started;
- it never starts a second hub: a hub started by hand, by launchd or by TauBar is shown
  (`started outside the app`, `run by launchd`) and left alone.

tau needs the Python with tau-core and `TAU_HOME`. It takes them over from TauBar, or from an
installed `com.tau.hub` launchd agent, on its first start; otherwise open its settings window,
**How tau starts the hub** → **Use a tau checkout…**. To hand the hub over from launchd, run
`uv run tau hub uninstall` in the checkout and switch on **Run the hub**. Details, including the
data dir, port and environment fields: [Run tau as a service](hub-service.md#macos-taubar-default).

## Owner guard and the camera

When the hub runs the owner guard ([ADR 0008](https://github.com/fport/tau/blob/main/docs/adr/0008-owner-guard.md)),
the panel shows a **Guard** row (`locked`, `unlocked`, `unavailable (camera denied)`) and the
right-click menu a guard line (`Guard: locked`), both with **Lock now**, which asks the hub to
lock with a signed request; tau never unlocks. Both are hidden without a guard. Setting the guard
up, daily use and the "locked out" steps are in the [Owner guard](guard.md) guide.

The hub is tau's child, so macOS asks for the camera in tau's name ("tau would like to access
the camera"); tau carries the usage descriptions and the camera and microphone entitlements for
that. A chat window's `tau tui` is tau's child too, so `tau guard setup` in a chat window uses
tau's permission. When the hub reports the camera as denied, **Grant camera access…** opens
System Settings → Privacy & Security → Camera. No window's page can use the camera or the
microphone itself: every webview permission request is denied.

The permission stays across updates because every release is signed with the same certificate.
macOS keeps a permission for an app's *designated requirement*, the rule in its signature that
says which code is "this app"; with one certificate that rule names the certificate, not the
build, and every update satisfies it. A build from the checkout is signed ad hoc, so each rebuild
is a new app to macOS and asks again; the
[README](https://github.com/fport/tau/blob/main/apps/tau/README.md#why-a-stable-identity-keeps-the-camera-permission)
explains the signing and how to use the release identity for your own builds. To make macOS ask
again, run `tccutil reset Camera com.tau.app` and restart the hub from tau (untick and tick
**Run the hub**).

## Sleep modes

| Mode | Effect |
|---|---|
| Normal | The Mac sleeps as usual. |
| **Keep awake on AC power** (default) | No system sleep while plugged in, like `caffeinate -s`: an IOKit `PreventSystemSleep` assertion, no root needed. On battery or with the lid closed the Mac still sleeps. |
| Keep awake with the lid closed | Also stays awake with the lid closed (`pmset -a disablesleep 1`). Needs a one-time sudoers rule. |

The choice survives restarts. Check it with `pmset -g assertions` (a line
`… (tau-app): … PreventSystemSleep named: "tau keeps the Mac awake"`) and, for the lid-closed
mode, `pmset -g` (`SleepDisabled 1`). **Quitting tau restores normal sleep.**

### Set up the lid-closed mode

The mode shows "needs setup" until one sudoers rule exists that allows your user exactly
`/usr/bin/pmset -a disablesleep 0` and `… 1`, nothing else. From the checkout, in your own
terminal:

```sh
apps/tau/sudoers/install-sudoers.sh --print   # show and check the rule, install nothing
apps/tau/sudoers/install-sudoers.sh           # install it (sudo asks for your password)
```

tau picks it up within five seconds. A rule installed for TauBar keeps working. To remove it
again (this re-enables sleep first):

```sh
apps/tau/sudoers/uninstall-sudoers.sh
```

A closed MacBook that does not sleep still makes heat: use this mode on AC power, in the open
air.

## Launch at login

The **Launch at login** switch registers tau through `SMAppService` (System Settings → General →
Login Items → Open at Login), not through a launchd agent: on some Macs launchd pends the
automatic start of user agents indefinitely (see
[Run tau as a service](hub-service.md#macos-taubar-default)). The login item points at the app's
current location, so tau turns it on only when it runs from `/Applications` (or
`~/Applications`) and otherwise says so. With **Run the hub** on, this is also how the hub starts
at login.

## Updates

A release build asks GitHub for tau's latest release a minute after it starts and then once a
day, and offers a newer version; nothing is installed without your click. **Check for Updates…**
asks at once. Installing replaces the app and opens it again: the chat windows close and the hub
restarts with the new version. The update is checked against tau's own signing key before it is
installed. **Look for an update once a day** in the settings window switches the daily check
off; a check sends GitHub nothing but the usual request.
