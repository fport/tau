# CLI

Every `tau` subcommand is a component: `tau-core` ships `chat`, `components`, `doctor`, `hub`, `init`, `spend` and `version`; `tau-tui` adds `tui`, `tau-net` adds `net` and `tau-cloud` adds `cloud` (see [Join the tau network](../guides/tau-network.md)); any installed distribution can add more through the `tau.commands` entry point group. This page mirrors `--help` for each of them.

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
  cloud       Cloud mode: sync config and persona with the spine, run the
              brain.
  components  List installed components and their state.
  doctor      Check the installation.
  hub         Run and manage tau as a long-lived service in the hub role.
  init        Create tau.toml and the persona files.
  net         Talk to other taus (identity, contacts, messages).
  spend       Show the spend per model role.
  tui         Open tau in the Textual interface.
  version     Show the versions of the installed tau packages.
```

The three global options go **before** the subcommand: `tau --home ~/other --lang tr chat`. `--profile` and `--lang` are exported as `TAU_PROFILE` and `TAU_LANG` for the run, so a subcommand in another package sees them too. `-v` sends `INFO` to stderr instead of only `WARNING`.

## `tau init`

```text
Usage: tau init [OPTIONS]

  Set up a configuration root: tau.toml from the shipped template (provider
  picked from the credentials present in the environment or <home>/.env:
  anthropic, openai, gemini, bedrock, else fake), persona/persona.md,
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

`--provider` accepts `anthropic`, `openai`, `gemini`, `bedrock` or `fake`; the model ids it writes come from a table shipped with the package, so tau-core's Python never names a model. Without `--provider`, `anthropic` is picked when `ANTHROPIC_API_KEY` is set, then `openai` (`OPENAI_API_KEY`), then `gemini` (`GEMINI_API_KEY` or `GOOGLE_API_KEY`), then `bedrock` (AWS credentials), else `fake`.

- It rewrites only the `provider` and `model_id` of `brain` and `fast`; `anthropic` writes the template as shipped.
- The `budget` tables stay (tau enforces them for every provider), and `local` stays on Ollama (`qwen3.5:9b`, `failover = "fast"`).

```text
Provider: anthropic. ANTHROPIC_API_KEY was found in the environment or ~/.tau/.env. tau.toml caps brain and fast with budgets tau enforces itself (`tau spend` shows them), and local uses Ollama on this machine, falling back to fast when it is not running.
```

Exit 0 on success, including when it kept every existing file.

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

When some role has a budget, doctor adds a `budget` line with every role's spend from the ledger (`ok   budget: brain $0.00 of $15.00 this month (resets 01.10.2026 00:00); fast $0.00 of $1.00 today (resets 01.10.2026 00:00)`), or a `fail` when the ledger cannot be read. A budgeted role whose model has no price is a `warn` on its role line (`has a budget, but model 'my-model' has no price, so its calls count as $0; add [models.prices."my-model"] to tau.toml`).

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

## `tau spend`

```text
Usage: tau spend [OPTIONS]

  Show what every model role spent in its budget period (from the ledger under
  TAU_DATA_DIR) next to its budget in tau.toml.

Options:
  --json      Print the spend as JSON.
  -h, --help  Show this message and exit.
```

```text
  brain    anthropic $0.42 of $15.00 this month, resets 01.10.2026 00:00
  fast     anthropic $1.01 of $1.00 today, resets 01.10.2026 00:00 · SPENT
  local    ollama    $0.00 this month, no budget
```

Columns: role, provider, what the role spent in its current period, its cap, the period (`today`, `this week`, `this month`) and the next reset (Europe/Istanbul). `· SPENT` marks a role at its cap (`, fast answers instead` when it has `degrade_to`); `· N calls without a price for <model id>` counts calls on a model that has no price. A role without a budget reads `no budget (its calls are not counted)`, or its spend this month when a `failover` made it metered. It reads `tau.toml` and the ledger `TAU_DATA_DIR/spend.sqlite3` directly, so it needs no running hub and shows a changed cap at once. Output is plain English, like `tau doctor`.

`--json` prints one object per role, the same objects as the hub's `GET /spend` without its `roles` wrapper:

```json
{
  "brain": {
    "provider": "anthropic",
    "model_id": "claude-sonnet-5",
    "spent_usd": 0.42,
    "cap_usd": 15.0,
    "period": "month",
    "since": "2026-09-01T00:00:00+03:00",
    "reset_at": "2026-10-01T00:00:00+03:00",
    "exhausted": false,
    "degrade_to": "fast",
    "unpriced_calls": 0,
    "metered": true
  }
}
```

See [Models and budgets](../guides/models-and-budgets.md).

## `tau net`

```text
Usage: tau net [OPTIONS] COMMAND [ARGS]...

  The tau network: your tau's identity, card and contacts, and messages to
  other taus.

Options:
  -h, --help  Show this help and exit.

Commands:
  accept    Accept a contact request.
  add       Ask another tau to become a contact.
  block     Block an address.
  card      Print the card.
  contacts  List contacts.
  init      Create the network identity.
  log       Show the network log.
  name      Set the card's display name.
  poll      Handle queued envelopes once.
  publish   Publish the card.
  remove    Forget a contact.
  send      Send a message to a contact.
  spine     Set up and deploy your spine Worker.
  status    Show the network status.
  universe  Join or leave the tau universe.
```

Added by `tau-net`. The spine comes from `TAU_SPINE_URL` and `TAU_SPINE_TOKEN`; the identity from `TAU_DATA_DIR/net/identity.json` or `TAU_NET_IDENTITY`; the settings from `[component.net]`. The setup is in [Build your own tau](../getting-started/build-your-own-tau.md) and [Join the tau network](../guides/tau-network.md); the protocols are in [the tau network reference](tau-network.md) and [the tau universe reference](tau-universe.md).

| Command | What it does |
|---|---|
| `tau net init [--name NAME]` | Creates the identity (an Ed25519 signing key and an X25519 box key); never overwrites one. `--name` sets the card's display name in the network profile under `TAU_DATA_DIR/net`, never in `tau.toml` |
| `tau net name NAME...` | Sets the card's display name (1 to 80 characters) in the network profile; it wins over `[component.net] name`. Publish it with `tau net publish` |
| `tau net status` | Identity, spine health, whether the published card matches, contacts by state, where the network state is stored |
| `tau net card` / `tau net publish` | Prints the served card / publishes it with `PUT /hub/card` (the hub service also publishes on start) |
| `tau net contacts` | Contacts and pending requests |
| `tau net add ADDRESS [--note TEXT]` | Fetches the card, remembers the address as pending and sends a contact request; accepts at once if they had asked already |
| `tau net accept ADDRESS` | Accepts a pending request: pins the keys and sends a `contact_accept` |
| `tau net block ADDRESS` / `tau net remove ADDRESS` | Nothing from the address is read or answered any more / forgets the contact (its log and session stay) |
| `tau net send ADDRESS[/NAME] TEXT...` | Sends a message in your name to an accepted contact (at most 8 000 characters). `ADDRESS/NAME` writes to that tau's public sub-tau `/NAME`, whose answer comes back from `/NAME`. Your own command, so no approval; the agent's `net_send` tool is tier 2 |
| `tau net log [--address ADDRESS] [-n N]` | The network log, oldest first (default 20 entries) |
| `tau net poll --once` | Handles what the spine holds right now, network turns included, without a running hub. Do not run it while the hub polls |
| `tau net spine init DIR [--address HOST]` | Writes a ready-to-deploy spine project from the kit inside `tau-net` into a new or empty `DIR`. `--address` sets `ADDRESS` and a custom-domain route; without it the address is `tau-spine.<subdomain>.workers.dev` |
| `tau net spine deploy DIR [--address HOST]` | Deploys it with Wrangler after checking the login, sets the Worker's `HUB_TOKEN` secret to `TAU_SPINE_TOKEN` from the hub's `.env` (generated when missing, passed on stdin, never printed) and writes `TAU_SPINE_URL` there |
| `tau net universe join [--owner NAME] [--about TEXT] [--links \| --no-links]` | Lists this tau in the universe of `[component.net] universe` (default `tau.getporti.com`): writes the profile, publishes the card when needed, sends a signed join and a report, prints the tau's page |
| `tau net universe status` / `tau net universe leave` | Whether the profile says joined and whether the universe lists this tau, with its visible links / sends a signed leave and stops the hub's reports |

## `tau cloud`

```text
Usage: tau cloud [OPTIONS] COMMAND [ARGS]...

  Cloud mode: your tau's hub runs as a container in your own Cloudflare
  account and keeps sessions, config and persona in the spine (ADR 0007).

Options:
  -h, --help  Show this help and exit.

Commands:
  pull    Download tau.toml and the persona files from the spine.
  push    Upload tau.toml and the persona files to the spine.
  run     Run the hub as the brain container (entrypoint).
  status  Show the spine, its files and the brain.
```

Added by `tau-cloud`; the setup is in [Run tau in Cloudflare (cloud mode)](../guides/cloud-mode.md). Every subcommand needs `TAU_SPINE_URL` and `TAU_SPINE_TOKEN`.

| Command | What it does |
|---|---|
| `tau cloud push [--include-user] [-y]` | Uploads `tau.toml`, `persona/persona.md`, `persona/net.md` and the sub-tau files (`persona/subs/*.md` with a plain name; other entries of that directory, subdirectories and symbolic links are skipped and named). Sub-tau files gone here are removed from the spine when `persona/subs/` exists. `persona/user.md` goes up only with `--include-user` or a yes to its own question; `.env` never goes up |
| `tau cloud pull [--force]` | Downloads the same files into `TAU_HOME`; a local file that differs is kept unless `--force`, nothing local is deleted, and a listed name outside the file set is skipped |
| `tau cloud status` | The spine's health and mode, the files it holds, the brain container's `/health` |
| `tau cloud run` | The container entrypoint: pull the files (sub-tau files included), set `[sessions] backend` and `[component.net] store` to `spine`, serve `GET /health` on `0.0.0.0:8080` (`TAU_CLOUD_HEALTH_HOST`/`_PORT` override), run the hub until SIGTERM. Refuses a `TAU_HOME` whose `tau.toml` it did not write |

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

Every command honours `TAU_HOME`, `TAU_DATA_DIR`, `TAU_PROFILE`, `TAU_ROLE`, `TAU_HUB_PORT` and `TAU_LANG`, and reads `<TAU_HOME>/.env` without overriding variables already set. The channels also read the model credentials of their roles and `TAU_OLLAMA_URL`; `tau spend` and the budgets use the ledger under `TAU_DATA_DIR`. See [Environment variables](environment.md).
