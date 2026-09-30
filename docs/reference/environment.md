# Environment variables

tau reads its environment once at start-up, then `<TAU_HOME>/.env` with python-dotenv. A variable that is already set in the environment is never overridden by the file. `.env` is gitignored and holds real values; `.env.example` next to it holds every name with an example value, and `tau doctor` warns about a name in `.env` that `.env.example` does not list.

Precedence for the settings that have a command-line option: option → environment → `.env` → `tau.toml` → default.

## Roots and identity

| Variable | Default | Meaning |
|---|---|---|
| `TAU_HOME` | the current directory when it holds `tau.toml`, else `~/.tau` | The configuration root: `tau.toml`, `.env`, `persona/`, `tools/`. `tau --home DIR` wins. |
| `TAU_DATA_DIR` | `~/.local/share/tau` | Mutable state: `sessions/`, `hub/` (with the control token `hub/control.token`), `logs/`, the spend ledger `spend.sqlite3` and, with the owner guard, `guard/`. Never inside a repository. |
| `TAU_PROFILE` | `home` | The active profile: `home`, `travel` or `sport`. `tau --profile NAME` wins and is exported as this variable. |
| `TAU_ROLE` | `hub` | The host role, `hub` or `node`. The hub service templates set `hub`; the mesh (layer 5) uses `node`. Any other value is a `ConfigError`. |
| `TAU_HUB_PORT` | `[hub] control_port` (7877) | Overrides the control API port. Must be a number. |
| `TAU_LANG` | `[ui] language` (`en`) | UI language, `en` or `tr`. `tau --lang` wins and is exported as this variable. |

## Model credentials

Which ones you need depends on the providers in `tau.toml`. Each provider accepts one of several *alternatives*; every variable of one alternative must be set.

| Provider | Alternatives |
|---|---|
| `anthropic` | `ANTHROPIC_API_KEY` (or the variable named by `params.api_key_env`). Optionally `ANTHROPIC_WORKSPACE_ID` for a key that is not scoped to a workspace. |
| `openai` | `OPENAI_API_KEY` (or the variable named by `params.api_key_env`). |
| `gemini` | `GEMINI_API_KEY` · `GOOGLE_API_KEY` (or the variable named by `params.api_key_env`). |
| `bedrock` | `AWS_REGION` + `AWS_PROFILE` · `AWS_REGION` + `AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY` · `AWS_REGION` + `AWS_BEARER_TOKEN_BEDROCK`. A `region` in the role drops `AWS_REGION` from each alternative. |
| `ollama` | none |
| `fake` | none |
| a `tau.providers` component | whatever its factory declares in `required_env` |

| Variable | Meaning |
|---|---|
| `ANTHROPIC_API_KEY` | The Anthropic key, `sk-ant-…`. |
| `ANTHROPIC_WORKSPACE_ID` | `wrksp_…`; sent as the `anthropic-workspace-id` header. Without it a non-scoped key gets a 400 from the API. |
| `OPENAI_API_KEY` | The OpenAI key, `sk-…`, or the key of the OpenAI-compatible API a role's `params.base_url` points at. |
| `GEMINI_API_KEY`, `GOOGLE_API_KEY` | The Google Gemini key; either name works, `GEMINI_API_KEY` is looked at first. |
| `TAU_OLLAMA_URL` | Where the `ollama` provider finds Ollama, without `/v1`. Default `http://127.0.0.1:11434` (this machine); a role's `params.base_url` wins. Set it when the hub is not the Mac that runs Ollama, e.g. `http://my-mac.tailXXXXXX.ts.net:11434`. Not a secret. |
| `AWS_REGION` | Bedrock region, e.g. `eu-central-1`. Bedrock is optional. |
| `AWS_PROFILE` | A named profile from `~/.aws/config`. |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | Static AWS credentials. |
| `AWS_BEARER_TOKEN_BEDROCK` | A Bedrock API key (bearer token). |

A missing credential stops `tau chat` with exit 2 and a message naming the variables; `tau tui` opens its settings screen on the Credentials section instead; `tau doctor` reports it without starting anything. `/settings set NAME` (terminal, hidden prompt) and the TUI's Credentials section write a value to `.env` (mode `0600`) and export it to the running process. Budgets need no variable: they live in `tau.toml`, the spend in `TAU_DATA_DIR/spend.sqlite3` ([Models and budgets](../guides/models-and-budgets.md)).

## Telegram

Read by the `telegram` hub service (see [Telegram](../guides/telegram.md)). Without a token, or without an allowed chat and no pairing code waiting, the service stays idle and the hub runs on. `tau telegram pair` writes both to `<TAU_HOME>/.env` and asks a running hub to reload them; on that reload the service reads the two names from `.env` first, since the hub loaded the file into its environment when it started.

| Variable | Meaning |
|---|---|
| `TELEGRAM_BOT_TOKEN` | The bot token from @BotFather, `123456789:AA…`. A password: it never appears in logs, `/status` or `tau doctor`. |
| `TELEGRAM_ALLOWED_CHAT_IDS` | The chat ids the bot answers, comma-separated. Messages from any other chat are dropped unanswered. `tau telegram pair` sets it to the chat that sent its one-time code. |

## tau network and cloud mode

[ADR 0007](../adr/0007-cloud-mode-and-tau-network.md); setup in [Join the tau network](../guides/tau-network.md) and [cloud mode](../guides/cloud-mode.md).

| Variable | Meaning |
|---|---|
| `TAU_SPINE_URL` | The tau's spine Worker, `https://tau.example.com` (`http://127.0.0.1:8787` while developing). Without it the `net` hub service stays idle. |
| `TAU_SPINE_TOKEN` | The spine's `HUB_TOKEN` secret. A password: never in logs, reprs or `/status`. |
| `TAU_NET_IDENTITY` | The network identity as base64url JSON, in place of `TAU_DATA_DIR/net/identity.json`. Cloud mode sets it as a Worker secret. |
| `TAU_NET_ALLOW_INSECURE` | `1` allows `http` to peers on `localhost` / `127.0.0.1`. Development only. |
| `CLOUDFLARE_API_TOKEN` | The Cloudflare API token `tau net spine deploy` uses to deploy the spine without Node.js: Workers Scripts and Workers KV Storage to edit, Account Settings to read, Workers Routes to edit for a custom domain. The deploy prints the link that creates it, asks for it at a hidden prompt and saves it here. A password: only ever sent in the `Authorization` header. The hub itself never reads it. |
| `CLOUDFLARE_ACCOUNT_ID` | Optional: the account `tau net spine deploy` uses when neither `--account-id` nor `account_id` in the spine's `wrangler.jsonc` names one. Wrangler reads it too. Not a secret. |

In cloud mode the brain container gets its credentials from the spine's Worker secrets: every model credential above except `AWS_PROFILE` and `TAU_OLLAMA_URL` (`ANTHROPIC_*`, the static and bearer AWS variables, `OPENAI_API_KEY`, `GEMINI_API_KEY`, `GOOGLE_API_KEY`), `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_CHAT_IDS`, `TAU_NET_IDENTITY` and `TAU_LANG`, each only when it is set ([cloud mode](../guides/cloud-mode.md), §5 of the [protocol](tau-network.md)).

## Remote access reference values (layer 0)

These are **not read by tau**. They are the personal values of your remote-access setup, kept in `.env` so they are in one place and out of the repository. `infra/remote/doctor.sh` prints the live values.

| Variable | Example |
|---|---|
| `TAU_TAILNET` | `tailXXXXXX.ts.net` |
| `TAU_MAC_HOSTNAME` | `my-mac` |
| `TAU_MAC_MAGICDNS` | `my-mac.tailXXXXXX.ts.net` |
| `TAU_MAC_TAILNET_IP` | `100.x.y.z` |
| `TAU_MAC_SSH_HOST_KEY_FP` | `SHA256:...` |
| `TAU_PHONE_HOSTNAME` | `my-phone` |
| `TAU_PHONE_TAILNET_IP` | `100.x.y.z` |
| `TAU_PHONE_SSH_KEY_FP` | `SHA256:...` |

The remote-access scripts themselves read `infra/remote/config.env` (defaults) and `config.local.env` (gitignored overrides): `TAU_REMOTE_USER`, `TAU_TMUX_SESSION` (`tau`), `TAU_TAILNET_V4` (`100.64.0.0/10`), `TAU_TAILNET_V6` (`fd7a:115c:a1e0::/48`), `TAU_SSHD_CONF` (`/etc/ssh/sshd_config.d/010-tau.conf`), `TAU_KEEPAWAKE` (`1`; set `0` and re-run `setup.sh` to drop the keep-awake agent; ignored once TauBar is installed) and `TAU_TAUBAR_APP` (empty: TauBar.app is looked for in `/Applications`, then `~/Applications`).

[TauBar](../guides/taubar.md) reads one variable of its own: `TAUBAR_HOME` puts its settings, state and log in one directory instead of `~/Library/Application Support/com.tau.taubar` and `~/Library/Logs/com.tau.taubar` (tests, a second copy).

## Tokens for SSH sessions

`~/.zshenv` (as written by `infra/remote/setup.sh`) sources `~/.config/tau/remote.env` **only in SSH sessions**. It is the place for tokens that tools need over the phone link:

| Variable | Used by |
|---|---|
| `CLAUDE_CODE_OAUTH_TOKEN` | Claude Code, when the macOS login keychain looks locked over SSH |
| `GH_TOKEN` | `gh` |
| `CLOUDFLARE_API_TOKEN` | `wrangler`, including the [backup upload](../guides/backups.md), and `tau net spine deploy` (which also reads it from `<TAU_HOME>/.env`) |

Keep the file `0600` inside a `0700` directory.

## TUI and terminal knobs

| Variable | Effect |
|---|---|
| `TAU_TUI_ASCII=1` | ASCII vocabulary and box borders for terminals without the block characters; the mark in Ember only |
| `TAU_TUI_PLAIN_STREAM=1` | stream every reply as plain text and parse the markdown once per segment |
| `TEXTUAL_ANIMATIONS=none` | no header motion |
| `TEXTUAL_COLOR_SYSTEM` | Textual's colour system override; with `--ansi` the `tau-ansi` 16-colour theme |

## Owner guard

The [owner guard](../guides/guard.md) has no variable of its own that changes policy: no variable, flag or config key switches it off for a channel. It reads the environment only here:

| Variable | Effect |
|---|---|
| `SSH_CONNECTION` | set by sshd; `tau guard setup`, `enroll` and `forget` refuse to run while it is set (exit 2), and a worker started with it shows no guard window |
| `TAU_GUARD_WINDOW` | `0` keeps the guard window off for every worker started under it (a hub, a `tau guard` command; the guard's own tests set it); display only, it changes no verdict |
| `PYTHONPATH`, `PYTHON_KEYRING_BACKEND`, `KEYCHAIN_PATH` | never reach the guard's worker: no module path can shadow it, and the template key always goes through keyring's macOS Keychain backend |
| `TAU_GUARD_TEST_CACHE` | tests only: where the opt-in real-model tests cache SFace and public-domain portraits (default `~/.cache/tau-guard-tests`) |
| `TAU_GUARD_SFACE` | tests only: a local SFace file for the opt-in real-model tests instead of a download |

The worker runs in `TAU_DATA_DIR/guard/` with the hub's environment minus those three, plus `OPENCV_LOG_LEVEL=ERROR` and `OPENCV_AVFOUNDATION_SKIP_AUTH=1`, so OpenCV never prints to a terminal or asks for the camera itself. Nothing needs setting by hand.

## Planned variables

!!! info "Planned"
    These names appear in the roadmap and are not read by any released package yet. Use them in `.env` if you are preparing the guides, and list them in your `.env.example` so `tau doctor` stays quiet.

| Variable | Issue | Meaning |
|---|---|---|
| `TAU_BACKUP_PUBKEY` | 018 | The `age` public key the backup bundle is encrypted to; the name used in the [backup guide](../guides/backups.md) |

## A complete example

```sh
# ~/.tau/.env
TAU_DATA_DIR=~/.local/share/tau
TAU_PROFILE=home
TAU_LANG=en

ANTHROPIC_API_KEY=sk-ant-...
# ANTHROPIC_WORKSPACE_ID=wrksp_...
# OPENAI_API_KEY=sk-...
# GEMINI_API_KEY=...

# only when the hub is not the Mac that runs Ollama
# TAU_OLLAMA_URL=http://my-mac.tailXXXXXX.ts.net:11434
```
