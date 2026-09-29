# infra/services

Service definitions for running `tau hub` as a long-lived process: a launchd user agent on
macOS (the hub today) and a systemd user unit for the future RPi5 hub.

**On macOS the default is [TauBar](../../apps/taubar/README.md), not launchd.** Its "Run the
hub" switch starts `tau hub run` as TauBar's own child with the same command and environment as
the plist below, restarts it after a crash or `kill -9`, leaves it stopped after `tau hub stop`,
stops it when TauBar quits, and never starts a second hub next to one that is already running.
TauBar was made the default because on the Mac it was built on (macOS 26.3.1) launchd pended every
automatic start of user agents in the login session: neither `RunAtLoad` nor `KeepAlive` brought
the hub up or back, only `launchctl kickstart` did (roadmap 057, 052). The launchd agent below is
the alternative for a Mac without TauBar; after installing it, check that the hub really runs.
To switch from the agent to TauBar: `uv run tau hub uninstall`, then tick "Run the hub".

The two files here are **examples**: the package templates in
`packages/tau-core/src/tau_core/hub/templates/` rendered with placeholder paths
(`/path/to/venv/bin/python`, `/path/to/tau`, `/path/to/tau-data`). A test keeps them identical to
the templates. Don't copy them by hand; the commands below render them with the real absolute
paths of the machine they run on.

| File | Rendered by | Installed to |
|---|---|---|
| `com.tau.hub.plist` | `tau hub install` | `~/Library/LaunchAgents/com.tau.hub.plist` |
| `tau-hub.service` | `tau hub systemd-unit` | `~/.config/systemd/user/tau-hub.service` |

Both run `<venv python> -m tau_core hub run` with `TAU_HOME`, `TAU_DATA_DIR`, `TAU_ROLE=hub` and
`PATH` set, and both restart the hub only when it did **not** stop cleanly: a crash or a
`kill -9` brings it back within about three seconds, while `tau hub stop` (SIGTERM, exit 0) keeps
it stopped.

## macOS alternative: launchd user agent

Run from the checkout, in a Terminal of the logged-in user (the `gui/<uid>` domain needs a GUI
login session, so an SSH session without one cannot bootstrap it):

```sh
cd /path/to/tau
uv run tau hub install      # render the plist, create the log dir, launchctl bootstrap gui/$UID
uv run tau hub status       # running, heartbeat, last crash, "launchd: installed and loaded"
```

- `RunAtLoad`: the hub starts at install and at every login.
- `KeepAlive = {SuccessfulExit: false}` and `ThrottleInterval 3`: launchd relaunches the hub after
  a crash or kill; the new hub records a crash report that `tau hub status` shows.
- `tau hub stop` stops it without a relaunch. Start it again with `tau hub install` (idempotent:
  it boots out a loaded agent and bootstraps the fresh plist) or
  `launchctl kickstart gui/$UID/com.tau.hub`.
- `tau hub uninstall` runs `launchctl bootout gui/$UID/com.tau.hub` (the hub gets SIGTERM) and
  deletes the plist.
- Logs: stdout/stderr in `<TAU_DATA_DIR>/hub/logs/launchd.{out,err}.log`, details in
  `<TAU_DATA_DIR>/logs/tau.log`.
- The plist points at the venv's python. After moving the checkout or recreating `.venv`, run
  `tau hub install` again.

Check the self-heal by hand (with TauBar too):

```sh
curl -s 127.0.0.1:7877/health    # note the pid
kill -9 <pid>
sleep 5; uv run tau hub status   # a new pid, and "Last crash: … unexpected exit (no clean shutdown)"
```

Not `pkill -9 -f "tau_core hub run"`: that kills every hub on the machine, including a test hub
with another `TAU_DATA_DIR`.

## Linux (RPi5): systemd user unit

```sh
cd /path/to/tau
uv run tau hub systemd-unit > ~/.config/systemd/user/tau-hub.service
systemctl --user daemon-reload
systemctl --user enable --now tau-hub
loginctl enable-linger "$USER"   # start at boot, without a login session
```

`Restart=on-failure` with `RestartSec=3` gives the same behavior as launchd: restart after a crash
or kill, no restart after a clean stop (`tau hub stop` or `systemctl --user stop tau-hub`).
`--python PATH` renders the unit for another interpreter.

## Hub files

Everything the hub keeps lives in `<TAU_DATA_DIR>/hub/` (default `~/.local/share/tau/hub/`):

| File | Meaning |
|---|---|
| `hub.lock` | `flock` single-instance lock; holds the running hub's pid; never deleted |
| `state.json` | pid, `started_at`, `heartbeat_at`, version, role, profile, `last_crash`, `stopped_at` |
| `crash.json` | reason a failing hub wrote on its way down; consumed by the next start |
| `crash_reports.jsonl` | every crash the next start noticed, oldest first |
| `last_crash.json` | the most recent crash report (shown by `tau hub status` and `/status`) |
| `logs/` | the supervisor's stdout/stderr capture: `launchd.{out,err}.log` or `taubar.{out,err}.log` |
