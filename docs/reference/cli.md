# CLI

Every `tau` subcommand is a component: `tau-core` ships `chat`, `components`, `doctor`, `hub`, `init`, `proxy` and `version`; `tau-tui` adds `tui` and `tau-net` adds `net` (see [Join the tau network](../guides/tau-network.md)); any installed distribution can add more through the `tau.commands` entry point group. This page mirrors `--help` for each of them.

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
  net         Talk to other taus (identity, contacts, messages).
  proxy       Manage the model proxy's keys and budgets.
  tui         Open tau in the Textual interface.
  version     Show the versions of the installed tau packages.
```

The three global options go **before** the subcommand: `tau --home ~/other --lang tr chat`. `--profile` and `--lang` are exported as `TAU_PROFILE` and `TAU_LANG` for the run, so a subcommand in another package sees them too. `-v` sends `INFO` to stderr instead of only `WARNING`.

## `tau init`

```text
Usage: tau init [OPTIONS]

  Set up a configuration root: tau.toml from the shipped template (provider
  picked from the credentials present in the environment or <home>/.env:
  proxy, then anthropic, then bedrock, else fake), persona/persona.md,
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

`--provider` accepts `proxy`, `anthropic`, `bedrock` or `fake`; the model ids it writes come from a table shipped with the package, so tau-core's Python never names a model. Without `--provider`, `proxy` is picked when `TAU_PROXY_KEY_BRAIN` is set, `anthropic` when `ANTHROPIC_API_KEY` is, `bedrock` when AWS credentials are, else `fake`.

- `proxy` writes the template as shipped: every role on the LiteLLM proxy, with its budget table.
- Any other provider rewrites `brain` and `fast` to it, points `local` at `ollama` (`qwen3.5:9b`, Ollama called directly) and drops the `budget` tables, since only the proxy enforces them.

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

When a role uses the `proxy` provider, doctor also checks the proxy: `warn proxy` when it does not answer on `/health/liveliness`, then one `proxy <role>` line per proxy role (`ok` with `$0.40 of $15.00 per 1mo, within budget`; `warn` when the key's cap differs from `tau.toml` or the role has no budget; `fail` when the proxy does not accept the key). A `budget` on a role whose provider is not `proxy` is a `warn`, since nothing enforces it.

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

## `tau proxy`

```text
Usage: tau proxy [OPTIONS] COMMAND [ARGS]...

  Virtual keys, budgets and spend of the roles served through the LiteLLM
  proxy (provider = "proxy" in tau.toml; the proxy itself is infra/litellm).

Options:
  -h, --help  Show this message and exit.

Commands:
  keys    Create the missing role keys (written to .env) and align every...
  rotate  Replace ROLE's key with a new one; the spend of the current...
  spend   Print what every proxy role's key spent in its period.
```

Every subcommand works on the roles whose `provider` is `"proxy"` and stops with `no role in tau.toml uses provider = "proxy"` when there is none. The proxy's URL is the first proxy role's `params.base_url`, else `TAU_PROXY_URL`, else `http://127.0.0.1:4000`. Starting and stopping the proxy itself is `infra/litellm/proxy.sh`; see [Model proxy and budgets](../guides/model-proxy.md). Output is plain English, like `tau doctor`.

### `tau proxy keys`

```text
Usage: tau proxy keys [OPTIONS] [ROLES]...

  Create the missing role keys (written to .env) and align every key's model
  group and budget with tau.toml. Needs LITELLM_MASTER_KEY. Safe to run again.

Options:
  --replace   Replace a key the proxy holds under a role's alias that .env
              does not have.
  -h, --help  Show this message and exit.
```

Without `ROLES` it handles every proxy role. For each one:

- **created**: `.env` has no key the proxy knows, so a new key is made with the alias `tau-<role>`, the role's model group only, and the role's `budget` as `max_budget` + `budget_duration`. It is written to `<TAU_HOME>/.env` as `TAU_PROXY_KEY_<GROUP>` (mode `0600`) and exported to the process.
- **updated**: the key exists but its alias, model group or cap differs from `tau.toml`; the proxy is told the new values.
- **unchanged**: nothing to do.

```text
  brain    created   TAU_PROXY_KEY_BRAIN  $15.00 per 1mo, then fast
  fast     updated   TAU_PROXY_KEY_FAST  max_budget → $2.00 per 1d
  local    unchanged TAU_PROXY_KEY_LOCAL  $0.50 per 1d
```

If the proxy already holds a key under the alias `tau-<role>` that `.env` does not have, `keys` stops: that key may belong to another tau home sharing the proxy. `--replace` deletes it and creates a new one; its spend in the current period carries over, so the budget does not reset. Exit 1 with the reason when `LITELLM_MASTER_KEY` is not set, a named role is not a proxy role, or the proxy refuses or does not answer.

### `tau proxy rotate`

```text
Usage: tau proxy rotate [OPTIONS] ROLE

  Replace ROLE's key with a new one; the spend of the current period moves
  with it. Restart the hub afterwards so it reads the new key.

Options:
  -h, --help  Show this message and exit.
```

```text
  brain    rotated   TAU_PROXY_KEY_BRAIN  $0.42 spent this period kept
```

The old key is renamed, the new one is created with the old one's spend and written to `.env`, then the old one is deleted; if creating the new key fails, the old one gets its alias back. Needs `LITELLM_MASTER_KEY`. A role whose key the proxy does not know is refused with a pointer to `tau proxy keys`.

### `tau proxy spend`

```text
Usage: tau proxy spend [OPTIONS]

  Print what every proxy role's key spent in its period.

Options:
  --json      Print the spend as JSON.
  -h, --help  Show this message and exit.
```

```text
  brain    brain    $0.42 of $15.00 per 1mo, resets 2026-10-01 00:00 UTC
  fast     fast     $1.00 of $1.00 per 1d, resets 2026-10-01 00:00 UTC · SPENT
  local    local    unknown (TAU_PROXY_KEY_LOCAL is not set)
```

Columns: role, model group, spend of the current period, cap, period and the next reset (UTC). `· SPENT` marks a key at its cap (`, fast answers instead` when the role has `degrade_to`); `· differs from tau.toml, run tau proxy keys` marks a key whose cap drifted. It reads each key's own record from the proxy, so it needs no master key. `--json` prints `{role: {"group", "spend_usd", "max_budget_usd", "period", "reset_at", "exhausted", "configured": {"usd", "period", "degrade_to"}, "error"}}`, the same objects as the hub's `GET /spend`.

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
  poll      Handle queued envelopes once.
  publish   Publish the card.
  remove    Forget a contact.
  send      Send a message to a contact.
  status    Show the network status.
```

Added by `tau-net`. The spine comes from `TAU_SPINE_URL` and `TAU_SPINE_TOKEN`; the identity from `TAU_DATA_DIR/net/identity.json` or `TAU_NET_IDENTITY`; the settings from `[component.net]`. The setup is in [Join the tau network](../guides/tau-network.md) and the protocol in [the tau network reference](tau-network.md).

| Command | What it does |
|---|---|
| `tau net init [--name NAME]` | Creates the identity (an Ed25519 signing key and an X25519 box key); never overwrites one. `--name` writes `[component.net] name` into `tau.toml` |
| `tau net status` | Identity, spine health, whether the published card matches, contacts by state, where the network state is stored |
| `tau net card` / `tau net publish` | Prints the served card / publishes it with `PUT /hub/card` (the hub service also publishes on start) |
| `tau net contacts` | Contacts and pending requests |
| `tau net add ADDRESS [--note TEXT]` | Fetches the card, remembers the address as pending and sends a contact request; accepts at once if they had asked already |
| `tau net accept ADDRESS` | Accepts a pending request: pins the keys and sends a `contact_accept` |
| `tau net block ADDRESS` / `tau net remove ADDRESS` | Nothing from the address is read or answered any more / forgets the contact (its log and session stay) |
| `tau net send ADDRESS TEXT...` | Sends a message in your name to an accepted contact (at most 8 000 characters). Your own command, so no approval; the agent's `net_send` tool is tier 2 |
| `tau net log [--address ADDRESS] [-n N]` | The network log, oldest first (default 20 entries) |
| `tau net poll --once` | Handles what the spine holds right now, network turns included, without a running hub. Do not run it while the hub polls |

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
| 1 | `tau doctor` found a failing check; `tau hub run` found a running hub; a hub or `tau proxy` command could not do its job |
| 2 | `tau chat` / `tau tui`: missing credentials, invalid config or unknown session, before anything opened; also Click's own usage errors |
| 130 | `tau chat` left on Ctrl-C while an approval prompt was still blocking on stdin |

## Environment

Every command honours `TAU_HOME`, `TAU_DATA_DIR`, `TAU_PROFILE`, `TAU_ROLE`, `TAU_HUB_PORT` and `TAU_LANG`, and reads `<TAU_HOME>/.env` without overriding variables already set. `tau proxy`, `tau doctor` and every channel on a `proxy` role also read `TAU_PROXY_URL` and the `TAU_PROXY_KEY_*` keys; `tau proxy keys` and `rotate` need `LITELLM_MASTER_KEY`. See [Environment variables](environment.md).
