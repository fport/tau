# TauBar

tau's macOS menu bar app: Tauri v2 with a Rust core and a small React/TypeScript window. Tray
only, no Dock icon.

What it does today:

- **Runs the hub:** with "Run the hub" ticked, TauBar starts `tau hub run`, restarts it after a
  crash, leaves it stopped after `tau hub stop`, stops it when TauBar quits, and never starts a
  second hub. The menu shows whether the hub is up, its Telegram poller and its last crash.
- **Sleep modes:** Normal, Keep awake on AC power (default), Keep awake with the lid closed.
- **Launch at login:** a checkbox that registers TauBar as a login item.
- A **window** (Settings…) with the same switches, the hub's settings and TauBar's own log.

The status panel, approvals and voice come with later roadmap issues (025, 031).

```text
τ
├─ Hub: up 2 h 5 min · pid 1234
├─ Telegram: polling as @your_bot
├─ Last crash: none
├─ ✓ Run the hub
├─   Open Hub Log
├─ ──────────
├─ Sleep: kept awake on AC power
├─   Normal
├─ ✓ Keep awake on AC power
├─   Keep awake with the lid closed (needs setup)
├─ ──────────
├─ ✓ Launch at login
├─   Settings…                              ⌘,
├─   Open TauBar Log
├─ ──────────
└─   Quit TauBar                            ⌘Q
```

## Build

Needs macOS 13 or later, Rust (`rustup`), Node 20+ with pnpm, and the Xcode command line tools.

```sh
cd apps/taubar
pnpm install
pnpm tauri build          # → src-tauri/target/release/bundle/macos/TauBar.app
```

`pnpm tauri dev` runs it with hot reload for development. Launch at login needs the built
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
`APPLE_PASSWORD`, `APPLE_TEAM_ID` for notarization) before `pnpm tauri build`; see Tauri's
[macOS code signing](https://v2.tauri.app/distribute/sign/macos/) guide.

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

## Sleep modes

| Mode | What TauBar does | Check |
|---|---|---|
| Normal | nothing | no TauBar line in `pmset -g assertions` |
| Keep awake on AC power | holds an IOKit `PreventSystemSleep` assertion, like `caffeinate -s`; macOS honours it only on AC power, so on battery or with the lid closed the Mac still sleeps | `pmset -g assertions` shows `PreventSystemSleep 1` and `pid …(taubar): … named: "TauBar keeps the Mac awake for tau"` |
| Keep awake with the lid closed | the assertion plus `sudo -n pmset -a disablesleep 1` through a narrow sudoers rule | `pmset -g` shows `SleepDisabled 1` |

The choice is saved and applied again at the next start. **Quitting restores normal sleep:**
TauBar releases the assertion and, if it set it, runs `pmset -a disablesleep 0`. The same
happens on SIGTERM, SIGINT and SIGHUP (logout, `kill <pid>`, Ctrl-C in `pnpm tauri dev`). A
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
pnpm test                          # vitest: the window's display and form logic
pnpm build                         # tsc + vite
(cd src-tauri && cargo test)       # Rust: supervisor, restart policy, sleep modes, settings, …
```

The supervisor tests run real `/bin/sh` children as stand-in hubs (crash, `kill -9`, clean
exit, a SIGTERM-deaf hub, a foreign lock holder, an orphan to adopt) against a fake probe, so
they need no tau checkout and never touch a real hub.

| File | Job |
|---|---|
| `src-tauri/src/lib.rs` | app setup (tray only), menu actions, window, ticker and hub threads |
| `src-tauri/src/core.rs` | state shared by the menu and the window |
| `src-tauri/src/hub/supervisor.rs` | the hub supervisor (start, reap, restart, stop, adopt, never a second hub) |
| `src-tauri/src/hub/policy.rs` | which exits are restarted, and the backoff |
| `src-tauri/src/hub/probe.rs`, `launch.rs`, `display.rs` | lock/control API/launchd probes, the command and environment, the menu lines |
| `src-tauri/src/sleep.rs` | the three modes behind a `Power` trait (a fake in tests) |
| `src-tauri/src/login.rs` | `SMAppService.mainApp` |
| `src-tauri/src/tray.rs` | the native menu |
| `src-tauri/src/settings.rs`, `eventlog.rs`, `signals.rs`, `commands.rs` | settings files, TauBar's log, quit on signals, window commands |
| `src/App.tsx`, `src/api.ts`, `src/format.ts` | the window |
| `sudoers/` | the lid-closed rule and its install/uninstall scripts |

The UI is English only for now; tau's other UIs take their strings from the `tau_core.i18n`
table, which TauBar cannot read yet.
