# TauBar (macOS menu bar)

TauBar is tau's menu bar app for the Mac hub: a **τ** in the menu bar, no Dock icon. It keeps
the Mac awake the way you choose and starts at login. The source and the full reference
(signing, files, development) are in
[`apps/taubar/README.md`](https://github.com/fport/tau/blob/main/apps/taubar/README.md).

## Build and install

You need macOS 13 or later, Rust (`rustup`), Node 20+ with pnpm, and the Xcode command line
tools.

```sh
cd apps/taubar
pnpm install
pnpm tauri build
cp -R src-tauri/target/release/bundle/macos/TauBar.app /Applications/
open -a TauBar
```

The build is signed ad hoc, which is enough for the Mac that built it. The first start opens
TauBar's window; after that it lives in the menu bar.

!!! note "No τ in the menu bar?"
    On a MacBook with a notch, macOS hides menu bar icons that do not fit next to the notch, and
    the newest go first. Open TauBar again (Spotlight, Finder or `open -a TauBar`): its window
    appears with every switch and a Quit button. Make room by quitting other menu bar apps or
    switching some off under **System Settings → Menu Bar → Allow in the Menu Bar**.

Then tick **Launch at login** and run `infra/remote/setup.sh` once: with TauBar in
`/Applications` it removes the `com.tau.keepawake` agent from the
[remote access setup](phone-tailscale-termius.md), because TauBar does the same job.
`infra/remote/doctor.sh` accepts either.

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

The **Launch at login** checkbox registers TauBar through `SMAppService` (System Settings →
General → Login Items → Open at Login), not through a launchd agent: on some Macs launchd pends
the automatic start of user agents indefinitely.
Install TauBar in `/Applications` before ticking it, since the login item points at the app's
current location.
