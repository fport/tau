# First run

This page follows `tau init`, `tau doctor` and the first `tau chat` in detail: what the wizard asks, where credentials go, how to try tau without any account, and what every line of the doctor means.

## The init wizard

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
| `--provider NAME` | Provider for the `brain` and `fast` roles: `bedrock`, `anthropic` or `fake`. Default: the first one with credentials. |
| `--language LANG` | UI language, `en` or `tr`. Asked when omitted, unless `--yes`. |
| `--profile NAME` | Appends `TAU_PROFILE=NAME` to `<root>/.env` if it is not set there. |
| `-y`, `--yes` | Ask nothing; use defaults for whatever is not given. |
| `--force` | Overwrite an existing `tau.toml` and `persona.md`. `user.md` and `.env.example` are never overwritten. |

A run with no credentials anywhere ends like this (paths shortened):

```text
Provider: fake. No model credentials were found in the environment or <root>/.env, so both roles use the scripted 'fake' provider. Add AWS or Anthropic credentials to <root>/.env (names are in <root>/.env.example) and run `tau init --force`, or edit tau.toml.
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

Pick one provider and uncomment its lines in `.env`:

=== "Anthropic"

    ```sh
    ANTHROPIC_API_KEY=sk-ant-...
    # Only for a key that is not scoped to a workspace (Console → Settings → Workspaces):
    # ANTHROPIC_WORKSPACE_ID=wrksp_...
    ```

=== "Amazon Bedrock"

    `AWS_REGION` plus one of three credential forms:

    ```sh
    AWS_REGION=eu-central-1
    AWS_PROFILE=tau
    # or
    # AWS_ACCESS_KEY_ID=AKIAXXXXXXXXXXXXXXXX
    # AWS_SECRET_ACCESS_KEY=...
    # or
    # AWS_BEARER_TOKEN_BEDROCK=...
    ```

Then let the wizard rewrite the roles for that provider, or edit `tau.toml` by hand:

```sh
tau init --force          # picks bedrock > anthropic > fake from what .env now holds
tau doctor
```

!!! note "The fallback rule"
    The shipped `tau.toml` maps `brain` and `fast` to Bedrock with an Anthropic **fallback**. The fallback is used only when the primary provider has no credentials. So a `.env` that holds only `ANTHROPIC_API_KEY` works with the shipped file as is; `tau doctor` says which provider each role will actually use.

If a role has no usable credentials, `tau chat` and `tau tui` stop before starting, with exit code 2 and a message naming the missing variables:

```text
Missing model credentials for role 'brain' (bedrock). Add these variables to .env: AWS_REGION, AWS_PROFILE
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

A typical first run in a checkout, before you added credentials or a `user.md`:

```text
ok   config: <root>/tau.toml loaded
warn role brain: provider 'bedrock' is missing AWS_REGION, AWS_PROFILE; the fallback 'anthropic' has credentials and will be used
warn role fast: provider 'bedrock' is missing AWS_REGION, AWS_PROFILE; the fallback 'anthropic' has credentials and will be used
warn role local: provider 'ollama' is not available until issue 012
ok   sessions: backend 'file' opens under ~/.local/share/tau/sessions
ok   persona: <root>/persona/persona.md present and non-empty
warn persona: <root>/persona/user.md is missing: tau addresses you formally and knows nothing about you (start from persona/user.example.md)
ok   .env: every name in .env is listed in .env.example
ok   components: every component loads
info hub: hub is not running (nothing answers on http://127.0.0.1:7877/health)
10 checks: 5 ok, 4 warnings, 0 failed
```

| Check | What it verifies | When it fails |
|---|---|---|
| `config` | `tau.toml` parses and every provider and backend name is known. Unknown top-level tables are a warning. | A missing or invalid file: `fail`, and no further checks run. |
| `role <name>` | Each role's provider exists and has credentials, without building a client. A `warn` means the fallback will be used, or the provider is planned (`ollama`, issue 012). | No credentials for the primary or the fallback: `fail`, with the missing names. |
| `sessions` | The `[sessions] backend` opens. For `file` it names the directory. | The backend cannot open its store. |
| `persona` (twice) | `persona.md` is present and non-empty; `user.md` is present. | A missing or empty `persona.md` is a `fail`; a missing `user.md` is only a `warn`. |
| `.env` | Every name in `.env` is listed in `.env.example`, so a typo in a variable name is caught. `info` when there is no `.env`. | Never; unknown names are a `warn`. Add your own names to `.env.example` to silence it. |
| `components` | Every `tau.*` entry point loads. | A broken component: the distribution and its error are printed. |
| `hub` | Whether a hub answers on `http://127.0.0.1:<control_port>/health`. Information only. | Never. `warn` when something answers with an error. |

Exit code 1 means at least one `fail`. `tau doctor --json` prints the same checks as JSON for scripts.

!!! tip
    `tau doctor` never starts a model, opens a network connection to a provider or writes anything except the session directory it opens. Run it as often as you like.

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
