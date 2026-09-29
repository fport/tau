# CLI

Every `tau` subcommand is a component: `tau-core` ships `chat`, `components`, `doctor`, `hub`, `init` and `version`; `tau-tui` adds `tui`; any installed distribution can add more through the `tau.commands` entry point group. This page mirrors `--help` for each of them.

Inside a repository checkout, prefix each command with `uv run`.

## `tau`

```text
Usage: tau [OPTIONS] COMMAND [ARGS]...

  tau — a personal smart-body agent.

  Subcommands come from plugins (the tau.commands entry point group).

Options:
  -h, --help      Show this help and exit.
  --profile NAME  Active profile, e.g. home | travel | sport (default:
                  TAU_PROFILE, else 'home').
  --home DIR      Configuration root: tau.toml, persona/, tools/ (default:
                  TAU_HOME).
  --lang LANG     UI language, en | tr (default: TAU_LANG, else [ui] in
                  tau.toml).
  -v, --verbose   Verbose log output.

Commands:
  chat        Chat with tau in the terminal.
  components  List installed components and their state.
  doctor      Check the installation.
  hub         Run and manage tau as a long-lived service in the hub role.
  init        Create tau.toml and the persona files.
  tui         Open tau in the Textual interface.
  version     Show the versions of the installed tau packages.
```

The three global options go **before** the subcommand: `tau --home ~/other --lang tr chat`. `--profile` and `--lang` are exported as `TAU_PROFILE` and `TAU_LANG` for the run, so a subcommand in another package sees them too. `-v` sends `INFO` to stderr instead of only `WARNING`.

## `tau init`

```text
Usage: tau init [OPTIONS]

  Set up a configuration root: tau.toml from the shipped template (provider
  picked from the credentials present in the environment or <home>/.env:
  bedrock, then anthropic, else fake), persona/persona.md,
  persona/user.example.md, persona/user.md (from the example, unless it
  exists) and .env.example (the variable names). Existing files are kept
  unless --force is given; user.md and .env.example are never overwritten.

Options:
  -h, --help       Show this help and exit.
  --home DIR       Configuration root to create (default: TAU_HOME, else
                   ~/.tau).
  --provider NAME  Provider for the brain and fast roles (default: the first
                   with credentials).
  --language LANG  UI language, en | tr (asked when not given, unless --yes).
  --profile NAME   Write TAU_PROFILE=NAME into <home>/.env (appended; an
                   existing value is kept).
  -y, --yes        Ask nothing; use defaults for what is not given.
  --force          Overwrite an existing tau.toml and persona.md.
```

`--provider` accepts `bedrock`, `anthropic` or `fake`; the model ids it writes come from a table shipped with the package, so tau-core's Python never names a model. The `local` role keeps the template's value. Exit 0 on success, including when it kept every existing file.

## `tau doctor`

```text
Usage: tau doctor [OPTIONS]

  Check the installation: tau.toml, each role's provider and credentials (no
  model client is built), the session store, the persona files, .env against
  .env.example, component load errors, [components] names nothing provides and
  whether a hub answers on the control API. Exit 1 when a check fails.

Options:
  -h, --help  Show this help and exit.
  --json      Print the checks as JSON.
```

Each check line is `ok`, `warn`, `info` or `fail` followed by the check name and a detail. Exit 1 only on `fail`. `--json` prints `{"ok": bool, "checks": [{"name", "status", "detail"}, …]}`. The root is the global `--home` option: `tau --home DIR doctor`. See [First run](../getting-started/first-run.md) for the meaning of every line.

## `tau components`

```text
Usage: tau components [OPTIONS]

  List every component tau can see: tools, commands, providers, session
  backends, context sources and hub services, with their distribution,
  version, whether [components] enables them and any load error.

Options:
  -h, --help  Show this help and exit.
  --json      Print the listing as JSON.
```

One block per entry-point group, one row per component: name, distribution and version, `enabled` or `disabled`, and a note (`tier N` for tools, `in use: brain, fast` or `available` for providers, `in use` for the session backend, the `tau <name>` for commands, a load error when there is one). See [Components and plugins](components.md) for a full listing.

## `tau chat`

```text
Usage: tau chat [OPTIONS]

  Chat with tau in the terminal.

Options:
  -h, --help     Show this help and exit.
  --role ROLE    Model role to use (default: brain, or the role a resumed
                 session remembers from /model).
  --resume [ID]  Resume an earlier session (same as /resume).
  --session ID   Start with this session id.
```

- `--resume` alone resumes the most recent earlier session with messages; `--resume ID` resumes that one.
- `--session ID` opens (or creates) a session with that id; ids must be plain names (letters, digits, `.`, `_`, `-`).
- `--role` pins the role for the whole run and wins over the role a resumed session remembers.
- Exit 2 before the prompt appears when credentials are missing, the config is invalid, or the session cannot open. Ctrl-D and `/quit` exit 0.

## `tau tui`

```text
Usage: tau tui [OPTIONS]

  Open tau in the Textual interface.

Options:
  -h, --help      Show this help and exit.
  --profile NAME  Active profile (default: TAU_PROFILE, else 'home').
  --resume [ID]   Resume an earlier session (the most recent one when ID is
                  omitted).
```

`--profile` here is the same setting as the global one; either place works. A broken config or an unknown session id end the command with a plain English message and exit code 2 before the interface opens. With no `tau.toml` at all the setup screen opens first and creates one (the same code as `tau init`; Esc there is exit code 2 too); with a config whose role has no credentials the interface opens on its settings screen and the chat starts once a key is saved ([First run](../getting-started/first-run.md#in-the-interface-tau-tui)). While it runs, logging goes only to `<TAU_DATA_DIR>/logs/tau.log`.

## `tau hub`

```text
Usage: tau hub [OPTIONS] COMMAND [ARGS]...

  Run and manage tau as a long-lived service in the hub role.

Options:
  -h, --help  Show this help and exit.

Commands:
  install       Install and start the launchd agent (macOS).
  run           Run the hub in the foreground.
  status        Show the hub's status and the reason of its last crash.
  stop          Stop the running hub (SIGTERM, clean shutdown).
  systemd-unit  Print the systemd unit file (for the RPi5 hub).
  uninstall     Remove the launchd agent (macOS).
```

### `tau hub run`

```text
Usage: tau hub run [OPTIONS]

  Run the hub in the foreground (launchd and systemd run this too).

Options:
  -h, --help  Show this help and exit.
```

Exit 1 with `tau hub is already running (pid N)…` when the lock is held. Ctrl-C or `tau hub stop` stops it cleanly.

### `tau hub status`

```text
Usage: tau hub status [OPTIONS]

  Show the hub's status and the reason of its last crash.

Options:
  -h, --help  Show this help and exit.
  --json      Print the status as JSON.
```

Prints whether the hub runs (pid, uptime, heartbeat), the last crash and the launchd state. Exit 0 whether or not a hub runs.

### `tau hub stop`

```text
Usage: tau hub stop [OPTIONS]

  Stop the running hub (SIGTERM, clean shutdown).

Options:
  -h, --help         Show this help and exit.
  --timeout SECONDS  Wait at most this long for the hub to stop.  [default:
                     15.0]
```

Prints `Stop signal sent (pid N).` then `tau hub stopped.`, or `tau hub did not stop within N s.` on stderr with exit 1.

### `tau hub install` / `tau hub uninstall`

```text
Usage: tau hub install [OPTIONS]

  Install and start the hub as a launchd user agent (macOS).

Options:
  -h, --help  Show this help and exit.
```

```text
Usage: tau hub uninstall [OPTIONS]

  Stop and remove the launchd user agent (macOS).

Options:
  -h, --help  Show this help and exit.
```

macOS only; on Linux both print a message and exit 1. `install` is idempotent and needs a GUI login session. See [Run tau as a service](../guides/hub-service.md).

### `tau hub systemd-unit`

```text
Usage: tau hub systemd-unit [OPTIONS]

  Print the systemd unit file (for the RPi5 hub).

Options:
  -h, --help     Show this help and exit.
  --python PATH  The Python the service runs (default: the current
                 interpreter).
```

Prints the unit to stdout with this machine's absolute paths; redirect it into `~/.config/systemd/user/tau-hub.service`.

## `tau version`

```text
Usage: tau version [OPTIONS]

  Show the versions of the installed tau packages.

Options:
  -h, --help  Show this help and exit.
```

```text
tau-core 0.3.1
tau-tui 0.3.1
```

One line per installed `tau-*` distribution. It never imports a provider SDK, so it is safe to run on a broken installation.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | success; for `tau doctor`, no `fail` |
| 1 | `tau doctor` found a failing check; `tau hub run` found a running hub; a hub command could not do its job |
| 2 | `tau chat` / `tau tui`: missing credentials, invalid config or unknown session, before anything opened; also Click's own usage errors |
| 130 | `tau chat` left on Ctrl-C while an approval prompt was still blocking on stdin |

## Environment

Every command honours `TAU_HOME`, `TAU_DATA_DIR`, `TAU_PROFILE`, `TAU_ROLE`, `TAU_HUB_PORT` and `TAU_LANG`, and reads `<TAU_HOME>/.env` without overriding variables already set. See [Environment variables](environment.md).
