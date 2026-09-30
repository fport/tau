# First run

There are two ways to set tau up. The quick one is inside the interface: `tau tui` on a machine with no configuration opens a setup screen, and `/settings` (or F10) edits everything afterwards. The other is the files: `tau init` writes them, you edit `tau.toml` and `.env` by hand, `tau doctor` checks them. Both end in the same two files, so you can mix them freely. This page shows the interface first, then the files, then `tau doctor` line by line and the first conversation.

## In the interface: `tau tui`

```sh
tau tui
```

With no `tau.toml` anywhere (`TAU_HOME`, the current directory, `~/.tau`) the setup screen opens instead of the chat:

```text
 ╭──────────────────────────────────────────────────────────────╮
 │ ◆ Welcome to tau · first run                                 │
 │                                                              │
 │ Nothing is configured yet. Pick a home directory, the model  │
 │ provider and the UI language; tau writes tau.toml and the    │
 │ persona files there.                                         │
 │                                                              │
 │ home directory  ~/.tau                                       │
 │ provider        anthropic · credentials found             ▼  │
 │ UI language     en                                        ▼  │
 │                           Create                             │
 │ tab fields · enter / ctrl+s / F2 create · esc quit           │
 ╰──────────────────────────────────────────────────────────────╯
```

- **home directory** is where `tau.toml`, `.env` and `persona/` go; `~/.tau` unless `TAU_HOME` or `tau --home` says otherwise. A directory that already holds a `tau.toml` is used as it is.
- **provider** is detected from the environment and `<home>/.env` the way `tau init` does it: `proxy` when a model-proxy key (`TAU_PROXY_KEY_BRAIN`) is present, else `anthropic` when `ANTHROPIC_API_KEY` is, else `bedrock` when AWS credentials are, else `fake` (no key needed, scripted replies). Change it if you like.
- **UI language** relabels the screen as you switch it.

**Create** runs the same code as `tau init`, then the chat opens on the new home. Esc leaves without writing anything (exit code 2, the same as a missing config).

When the config exists but the role's provider has no credentials, `tau tui` still opens: the settings screen appears on its **Credentials** section with the missing variables marked `◆ needed`, the composer says *Add credentials in /settings*, and the chat starts as soon as a save gives the provider its key. A role that runs on its fallback provider (when you defined one) is announced with one notice line (`brain: using the fallback provider anthropic (bedrock has no credentials). Add them in /settings.`).

`/settings` (Turkish alias `/ayarlar`) or F10 opens the same editor at any time:

```text
 τ tau  home · 20260929-120000-abcd                                  brain · en
 ╭────────────────────────────────────────────────────────────────────────────╮
 │ ◆ Settings                                                                 │
 │                                                                            │
 │ Model roles        brain                                                   │
 │ Credentials        provider     anthropic                              ▼   │
 │ Interface          model id     claude-sonnet-5                            │
 │ Agent              max tokens   4096                                       │
 │ Doctor             fallback     (none)                                 ▼   │
 │ Files              fallback id                                             │
 │                    ✓ credentials ok                                        │
 │                                                                            │
 │                    fast                                                    │
 │                    …                                                       │
 │ ↑↓ section · tab fields · ctrl+s / F2 save · esc close                     │
 ╰────────────────────────────────────────────────────────────────────────────╯
```

| Section | What you edit |
|---|---|
| Model roles | Per role: provider (every installed provider; a planned one, which a later issue builds, is listed in a note and cannot be chosen), model id (for `proxy`, the model group), max tokens, an optional fallback provider and model id, and the credential status of the role (`credentials ok`, `missing TAU_PROXY_KEY_BRAIN`, `missing … · fallback anthropic in use`, `no credentials needed`). A role's `budget` is edited in `tau.toml` only. |
| Credentials | Every variable the configured providers need, then every other provider's, then every name in `.env.example` and `.env`. Each row says `set · sk-…abcd` or `not set`, and `(from the environment; .env does not override it)` when your shell sets the variable. Keys, tokens, secrets and passwords take a hidden input; plain settings such as `TAU_PROXY_URL` or `TAU_PROFILE` a visible one. **clear** removes a value. Values are never shown again after you type them. |
| Interface | UI language (`en`/`tr`, applied on save) and the profile (`TAU_PROFILE` in `.env`). |
| Agent | `context`, `window_size`, `max_turns`, `max_total_tokens` with the same rules as the file. |
| Doctor | The `tau doctor` checks with `✓`, `◆`, `✗` and `▸` glyphs. |
| Files | The paths of `tau.toml`, `.env`, `.env.example`, `persona/persona.md` and `persona/user.md` with a mark for the ones that exist; the persona files are edited in your editor and re-read before the next turn. |

`ctrl+s` (F2 over mosh, where `ctrl+s` may be swallowed by flow control) validates and saves: a value the config would refuse is reported in the status line and nothing is written; a valid save writes `tau.toml` with its comments intact and `.env` with mode `0600`, then rebuilds the agent on the same session when a role, an agent option, a credential or the profile changed (`Settings saved; model reloaded.`). Esc closes without saving. Nothing here ever prints, logs or stores a credential value in clear.

## In the files: `tau init`

Everything the interface does can be done in the terminal, and `tau chat` has a smaller `/settings` too (see [Talk to tau](talk.md)). `tau init` writes the files:

```sh
tau init
```

Without options the wizard:

1. Resolves the configuration root (`TAU_HOME`, else `~/.tau`).
2. Looks for model credentials in the environment and in `<root>/.env`.
3. Asks for the UI language, `en` or `tr`.
4. Writes `tau.toml`, `persona/persona.md`, `persona/user.example.md`, `persona/user.md` and `.env.example`.

Every choice has a flag, so a script can run it without questions:

```sh
tau init --home ~/.tau --provider anthropic --language en --profile home --yes
```

| Option | Effect |
|---|---|
| `--home DIR` | The root to create. Default: `TAU_HOME`, else `~/.tau`. |
| `--provider NAME` | Provider for the `brain` and `fast` roles: `proxy`, `anthropic`, `bedrock` or `fake`. Default: the first one with credentials, in that order. `proxy` writes the shipped file as is (every role on the proxy, with budgets); any other provider also points `local` at Ollama directly and leaves the budgets out. |
| `--language LANG` | UI language, `en` or `tr`. Asked when omitted, unless `--yes`. |
| `--profile NAME` | Appends `TAU_PROFILE=NAME` to `<root>/.env` if it is not set there. |
| `-y`, `--yes` | Ask nothing; use defaults for whatever is not given. |
| `--force` | Overwrite an existing `tau.toml` and `persona.md`. `user.md` and `.env.example` are never overwritten. |

A run with no credentials anywhere ends like this (paths shortened):

```text
Provider: fake. No model credentials were found in the environment or <root>/.env, so both roles use the scripted 'fake' provider. Add ANTHROPIC_API_KEY to <root>/.env (names are in <root>/.env.example) and run `tau init --force`, or edit tau.toml.
wrote <root>/tau.toml
wrote <root>/persona/persona.md
wrote <root>/persona/user.example.md
wrote <root>/persona/user.md
wrote <root>/.env.example
Configuration root: <root> (UI language: en).
Next: edit persona/user.md, then run `tau doctor` and `tau chat`.
```

## Try it without credentials

The `fake` provider is a scripted model that ships with `tau-core`. It needs no key, never touches the network and answers `Okay.` to everything. It is how the test suite runs, and it is enough to see the REPL, the TUI, the slash commands, sessions and the approval flow.

```sh
tau init --provider fake --yes
tau chat
```

Ask tau anything, then try `/tools`, `/status` and `/sessions`. When you want real answers, add credentials and continue below.

## Credentials in `.env`

tau reads credentials from the environment and from `<root>/.env`. A variable that is already set in your shell wins; the file never overrides it. `.env` is yours and stays out of any repository; `.env.example` next to it only lists the names.

Anthropic is tau's model provider. Every setup starts with its key in `.env`:

```sh
ANTHROPIC_API_KEY=sk-ant-...
# Only for a key that is not scoped to a workspace (Console → Settings → Workspaces):
# ANTHROPIC_WORKSPACE_ID=wrksp_...
```

Then pick how tau reaches it:

=== "Directly (no Docker)"

    The key is all you need. Let the wizard rewrite the roles for it, open the **Model roles** section of `/settings` in the TUI, or edit `tau.toml` by hand:

    ```sh
    tau init --force          # picks proxy > anthropic > bedrock > fake from what .env now holds
    tau doctor
    ```

    `brain` and `fast` call Anthropic directly and `local` calls Ollama directly. There are no budgets in this mode; set a spend limit on the Anthropic workspace in the Console instead.

=== "Through the model proxy"

    The default of the shipped `tau.toml`: every role goes through a LiteLLM proxy in Docker with a hard budget per role. The proxy's own secrets and the three role keys are generated for you:

    ```sh
    infra/litellm/proxy.sh init    # LITELLM_MASTER_KEY, LITELLM_SALT_KEY, TAU_PROXY_DB_PASSWORD into .env
    infra/litellm/proxy.sh up
    tau init --provider proxy --force   # not needed in a checkout: its tau.toml already uses the proxy
    tau proxy keys                 # TAU_PROXY_KEY_BRAIN, _FAST, _LOCAL into .env
    tau doctor
    ```

    [Model proxy and budgets](../guides/model-proxy.md) walks through it.

=== "Amazon Bedrock (optional)"

    Bedrock is not part of tau's own setup, but it stays available as a direct provider. `AWS_REGION` plus one of three credential forms:

    ```sh
    AWS_REGION=eu-central-1
    AWS_PROFILE=tau
    # or
    # AWS_ACCESS_KEY_ID=AKIAXXXXXXXXXXXXXXXX
    # AWS_SECRET_ACCESS_KEY=...
    # or
    # AWS_BEARER_TOKEN_BEDROCK=...
    ```

    Then `tau init --provider bedrock --force`.

Inside a session, `/settings set ANTHROPIC_API_KEY` (terminal) asks for the value without echoing it and writes it to `.env`; the TUI's **Credentials** section does the same with a hidden input.

!!! note "Proxy or direct"
    The shipped `tau.toml` (and the repository's own) puts every role on `provider = "proxy"`. `tau init` writes it that way only when it finds a proxy key; with just `ANTHROPIC_API_KEY` it writes the direct providers instead. `tau doctor` says which provider each role uses and whether it has what it needs.

If a role has no usable credentials, `tau chat` stops before starting, with exit code 2 and a message naming the missing variables; `tau tui` opens on the settings screen instead (see above):

```text
Missing model credentials for role 'brain' (proxy). Add these variables to .env: TAU_PROXY_KEY_BRAIN
Example names are in .env.example.
```

## Your facts: `persona/user.md`

`persona/user.md` is what tau knows about you: how to address you, your name, city, working hours, preferences. It is created from the made-up example and is never overwritten. Without it, or with it empty, tau addresses you formally and knows nothing about you.

Edit it in any editor. The change applies on the next model call; there is nothing to restart. HTML comments in the file are notes for you and never reach the model.

!!! warning
    `user.md` is life data. Keep it in the configuration root and out of any repository or sync folder you do not control. The [backup guide](../guides/backups.md) covers how to copy it safely.

## `tau doctor`, line by line

```sh
tau doctor
```

A first run in a checkout, with `ANTHROPIC_API_KEY` in `.env` but before the model proxy is set up and before you wrote a `user.md`:

```text
ok   config: <root>/tau.toml loaded
fail role brain: provider 'proxy' is missing TAU_PROXY_KEY_BRAIN (names are in .env.example)
fail role fast: provider 'proxy' is missing TAU_PROXY_KEY_FAST (names are in .env.example)
fail role local: provider 'proxy' is missing TAU_PROXY_KEY_LOCAL (names are in .env.example)
warn proxy: not answering at http://127.0.0.1:4000; start it with infra/litellm/proxy.sh up (model calls of the proxy roles fail until then)
ok   sessions: backend 'file' opens under ~/.local/share/tau/sessions
ok   persona: <root>/persona/persona.md present and non-empty
warn persona: <root>/persona/user.md is missing: tau addresses you formally and knows nothing about you (start from persona/user.example.md)
ok   .env: every name in .env is listed in .env.example
ok   components: every component loads
info hub: hub is not running (nothing answers on http://127.0.0.1:7877/health)
info telegram: not configured (TELEGRAM_BOT_TOKEN is not set)
12 checks: 5 ok, 2 warnings, 3 failed
```

The checkout's `tau.toml` sends every role through the proxy, so the three roles fail until [Model proxy and budgets](../guides/model-proxy.md) is done; once it is, each role line turns `ok` and one `proxy <role>` line per role reports its spend (`ok   proxy brain: $0.00 of $15.00 per 1mo, within budget`). A root that `tau init` wrote for the direct `anthropic` provider has no proxy lines at all.

| Check | What it verifies | When it fails |
|---|---|---|
| `config` | `tau.toml` parses and every provider and backend name is known. Unknown top-level tables are a warning. | A missing or invalid file: `fail`, and no further checks run. |
| `role <name>` | Each role's provider exists and has credentials, without building a client. A `warn` means the fallback will be used, the provider is planned (a later issue builds it), or the role has a `budget` its provider cannot enforce (only `proxy` can). | No credentials for the primary or the fallback: `fail`, with the missing names. |
| `proxy` | With at least one `proxy` role: whether the model proxy answers. | Never; `warn` when it does not answer. |
| `proxy <role>` | Whether the proxy accepts the role's key, and the key's spend against its cap (`$0.40 of $15.00 per 1mo, within budget`). | The proxy refuses the key: `fail`, run `tau proxy keys`. A cap that differs from `tau.toml` or a role without a budget: `warn`. |
| `sessions` | The `[sessions] backend` opens. For `file` it names the directory. | The backend cannot open its store. |
| `persona` (twice) | `persona.md` is present and non-empty; `user.md` is present. | A missing or empty `persona.md` is a `fail`; a missing `user.md` is only a `warn`. |
| `.env` | Every name in `.env` is listed in `.env.example`, so a typo in a variable name is caught. `info` when there is no `.env`. | Never; unknown names are a `warn`. Add your own names to `.env.example` to silence it. |
| `components` | Every `tau.*` entry point loads. | A broken component: the distribution and its error are printed. |
| `hub` | Whether a hub answers on `http://127.0.0.1:<control_port>/health`. Information only. | Never. `warn` when something answers with an error. |
| `telegram` | Whether the [Telegram](../guides/telegram.md) channel is configured and, when the hub runs, the poller's state (`polling as @bot`, retrying, stopped). `info` without a token. | A token the Bot API rejected: `fail`. An empty or invalid `TELEGRAM_ALLOWED_CHAT_IDS` or a poller that keeps retrying: `warn`. |

Exit code 1 means at least one `fail`. `tau doctor --json` prints the same checks as JSON for scripts.

!!! tip
    `tau doctor` never starts a model, opens a network connection to a provider or writes anything except the session directory it opens. It only asks the local model proxy (and the hub) how they are. Run it as often as you like.

## Your first conversation

```sh
tau chat
```

The banner names the profile and the new session id. Type a message; the reply streams under `tau>`. Tool calls appear as dim indented lines:

```text
you> what time is it?
  ⚙ current_time (tier 0)
  ✓ current_time: 29.09.2026 17:38:26, Tuesday (Europe/Istanbul)
tau> It is 17:38 on Tuesday, 29 September.
```

When tau wants to use a tier-2 tool (one that acts on the physical world), it stops and asks. The shipped `demo_physical_action` tool exists exactly to show this:

```text
⚠️  Approval needed (tier 2)
  Tool: demo_physical_action
  Arguments: {"action": "turn on the desk lamp"}
  Effect: Demo: simulates a physical action; no real device moves.
  Approve? [y/N]
```

`y`, `yes`, `e` or `evet` approves. Anything else, including Enter and Ctrl-D, rejects; tau reads the refusal and tells you briefly. Nothing ever approves on its own. The rules are in [Tiers and approvals](../reference/tiers.md).

Every session is on disk from the first message. `/sessions` lists them, `/resume` continues the last one, `/quit` leaves. Next: [Configure](configure.md) and [Talk to tau](talk.md).
