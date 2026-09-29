# Install

tau is a set of Python packages. `tau-core` holds the agent and the `tau` command; `tau-tui` adds the Textual interface. You install them once, create a configuration root with `tau init`, check it with `tau doctor`, and talk.

## Requirements

- **Python 3.12 or newer.** Nothing older works; the packages declare `requires-python = ">=3.12"`.
- **[uv](https://docs.astral.sh/uv/)**, the Python package manager tau's workspace is built on. It installs its own Python if you have none.
- macOS or Linux. The hub runs on a MacBook today and on a Raspberry Pi 5 later; the same code runs on both.
- A model provider, or none. tau ships a scripted `fake` provider so you can try everything without an account. Real answers need Amazon Bedrock or Anthropic credentials (see [First run](first-run.md)).

=== "macOS"

    ```sh
    brew install uv
    uv python install 3.12
    ```

=== "Linux"

    ```sh
    curl -LsSf https://astral.sh/uv/install.sh | sh
    uv python install 3.12
    ```

!!! tip
    `uv python install 3.12` is optional. `uv` downloads a matching interpreter on demand when a project needs one.

## Install the packages

!!! note "From the repository instead"
    Contributors and anyone who wants the unreleased `main` branch install from the uv
    workspace and run every command through `uv run`:

    ```sh
    git clone https://github.com/fport/tau.git
    cd tau
    uv sync --all-packages --group dev
    uv run tau --help
    ```

    Everything below applies unchanged; read `tau …` as `uv run tau …` while you are inside the checkout. The repository root holds a `tau.toml`, so it is also your configuration root until you run `tau init` elsewhere.

Once the packages are published, the documented install is one `uv tool` command that puts `tau` on your `PATH` with the TUI included:

```sh
uv tool install tau-core --with tau-tui
tau --help
```

`uv tool install` keeps tau in its own virtual environment and never touches your system Python. Upgrade later with `uv tool upgrade tau-core`.

## Create a configuration root

`tau init` writes the files tau needs into a **configuration root**, `~/.tau` by default:

```sh
tau init
```

It asks one question, the UI language (`en` or `tr`), and then writes:

| File | What it is |
|---|---|
| `tau.toml` | Which provider and model id serve each role, plus the agent, sessions, hub and UI settings. See [Configure](configure.md). |
| `persona/persona.md` | tau's character. Tracked, public, contains nothing about you. |
| `persona/user.example.md` | A made-up example of the facts file. |
| `persona/user.md` | Your copy of the example. Edit it; it is the only place for real facts about you. |
| `.env.example` | The names of every credential and setting `tau doctor` knows about. Your real values go into `.env` next to it. |

`tau init` picks the provider from the credentials it can see: Bedrock first, then Anthropic, else `fake`. With no credentials at all you get a working configuration on the `fake` provider and a note saying so. Existing files are kept unless you pass `--force`; `user.md` and `.env.example` are never overwritten.

!!! note "Where is the root?"
    tau looks for `tau.toml` in this order: the `--home DIR` option, the `TAU_HOME` variable, the current directory when it holds a `tau.toml`, then `~/.tau`. Mutable state (sessions, logs, hub files) lives elsewhere, in `TAU_DATA_DIR`, default `~/.local/share/tau`. See [Environment variables](../reference/environment.md).

## Check the installation

```sh
tau doctor
```

`tau doctor` reads the config, checks each role's provider and credentials without building a model client, opens the session store, reads the persona files, compares `.env` with `.env.example`, loads every component and probes the hub. It exits 1 only when a check fails; warnings are fine to start with. [First run](first-run.md) walks through the output line by line.

## Talk

```sh
tau chat
```

```text
tau ready. Profile: home, session: 20260929-173826-f949. Commands: /help, /tools, /sessions, /resume, /new, /session, /compact, /clear, /status, /model, /lang, /quit (Ctrl-D also quits).
you>
```

Type a message and Enter. `/help` lists the commands, `/quit` leaves. On the `fake` provider tau answers `Okay.` to everything; that is the scripted model, not a bug. Add credentials and re-run `tau init --force` (or edit `tau.toml`) for real answers.

The full-screen interface is one more command:

```sh
tau tui
```

[Talk to tau](talk.md) compares the two and lists every key and command.

## Next

- [First run](first-run.md): credentials in `.env`, the fake provider, `tau doctor` explained.
- [Configure](configure.md): a walk through `tau.toml`.
- [Run tau as a service](../guides/hub-service.md) when you want the hub to stay up.
