# Run tau as a service

`tau hub run` runs tau as a long-lived process in the **hub** role. It holds the single-instance lock, refreshes a heartbeat, serves a small control API on loopback, and starts every enabled hub service (Telegram, voice and the mesh will all be hub services). Under a supervisor it comes back after a crash and stays down after a clean stop: on macOS that is [TauBar](taubar.md) (the default) or a launchd agent, on Linux a systemd user unit.

Today the hub carries no channel of its own: `tau chat` and `tau tui` build their agent in-process and work with or without a running hub. Install the service now if you want the plumbing in place, the crash reports, and the `/status` line that says the hub is up; the hub services that need it arrive with the next layers.

## Foreground

```sh
tau hub run
```

```text
tau hub is running (pid 12345, profile home). Control API: http://127.0.0.1:7877
To stop: Ctrl-C or `tau hub stop`
```

- Only one hub runs per machine. A second `tau hub run` exits 1 with `tau hub is already running (pid N)…`.
- Every `[hub] heartbeat_seconds` (default 5) it refreshes `<TAU_DATA_DIR>/hub/state.json`.
- SIGTERM or SIGINT stops it cleanly and writes `stopped_at`.
- A start that finds a `state.json` without `stopped_at` records a crash report and prints `The previous hub did not stop cleanly: …`.

## Status and stop

```sh
tau hub status
tau hub status --json
tau hub stop
tau hub stop --timeout 30
```

`tau hub status` with nothing running:

```text
tau hub is not running.
  Last crash: none
  launchd: not installed (to install: tau hub install)
```

Running, it shows the pid, uptime, heartbeat age, version, role, profile, the last crash and the launchd state. `--json` also carries what the configuration resolves to (`control_port`, `data_dir`, `hub_dir`, `lock`), which is how TauBar finds the lock and the control API of the hub it runs. `tau hub stop` sends SIGTERM and waits up to `--timeout` seconds (default 15); it is the clean stop that launchd and systemd do **not** treat as a crash.

## The control API

The hub listens on `127.0.0.1:<control_port>` only (default 7877; `TAU_HUB_PORT` overrides) and speaks JSON:

| Route | Answer |
|---|---|
| `GET /health` | `{"ok": true, "pid": …, "uptime_s": …}` |
| `GET /status` | role, profile, version, `started_at`, `heartbeat_at`, `uptime_s`, `last_crash`, `approvals_pending`, `nodes`, plus keys that hub services add |

A request with a non-loopback `Host` header gets 403, so the API cannot be reached through a tunnel or a proxy by accident. `tau doctor` and `/status` in a session probe `/health` with a one-second timeout, for information only.

```sh
curl -s 127.0.0.1:7877/health
```

## macOS: TauBar (default)

[TauBar](taubar.md), tau's menu bar app, runs the hub itself. Tick **Run the hub** in its menu (or its window) and TauBar:

- starts `<python> -m tau_core hub run` as its own child, in `TAU_HOME`, with `TAU_HOME`, `TAU_ROLE=hub`, a plain `PATH` and whatever else its settings add (`TAU_DATA_DIR`, `TAU_HUB_PORT`, more environment);
- restarts it after an unclean exit (a crash, a `kill -9`, a failed start) after 1 s, then 2, 4 … up to 60 s while it keeps failing, back to 1 s once a run lasted a minute;
- leaves it stopped after a clean exit it did not ask for (`tau hub stop`): the switch shows off until you tick it again or TauBar starts again, like launchd's agent at the next login;
- stops it with SIGTERM when you untick the switch or quit TauBar (SIGKILL if it has not stopped after 15 s, or 10 s while TauBar quits);
- never starts a second hub. Before every start it probes the hub lock of the data dir `tau hub status --json` resolves to. A hub it did not start is shown in the menu (`started outside TauBar` or `run by launchd`) and left alone; unticking the switch then tells you how to stop it. While a loaded `com.tau.hub` launchd agent owns the same data dir, TauBar leaves the hub to launchd.

The menu shows three lines from the control API: `Hub: up 2 h 5 min · pid 1234`, the Telegram poller (`Telegram: polling as @your_bot`) and the last crash. **Launch at login** starts TauBar, and with it the hub, when you log in.

TauBar needs to know which Python and which `TAU_HOME` to use. On its first start it copies them from an installed `com.tau.hub` launchd agent; otherwise pick the checkout in its window (**Use a tau checkout…** fills in `<checkout>/.venv/bin/python` and the checkout as `TAU_HOME`). The hub's stdout and stderr go to `<TAU_DATA_DIR>/hub/logs/taubar.{out,err}.log`, its log to `<TAU_DATA_DIR>/logs/tau.log` as always (menu → **Open Hub Log**), and TauBar's own log records every start, exit and restart.

To move from the launchd agent to TauBar:

```sh
cd /path/to/tau
uv run tau hub uninstall     # the launchd hub stops; TauBar may now run it
```

then tick **Run the hub**. (With the switch already on, TauBar starts its own hub as soon as the launchd hub is gone.)

Why TauBar and not launchd by default: on the Mac this was built on (macOS 26.3.1), launchd pended every automatic start of user agents in the login session: `RunAtLoad`, `KeepAlive` after a `kill -9` and even `StartInterval` never fired, only `launchctl kickstart` did (roadmap issues 057 and 052). A supervisor inside an app you can see does not depend on that.

## macOS alternative: launchd user agent

Use this when TauBar is not an option (no GUI app wanted, or a Mac where launchd's automatic starts work). Check after installing that the hub really runs (`tau hub status`); on some Macs launchd loads the agent but never starts it (see above), and `launchctl kickstart gui/$UID/com.tau.hub` starts it by hand.

Run from a Terminal of the logged-in user. The `gui/<uid>` launchd domain needs a GUI login session, so an SSH session without one cannot bootstrap it.

```sh
cd /path/to/tau
uv run tau hub install
uv run tau hub status
```

```text
launchd agent installed: ~/Library/LaunchAgents/com.tau.hub.plist
  The hub starts at login; after a crash or a kill it is restarted within a few
  seconds. It is not restarted after a clean stop (tau hub stop).
  launchd logs: ~/.local/share/tau/hub/logs
  For the status: tau hub status
```

What `tau hub install` does:

- renders the plist from the package template with the **absolute paths of this machine**: the virtual environment's Python, `TAU_HOME`, `TAU_DATA_DIR`, `TAU_ROLE=hub` and a plain `PATH`;
- creates the log directory;
- boots out a loaded agent, if any, and bootstraps the fresh plist (`launchctl bootstrap gui/$UID`), so it is idempotent.

The plist sets `RunAtLoad` (start at install and at every login), `KeepAlive = {SuccessfulExit: false}` and `ThrottleInterval 3`: a crash or a `kill -9` brings the hub back within about three seconds; `tau hub stop` keeps it stopped.

```sh
tau hub stop                                    # stop without a relaunch
launchctl kickstart gui/$UID/com.tau.hub        # start it again (or: tau hub install)
tau hub uninstall                               # launchctl bootout + delete the plist
```

Logs: stdout and stderr in `<TAU_DATA_DIR>/hub/logs/launchd.{out,err}.log`, details in `<TAU_DATA_DIR>/logs/tau.log`.

!!! warning "After moving the checkout or recreating `.venv`"
    The plist points at the venv's Python by absolute path. Run `tau hub install` again after moving the repository, recreating the virtual environment or upgrading Python, or launchd will fail to start the hub.

Check the self-heal once by hand (the same check works for TauBar):

```sh
curl -s 127.0.0.1:7877/health                  # note the pid
kill -9 <pid>
sleep 5; tau hub status        # a new pid, and "Last crash: … unexpected exit (no clean shutdown)"
```

!!! warning "Not `pkill -f`"
    `pkill -9 -f "tau_core hub run"` kills **every** hub on the machine, including one you run for tests with another `TAU_DATA_DIR`. Kill the pid that `/health` or `tau hub status` reports.

## Linux: systemd user unit

`tau hub systemd-unit` prints a unit rendered with this machine's paths; `--python PATH` picks another interpreter.

```sh
cd /path/to/tau
mkdir -p ~/.config/systemd/user
uv run tau hub systemd-unit > ~/.config/systemd/user/tau-hub.service
systemctl --user daemon-reload
systemctl --user enable --now tau-hub
loginctl enable-linger "$USER"   # start at boot, without a login session
```

`Restart=on-failure` with `RestartSec=3` mirrors launchd: restart after a crash or kill, no restart after `tau hub stop` or `systemctl --user stop tau-hub`. Logs go to the journal (`journalctl --user -u tau-hub -f`) and to `<TAU_DATA_DIR>/logs/tau.log`.

The rendered example files, kept identical to the package templates by a test, are in [`infra/services/`](https://github.com/fport/tau/tree/main/infra/services). Do not copy them by hand; the placeholders (`/path/to/venv/bin/python`, `/path/to/tau`, `/path/to/tau-data`) are what the commands above replace.

## Hub files

Everything the hub keeps is under `<TAU_DATA_DIR>/hub/`:

| File | Meaning |
|---|---|
| `hub.lock` | `flock` single-instance lock; holds the running hub's pid; never deleted |
| `state.json` | pid, `started_at`, `heartbeat_at`, version, role, profile, `last_crash`, `stopped_at` |
| `crash.json` | the reason a failing hub wrote on its way down; consumed by the next start |
| `crash_reports.jsonl` | every crash the next start noticed, oldest first |
| `last_crash.json` | the most recent crash report (`tau hub status` and `/status` show it) |
| `logs/` | the supervisor's capture of stdout and stderr: `launchd.{out,err}.log` or `taubar.{out,err}.log` |

## Hub services

A hub service is a component with a `name`, `async start(hub)` and `async stop()`, shipped through the `tau.hub_services` entry point group. `tau hub run` starts the control API first and then every enabled service in order; they stop in reverse. A service that fails to build or start is logged and skipped; the hub runs on. `[components.hub] services` in `tau.toml` picks which discovered services are on (empty means all). See [Components and plugins](../reference/components.md) and, to write one, [Write a plugin](../contributing/plugins.md).

## Keeping the machine awake

A hub that sleeps is a hub that does not think. On a MacBook, [TauBar](taubar.md) keeps the Mac awake on AC power (the default) or even with the lid closed, and restores normal sleep when it quits. Without TauBar, the remote-access setup installs `com.tau.keepawake`, a launch agent running `caffeinate -s` so the Mac stays awake while on AC power; the lid then has to stay open (or an external display attached). On a Raspberry Pi the question does not arise, which is one reason the Pi is the natural long-term hub; see [Move the hub to a Raspberry Pi](raspberry-pi.md).
