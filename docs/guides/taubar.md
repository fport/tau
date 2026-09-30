# TauBar (macOS menu bar)

TauBar is tau's menu bar app for the Mac hub: a **τ** in the menu bar, no Dock icon. It runs
and supervises the hub, keeps the Mac awake the way you choose and starts at login. The source
and the full reference (signing, files, development) are in
[`apps/taubar/README.md`](https://github.com/fport/tau/blob/main/apps/taubar/README.md).

A left click on the τ opens the panel below; the right click shows the same items as a plain
menu. The panel follows light and dark mode and closes when you click elsewhere or press Esc.

```text
Hub                                      [ on]
(τ)  Up 2 h 5 min
     pid 1234 · started by TauBar
(➤)  Telegram
     polling as @your_bot
(!)  Last crash
     none
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

## Build and install

You need macOS 13 or later, Rust (`rustup`), [Bun](https://bun.sh), and the Xcode command line
tools.

```sh
cd apps/taubar
bun install
bun run tauri build
cp -R src-tauri/target/release/bundle/macos/TauBar.app /Applications/
open -a TauBar
```

The build is signed ad hoc, which is enough for the Mac that built it. The first start opens
TauBar's window; after that it lives in the menu bar.

!!! note "No τ in the menu bar?"
    On a MacBook with a notch, macOS hides menu bar icons that do not fit next to the notch, and
    the newest go first. Open TauBar again (Spotlight, Finder or `open -a TauBar`): its window
    appears with every switch and a Quit button. Only one TauBar ever runs: a second launch
    hands over to the running one and exits. Make room by quitting other menu bar apps or
    switching some off under **System Settings → Menu Bar → Allow in the Menu Bar**.
    A menu bar manager such as Hidden Bar hides everything left of its separator: expand it and
    Cmd-drag the τ to the right of the separator.

Then switch on **Launch at login** and run `infra/remote/setup.sh` once: with TauBar in
`/Applications` it removes the `com.tau.keepawake` agent from the
[remote access setup](phone-tailscale-termius.md), because TauBar does the same job.
`infra/remote/doctor.sh` accepts either.

## Run the hub

Switch on **Run the hub** and TauBar becomes the hub's supervisor on this Mac, the macOS default (a
launchd agent is the [alternative](hub-service.md#macos-alternative-launchd-user-agent)):

- it starts `tau hub run` as its own child and shows `Hub: up …` once the control API answers;
- a crash or a `kill -9` is restarted after a second (longer waits while it keeps failing), and
  the new hub reports the crash;
- `tau hub stop` leaves the hub stopped; switching it off stops it; quitting TauBar stops
  the hub it started;
- it never starts a second hub: a hub started by hand or by launchd is shown
  (`started outside TauBar`, `run by launchd`) and left alone.

TauBar needs the Python with tau-core and `TAU_HOME`. It copies them from an installed
`com.tau.hub` launchd agent on its first start; otherwise open its window, **How TauBar starts
the hub** → **Use a tau checkout…**. To hand the hub over from launchd, run
`uv run tau hub uninstall` in the checkout and switch on **Run the hub**. Details, including the data
dir, port and environment fields: [Run tau as a service](hub-service.md#macos-taubar-default).

## Sleep modes

| Mode | Effect |
|---|---|
| Normal | The Mac sleeps as usual. |
| **Keep awake on AC power** (default) | No system sleep while plugged in, like `caffeinate -s`: an IOKit `PreventSystemSleep` assertion, no root needed. On battery or with the lid closed the Mac still sleeps. |
| Keep awake with the lid closed | Also stays awake with the lid closed (`pmset -a disablesleep 1`). Needs a one-time sudoers rule. |

The choice survives restarts. Check it with `pmset -g assertions` (a line
`… (taubar): … PreventSystemSleep named: "TauBar keeps the Mac awake for tau"`) and, for the
lid-closed mode, `pmset -g` (`SleepDisabled 1`). **Quitting TauBar restores normal sleep.**

### Set up the lid-closed mode

The mode shows "needs setup" until one sudoers rule exists that allows your user exactly
`/usr/bin/pmset -a disablesleep 0` and `… 1`, nothing else. From the checkout, in your own
terminal:

```sh
apps/taubar/sudoers/install-sudoers.sh --print   # show and check the rule, install nothing
apps/taubar/sudoers/install-sudoers.sh           # install it (sudo asks for your password)
```

TauBar picks it up within five seconds. To remove it again (this re-enables sleep first):

```sh
apps/taubar/sudoers/uninstall-sudoers.sh
```

A closed MacBook that does not sleep still makes heat: use this mode on AC power, in the open
air.

## Launch at login

The **Launch at login** switch registers TauBar through `SMAppService` (System Settings →
General → Login Items → Open at Login), not through a launchd agent: on some Macs launchd pends
the automatic start of user agents indefinitely (see
[Run tau as a service](hub-service.md#macos-taubar-default)). The login item points at the app's
current location, so TauBar turns it on only when it runs from `/Applications` (or
`~/Applications`) and otherwise says so. With **Run the hub** on, this is also how the hub
starts at login.
