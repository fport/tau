# Environment variables

tau reads its environment once at start-up, then `<TAU_HOME>/.env` with python-dotenv. A variable that is already set in the environment is never overridden by the file. `.env` is gitignored and holds real values; `.env.example` next to it holds every name with an example value, and `tau doctor` warns about a name in `.env` that `.env.example` does not list.

Precedence for the settings that have a command-line option: option → environment → `.env` → `tau.toml` → default.

## Roots and identity

| Variable | Default | Meaning |
|---|---|---|
| `TAU_HOME` | the current directory when it holds `tau.toml`, else `~/.tau` | The configuration root: `tau.toml`, `.env`, `persona/`, `tools/`. `tau --home DIR` wins. |
| `TAU_DATA_DIR` | `~/.local/share/tau` | Mutable state: `sessions/`, `hub/`, `logs/`. Never inside a repository. |
| `TAU_PROFILE` | `home` | The active profile: `home`, `travel` or `sport`. `tau --profile NAME` wins and is exported as this variable. |
| `TAU_ROLE` | `hub` | The host role, `hub` or `node`. The hub service templates set `hub`; the mesh (layer 5) uses `node`. Any other value is a `ConfigError`. |
| `TAU_HUB_PORT` | `[hub] control_port` (7877) | Overrides the control API port. Must be a number. |
| `TAU_LANG` | `[ui] language` (`en`) | UI language, `en` or `tr`. `tau --lang` wins and is exported as this variable. |

## Model credentials

Which ones you need depends on the providers in `tau.toml`. Each provider accepts one of several *alternatives*; every variable of one alternative must be set.

| Provider | Alternatives |
|---|---|
| `bedrock` | `AWS_REGION` + `AWS_PROFILE` · `AWS_REGION` + `AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY` · `AWS_REGION` + `AWS_BEARER_TOKEN_BEDROCK`. A `region` in the role drops `AWS_REGION` from each alternative. |
| `anthropic` | `ANTHROPIC_API_KEY` (or the variable named by `params.api_key_env`). Optionally `ANTHROPIC_WORKSPACE_ID` for a key that is not scoped to a workspace. |
| `fake` | none |
| a `tau.providers` component | whatever its factory declares in `required_env` |

| Variable | Meaning |
|---|---|
| `AWS_REGION` | Bedrock region, e.g. `eu-central-1`. |
| `AWS_PROFILE` | A named profile from `~/.aws/config`. |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | Static AWS credentials. |
| `AWS_BEARER_TOKEN_BEDROCK` | A Bedrock API key (bearer token). |
| `ANTHROPIC_API_KEY` | The Anthropic key, `sk-ant-…`. |
| `ANTHROPIC_WORKSPACE_ID` | `wrksp_…`; sent as the `anthropic-workspace-id` header. Without it a non-scoped key gets a 400 from the API. |

A missing credential stops `tau chat` with exit 2 and a message naming the variables; `tau tui` opens its settings screen on the Credentials section instead; `tau doctor` reports it without starting anything. `/settings set NAME` (terminal, hidden prompt) and the TUI's Credentials section write a value to `.env` (mode `0600`) and export it to the running process.

## Telegram

Read by the `telegram` hub service (see [Telegram](../guides/telegram.md)). Without a token, or without an allowed chat, the service stays idle and the hub runs on.

| Variable | Meaning |
|---|---|
| `TELEGRAM_BOT_TOKEN` | The bot token from @BotFather, `123456789:AA…`. A password: it never appears in logs, `/status` or `tau doctor`. |
| `TELEGRAM_ALLOWED_CHAT_IDS` | The chat ids the bot answers, comma-separated. Messages from any other chat are dropped unanswered. |

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

The remote-access scripts themselves read `infra/remote/config.env` (defaults) and `config.local.env` (gitignored overrides): `TAU_REMOTE_USER`, `TAU_TMUX_SESSION` (`tau`), `TAU_TAILNET_V4` (`100.64.0.0/10`), `TAU_TAILNET_V6` (`fd7a:115c:a1e0::/48`), `TAU_SSHD_CONF` (`/etc/ssh/sshd_config.d/010-tau.conf`) and `TAU_KEEPAWAKE` (`1`; set `0` and re-run `setup.sh` to drop the keep-awake agent).

## Tokens for SSH sessions

`~/.zshenv` (as written by `infra/remote/setup.sh`) sources `~/.config/tau/remote.env` **only in SSH sessions**. It is the place for tokens that tools need over the phone link:

| Variable | Used by |
|---|---|
| `CLAUDE_CODE_OAUTH_TOKEN` | Claude Code, when the macOS login keychain looks locked over SSH |
| `GH_TOKEN` | `gh` |
| `CLOUDFLARE_API_TOKEN` | `wrangler`, including the [backup upload](../guides/backups.md) |

Keep the file `0600` inside a `0700` directory.

## TUI and terminal knobs

| Variable | Effect |
|---|---|
| `TAU_TUI_ASCII=1` | ASCII vocabulary and box borders for terminals without the block characters; the mark in Ember only |
| `TAU_TUI_PLAIN_STREAM=1` | stream every reply as plain text and parse the markdown once per segment |
| `TEXTUAL_ANIMATIONS=none` | no header motion |
| `TEXTUAL_COLOR_SYSTEM` | Textual's colour system override; with `--ansi` the `tau-ansi` 16-colour theme |

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

# AWS_REGION=eu-central-1
# AWS_PROFILE=tau
```
