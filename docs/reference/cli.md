# CLI

Every `tau` subcommand is a component: `tau-core` ships `chat`, `components`, `doctor`, `hub`, `init`, `setup`, `spend`, `telegram` and `version`; `tau-tui` adds `tui`, `tau-guard` adds `guard` ([Owner guard](../guides/guard.md)), `tau-net` adds `net`, `tau-cloud` adds `cloud` (see [Join the tau network](../guides/tau-network.md)) and `tau-sub` adds `sub`; any installed distribution can add more through the `tau.commands` entry point group. This page mirrors `--help` for each of them.

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
  guard       The owner guard (setup, verify, status, lock, log).
  hub         Run and manage tau as a long-lived service in the hub role.
  init        Create tau.toml and the persona files.
  net         Talk to other taus (identity, contacts, messages).
  setup       Pick, install and set up tau's features.
  spend       Show the spend per model role.
  sub         Specialists of your tau (/coach, /landing, ...).
  telegram    Pair your Telegram chat and show the channel's state.
  tui         Open tau in the Textual interface.
  version     Show the versions of the installed tau packages.
```

The three global options go **before** the subcommand: `tau --home ~/other --lang tr chat`. `--profile` and `--lang` are exported as `TAU_PROFILE` and `TAU_LANG` for the run, so a subcommand in another package sees them too. `-v` sends `INFO` to stderr instead of only `WARNING`.

## `tau setup`

```text
Usage: tau setup [OPTIONS] [COMMAND] [ARGS]...

  Pick tau's features, install their packages and set them up: an interactive
  checklist, then one `uv tool install` pinned to this tau-core, then `tau
  init` when there is no configuration, a short 'about you', each chosen
  feature's steps and `tau doctor`. Run it again to add a feature; what is set
  up is never asked again. --yes --features tui,sub asks nothing. `tau setup
  status|install|run --json` is the line protocol of the Mac app
  (docs/reference/setup.md).

Options:
  -h, --help        Show this help and exit.
  --features IDS    Comma-separated feature ids to set up (see `tau setup
                    status`); skips the checklist.
  -y, --yes         Ask nothing: defaults, no optional steps.
  --no-install      Install nothing; set up what is installed.
  --remove FEATURE  Uninstall a feature's package (its settings and data
                    stay).
  --upgrade         Reinstall tau-core and the installed feature packages at
                    their newest releases.

Commands:
  install  Install the packages of features.
  run      Run the steps of one feature.
  status   Show the features and their state.
```

```text
Usage: tau setup status [OPTIONS]

  Show every feature: whether this platform has it, whether its package is
  installed and whether it is set up. --json prints the object the Mac app
  reads.

Options:
  -h, --help  Show this help and exit.
  --json      Print one JSON object.
```

```text
Usage: tau setup install [OPTIONS]

  Install the packages of the given features with one `uv tool install`
  (pinned to this tau-core) and configure nothing. --json streams JSON lines.

Options:
  -h, --help      Show this help and exit.
  --features IDS  Comma-separated feature ids; what they require is added.
                  [required]
  --json          Stream JSON lines.
```

```text
Usage: tau setup run [OPTIONS] FEATURE

  Run the steps of one feature, or of init, about or doctor. With --json the
  inputs come as one JSON object on stdin ({"steps": [...], "inputs": {...}}),
  never in argv, and a step that needs its own UI is reported as needs_ui
  instead of run. Without --json the wizard's steps run for that feature.

Options:
  -h, --help  Show this help and exit.
  --json      JSON input on stdin, JSON lines out.
```

The wizard, the feature catalog and the JSON protocol the Mac app drives are specified in [`tau setup` and its JSON protocol](setup.md). The one-line installer, `curl -fsSL https://tau.getporti.com/install.sh | sh`, installs uv and tau and then starts `tau setup`.

## `tau init`

```text
Usage: tau init [OPTIONS]

  Set up a configuration root: tau.toml from the shipped template,
  persona/persona.md, persona/user.example.md, persona/user.md (from the
  example, unless it exists) and .env.example (the variable names). The
  provider is picked from the credentials present in the environment or
  <home>/.env (anthropic, openai, gemini, bedrock). Without any, tau init asks
  for a provider (anthropic, openai or gemini) and its key with hidden input,
  checks the key with one small request to the provider (--no-check skips it)
  and appends it to <home>/.env, which is kept at mode 0600; a key the
  provider refuses writes nothing. --yes asks nothing and falls back to the
  scripted 'fake' provider. Existing files are kept unless --force is given;
  user.md and .env.example are never overwritten.

Options:
  -h, --help       Show this help and exit.
  --home DIR       Configuration root to create (default: TAU_HOME, else
                   ~/.tau).
  --provider NAME  Provider for the brain and fast roles (default: the first
                   with credentials, else asked).
  --language LANG  UI language, en | tr (asked when not given, unless --yes).
  --profile NAME   Write TAU_PROFILE=NAME into <home>/.env (appended; an
                   existing value is kept).
  --no-check       Do not check a typed key with a request to the provider.
  -y, --yes        Ask nothing; use defaults for what is not given (no key).
  --force          Overwrite an existing tau.toml and persona.md.
```

`--provider` accepts `anthropic`, `openai`, `gemini`, `bedrock` or `fake`; the model ids it writes come from a table shipped with the package, so tau-core's Python never names a model. Without `--provider`, `anthropic` is picked when `ANTHROPIC_API_KEY` is set, then `openai` (`OPENAI_API_KEY`), then `gemini` (`GEMINI_API_KEY` or `GOOGLE_API_KEY`), then `bedrock` (AWS credentials). With none of them, `--yes` picks `fake`; without `--yes` it asks.

- It rewrites only the `provider` and `model_id` of `brain` and `fast`; `anthropic` writes the template as shipped.
- The `budget` tables stay (tau enforces them for every provider), and `local` stays on Ollama (`qwen3.5:9b`, `failover = "fast"`).

```text
Provider: anthropic. ANTHROPIC_API_KEY was found in the environment or ~/.tau/.env. tau.toml caps brain and fast with budgets tau enforces itself (`tau spend` shows them), and local uses Ollama on this machine, falling back to fast when it is not running.
```

**The provider key** ([ADR 0013](../adr/0013-hosted-taus-handles-and-public-pages.md) §7). An interactive run on a machine without credentials asks the UI language, then the provider (`anthropic`, `openai` or `gemini`; default `anthropic`) and its key with hidden input. `--provider anthropic|openai|gemini` without a key for it asks only the key.

- The key is checked with one `GET` of the provider's model list, with the key in a request header, never in the URL, and redirects not followed. `--no-check` skips it.
- A refused key (`401`/`403`), another status or no answer is explained on stderr, nothing is written and the exit code is 1.
- The key is written as `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` or `GEMINI_API_KEY` to `<home>/.env`: a new file is created with mode `0600`; an existing one is set to `0600` and the line is appended without touching the others. A name that already has a value is kept.
- An empty key skips: `tau.toml` is written for the provider, and a notice names the variable to add later.
- The prompts and notices follow the UI language chosen (the `init.*` keys of the message table); the key never appears in the output, argv or a log.

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
- With the [owner guard](../guides/guard.md) active, `tau chat` starts on a `locked> ` prompt and clears the screen and the scrollback; Enter starts a face check. Until it passes only `/help`, `/lang`, `/guard` and `/quit` run.

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

With the [owner guard](../guides/guard.md) active, the interface opens on an opaque lock screen before any session loads, and the setup and settings screens stay closed until a face check passes (Enter starts one, Esc cancels it, ctrl+q quits). tau Desktop runs this same command in its windows.

## `tau guard`

```text
Usage: tau guard [OPTIONS] COMMAND [ARGS]...

  The owner guard: face setup and checks, its state as the hub reports it,
  locking tau, the audit log.

Options:
  -h, --help  Show this help and exit.

Commands:
  doctor  Check everything the face guard depends on.
  enroll  Enroll your face again (behind Touch ID or your password).
  forget  Remove your face template, the marker and the Keychain key...
  lock    Lock tau now (every guarded channel, until you unlock at the Mac).
  log     Show the guard's audit log (checks, locks, cooldowns).
  setup   Set up the face guard at the Mac: the face model, your...
  status  Show the guard's state as the running hub reports it.
  verify  Run one face check with the head-turn challenge.
  window  Say whether the guard window can open here; --demo plays a...
```

Added by `tau-guard`, on macOS only (other platforms refuse the face commands). The setup, daily use and recovery are in [Owner guard](../guides/guard.md); keys, routes, states and the audit log in the [guard reference](guard.md).

| Command | What it does |
|---|---|
| `tau guard setup [--model-file FILE] [--no-window]` | Installs the SFace model (downloaded and checked against its pinned sha256, or from `FILE`), enrolls your face behind Touch ID or your Mac password, runs one check and writes `[component.guard] enabled = true` to `tau.toml`. At the Mac only: refused over SSH |
| `tau guard enroll [--add] [--no-window]` | Enrolls again behind Touch ID or your Mac password; `--add` adds samples under other light to the template. At the Mac only |
| `tau guard verify [--explain[=all]] [--no-window]` | One face check with the head-turn challenge. Through the hub when a guarded hub runs (a passed check unlocks tau), else in a local worker; `--explain` always runs locally, shows each prompt as a highlighted line and prints every 3rd frame's numbers (`=all`: every frame), never saving a frame, and names the liveness rule a failed check broke. Exit 1 when it fails |
| `tau guard forget` | Removes the template, the enrollment marker and the Keychain key behind Touch ID or your Mac password and writes `enabled = false`. Exit 1 when the Keychain kept the key: run it again. At the Mac only |
| `tau guard doctor` | Checks everything the face guard depends on, including which app holds the hub's camera grant. Exit 1 on a `fail` |
| `tau guard status [--json]` | The state as the running hub reports it. `off` without an active guard; exit 0 when no hub runs, 1 on a hub error |
| `tau guard lock` | Locks every guarded channel now (trigger `command`). Works over SSH too |
| `tau guard log [--since WHEN] [--json]` | The audit log; `WHEN` is a duration (`30m`, `2h`, `7d`) or an ISO date or time |
| `tau guard window [--demo]` | Whether the guard window is on and could open from here; `--demo` plays a scripted check in it on a synthetic picture (no camera; Esc closes it) |

During a check the worker shows the [guard window](guard.md#the-guard-window) (`[component.guard] window`, on by default); `--no-window` keeps it off for a check the command runs itself, while a check through the hub follows the hub's setting.

After `setup` or `forget`, restart the hub and any open `tau chat`, `tau tui` or tau Desktop window.

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

## `tau telegram`

```text
Usage: tau telegram [OPTIONS] COMMAND [ARGS]...

  The Telegram channel: pair your chat with the bot and show the channel's
  state. The hub polls the Bot API itself; no server sits in between (ADR
  0006).

Options:
  -h, --help  Show this help and exit.

Commands:
  pair    Pair your Telegram chat with the bot.
  status  Show the Telegram channel's state.
```

The setup is in [Telegram](../guides/telegram.md).

### `tau telegram pair`

```text
Usage: tau telegram pair [OPTIONS]

  Pair your Telegram chat with the bot, without looking up a chat id. Asks for
  the bot token from @BotFather with hidden input (Enter keeps the one in
  <home>/.env), checks it with one getMe and writes it to <home>/.env (mode
  0600). Then it shows a one-time code, valid 10 minutes: send /start <code>
  to the bot, or open the link it prints. The running hub takes the code;
  without a hub this command polls Telegram itself. The chat that sends the
  code becomes TELEGRAM_ALLOWED_CHAT_IDS; wrong or expired codes get no
  answer. With the owner guard on, tau must be unlocked. Exit 0 once paired, 1
  otherwise.

Options:
  -h, --help  Show this help and exit.
  --json      Read {"token": "..."} as one JSON line on stdin instead of
              prompting (null or "" keeps the current token) and print one
              JSON event per line (for the app's wizard).
```

- **The token** is checked with one `getMe` before anything is written, then set as `TELEGRAM_BOT_TOKEN` in `<home>/.env`: that line replaced or appended, every other line kept, the file at `0600`. It never appears in argv, the output or a log.
- **The code** is 8 characters without look-alikes, valid 10 minutes, usable once, and stored only as a salted PBKDF2 hash in `TAU_DATA_DIR/telegram/pairing.json` while the command waits. `/start <code>` from a private chat pairs it (the deep link `https://t.me/<bot>?start=<code>` sends that in one tap); the chat becomes the only entry of `TELEGRAM_ALLOWED_CHAT_IDS`. A group, a wrong code or an expired one gets no answer; 10 wrong codes void it; Ctrl-C withdraws it.
- **One poller.** With a hub running, the command calls the hub's signed `POST /telegram/reload`: the Telegram service reads the token, the allowlist (`.env` first) and the code again and accepts the code in its own poll loop, polling even with an empty allowlist while a code waits. Without a hub, the command polls `getUpdates` itself from the hub's saved offset, writes the offset back and stops right after the pairing update; messages of chats that stay allowed go to `inflight.json`, which the hub runs at its next start. A 409 from Telegram (another poller) makes it look for a hub that started meanwhile.
- **With the owner guard** active it asks the guard for admission first (channel label `telegram-pair`) and stops, asking nothing, when tau is locked: a paired chat is an identified channel that skips the guard.

`--json` is the app wizard's protocol. Input, one line on stdin:

```json
{"token": "123456789:AA..."}
```

`null`, `""` or no `token` keeps the token `.env` has. Output, one object per line, in this order:

```json
{"event": "note", "message": "Note: TELEGRAM_BOT_TOKEN is also set in this shell's environment. ..."}
{"event": "bot", "bot": "deniz_tau_bot", "token": "written"}
{"event": "code", "code": "K7QM-X2PA", "link": "https://t.me/deniz_tau_bot?start=K7QM-X2PA", "bot": "deniz_tau_bot", "expires_at": "2026-10-01T11:32:00+00:00"}
{"event": "waiting", "via": "hub"}
{"event": "paired", "name": "Deniz @deniz", "dropped": 0, "hub": true}
```

- `note` lines are optional and may come at any point (a variable the shell exports that shadows `.env`; another process polling the bot).
- `token` is `written` or `kept`; `via` is `hub` (the running hub polls) or `cli` (the command polls); `dropped` counts the chats that lost access; `hub` says whether a running hub took the code.
- A failure ends the stream with `{"event": "error", "reason": "...", "message": "..."}` and exit 1 (2 for `config`, 130 after Ctrl-C). `message` is in the UI language; `reason` is one of `config`, `locked`, `bad_json`, `no_token`, `token_invalid`, `token_refused`, `unreachable`, `env_write`, `hub_conflict`, `hub_mismatch`, `hub_error`, `expired`, `void`, `cancelled`.

### `tau telegram status`

```text
Usage: tau telegram status [OPTIONS]

  Show whether a bot token is set (and the bot's name, from one getMe),
  whether an owner chat is paired, whether a pairing code waits and what the
  running hub's Telegram channel does. Never prints the token or a chat id.

Options:
  -h, --help  Show this help and exit.
  --json      Print the state as JSON.
```

```text
Bot token: set (@deniz_tau_bot)
Owner chat: paired (1 allowed)
Hub: running; polling as @deniz_tau_bot
```

`--json` prints `{"token", "bot", "bot_error", "token_refused", "paired", "allowed_chats", "pairing": {"expires_at"} | null, "hub": {"running", "telegram"}}`, where `hub.telegram` is the `telegram` key of the hub's `/status`. Exit 0 either way.

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
| `tau net add ADDRESS [--note TEXT]` | Fetches the card, remembers the address as pending and sends a contact request; accepts at once if they had asked already. `ADDRESS` is a host (`tau.example.com`) or a hosted tau (`tau.example.com/@alice`) |
| `tau net accept ADDRESS` | Accepts a pending request: pins the keys and sends a `contact_accept` |
| `tau net block ADDRESS` / `tau net remove ADDRESS` | Nothing from the address is read or answered any more / forgets the contact (its log and session stay) |
| `tau net send ADDRESS[/NAME] TEXT...` | Sends a message in your name to an accepted contact (at most 8 000 characters). `ADDRESS/NAME` writes to that tau's public sub-tau `/NAME` (`tau.example.com/coach`, `tau.example.com/@alice/coach`), whose answer comes back from `/NAME`. Your own command, so no approval; the agent's `net_send` tool is tier 2 |
| `tau net log [--address ADDRESS] [-n N]` | The network log, oldest first (default 20 entries) |
| `tau net poll --once` | Handles what the spine holds right now, network turns included, without a running hub. Do not run it while the hub polls |
| `tau net spine init DIR [--address HOST]` | Writes a ready-to-deploy spine project from the kit inside `tau-net` into a new or empty `DIR`. `--address` sets `ADDRESS` and a custom-domain route; without it the address is `tau-spine.<subdomain>.workers.dev` |
| `tau net spine deploy DIR [--address HOST] [--account-id ID] [--json]` | Deploys it through the Cloudflare API, with no Node.js: the API token is `CLOUDFLARE_API_TOKEN` (environment or `.env`), else it prints the link that creates one with the right permissions and asks for it at a hidden prompt, then saves it in `.env`. Uploads `worker.js` with the bindings, migrations and cron of `wrangler.jsonc`, creates the KV namespace, records the account and namespace ids in `wrangler.jsonc`, sets the Worker's `HUB_TOKEN` secret to `TAU_SPINE_TOKEN` from the hub's `.env` (generated when missing, never printed), turns on `workers.dev` or attaches the custom domain, writes `TAU_SPINE_URL` and checks the spine's health. `--json` reads `{"token", "account_id"}` from stdin and prints JSON lines ([universe reference §4](tau-universe.md#4-the-spine-kit-tau-net-spine)) |
| `tau net spine deploy DIR --wrangler [--address HOST]` | Deploys it with Wrangler instead (Node.js 22+, `wrangler login` first): sets the same secret on stdin and writes `TAU_SPINE_URL` |
| `tau net universe join [--owner NAME] [--about TEXT] [--links \| --no-links]` | Lists this tau in the universe of `[component.net] universe` (default `tau.getporti.com`): writes the profile, publishes the card when needed, sends a signed join and a report, prints the tau's page |
| `tau net universe status` / `tau net universe leave` | Whether the profile says joined and whether the universe lists this tau, with its handle, visible links and public sub-taus (those with a web page with today's visitor turns) / sends a signed leave, stops the hub's reports and forgets the universe's pinned keys, so no visits come in |
| `tau net universe claim` | Prints `https://<universe>/claim#…`, a claim signed by this tau and valid for an hour. Open it and sign in with GitHub there: the universe binds your GitHub login as this tau's handle (`/@login`). Publishes the card first when needed; sends nothing. Do not share the link |

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
| 1 | `tau doctor` or `tau guard doctor` found a failing check; `tau hub run` found a running hub; a hub command could not do its job; a `tau guard` check, enrollment or forget did not succeed; `tau telegram pair` did not pair a chat |
| 2 | `tau chat` / `tau tui`: missing credentials, invalid config or unknown session, before anything opened; `tau guard` face commands on a platform other than macOS or over SSH; `tau telegram` without a loadable config; also Click's own usage errors |
| 130 | `tau chat` left on Ctrl-C while an approval prompt was still blocking on stdin; `tau telegram pair` cancelled with Ctrl-C |

## Environment

Every command honours `TAU_HOME`, `TAU_DATA_DIR`, `TAU_PROFILE`, `TAU_ROLE`, `TAU_HUB_PORT` and `TAU_LANG`, and reads `<TAU_HOME>/.env` without overriding variables already set. The channels also read the model credentials of their roles and `TAU_OLLAMA_URL`; `tau spend` and the budgets use the ledger under `TAU_DATA_DIR`. See [Environment variables](environment.md).
