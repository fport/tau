# Install

tau is a set of Python packages. `tau-core` holds the agent and the `tau` command; `tau-tui` adds the Textual interface. You install them once, create a configuration root with `tau init`, check it with `tau doctor`, and talk.

## The one-line installer

On macOS and Linux, including a Raspberry Pi, one command installs tau and asks what you want:

```sh
curl -fsSL https://tau.getporti.com/install.sh | sh
```

- **What it installs.** It installs [uv](https://docs.astral.sh/uv/) when it is missing, then tau with `uv tool install tau-core --with tau-tui`, and starts `tau setup`. It never runs `sudo`. Read it first with `curl -fsSL https://tau.getporti.com/install.sh | less`.
- **What `tau setup` does.** It shows a checklist of features: the terminal UI, sub-taus, Telegram, remote access, the owner guard, the tau network, start at login and cloud mode. It installs their packages with one command, then sets them up: `tau init` (the provider and its key, below), a short "about you" for `persona/user.md`, each feature's steps and `tau doctor`.
- **Later.** Run `tau setup` again to add a feature; what is set up is never asked again. `tau setup --upgrade` upgrades tau.

[`tau setup`](../reference/setup.md) lists every feature and option. The rest of this page is the manual way, one step at a time.

## Requirements

- **Python 3.12 or newer.** Nothing older works; the packages declare `requires-python = ">=3.12"`.
- **[uv](https://docs.astral.sh/uv/)**, the Python package manager tau's workspace is built on. It installs its own Python if you have none.
- macOS or Linux. The hub runs on a MacBook today and on a Raspberry Pi 5 later; the same code runs on both.
- A model provider, or none. tau ships a scripted `fake` provider so you can try everything without an account. Real answers need an API key from Anthropic, OpenAI or Google Gemini, or a local model through [Ollama](https://ollama.com) (see [First run](first-run.md)). tau calls the provider directly and enforces a spend cap per role itself, so nothing else needs to run next to it ([Models and budgets](../guides/models-and-budgets.md)).

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

    Everything below applies unchanged; read `tau …` as `uv run tau …` while you are inside the checkout. The repository root holds a `tau.toml`, so it is also your configuration root until you run `tau init` elsewhere. That file puts `brain` and `fast` on Anthropic with budgets and `local` on Ollama, so it needs `ANTHROPIC_API_KEY` in the checkout's `.env`; with another provider, use a root that `tau init` wrote for it.

The documented install is one `uv tool` command that puts `tau` on your `PATH` with the TUI, the network (`tau-net`) and sub-taus (`tau-sub`) included:

```sh
uv tool install tau-core --with tau-tui --with tau-net --with tau-sub
tau --help
```

`uv tool install` keeps tau in its own virtual environment and never touches your system Python. Upgrade later with `tau setup --upgrade`. `uv tool upgrade tau-core` works too, as long as `tau setup` has not installed anything: `tau setup` pins the packages to one version.

## Create a configuration root

`tau init` writes the files tau needs into a **configuration root**, `~/.tau` by default:

```sh
tau init
```

It asks the UI language (`en` or `tr`). When it finds no model key in the environment or `~/.tau/.env`, it then asks which provider you use (`anthropic`, `openai` or `gemini`) and that provider's key, typed hidden. It checks the key with one small request to the provider (the list of models, which costs nothing) and writes it to `~/.tau/.env`, which it keeps at mode `0600`:

```text
UI language (en, tr) [en]: en
No model key was found in the environment or ~/.tau/.env. tau needs a key from one provider (`tau init --yes` sets up the scripted 'fake' provider without one).
Provider (anthropic, openai, gemini) [anthropic]: anthropic
ANTHROPIC_API_KEY (hidden; empty skips):
Checking the key with one small request to anthropic...
anthropic accepted the key.
```

A key the provider refuses, or a check that gets no answer, stops `tau init` before it writes anything; `--no-check` skips the request. An empty key skips the key: the configuration is written for that provider, and you add the key to `.env` later. `--yes` asks nothing and keeps the old behaviour: it picks the provider from the credentials it finds, else `fake`. Then `tau init` writes:

| File | What it is |
|---|---|
| `tau.toml` | Which provider and model id serve each role, plus the agent, sessions, hub and UI settings. See [Configure](configure.md). |
| `persona/persona.md` | tau's character. Tracked, public, contains nothing about you. |
| `persona/user.example.md` | A made-up example of the facts file. |
| `persona/user.md` | Your copy of the example. Edit it; it is the only place for real facts about you. |
| `.env.example` | The names of every credential and setting `tau doctor` knows about. Your real values go into `.env` next to it. |
| `.env` | Your key, when you typed one (mode `0600`, appended to an existing file without touching its other lines). |

When credentials are already there, `tau init` picks the provider from them and asks nothing about keys: Anthropic (`ANTHROPIC_API_KEY`), then OpenAI (`OPENAI_API_KEY`), then Gemini (`GEMINI_API_KEY` or `GOOGLE_API_KEY`), then Bedrock. It writes that provider's models for `brain` and `fast`, keeps the budgets tau enforces for them ($15 a month for `brain`, $1 a day for `fast`), and puts `local` on Ollama with `fast` as its failover. `tau init --yes` with no credentials at all gives you a working configuration on the `fake` provider and a note saying so. Existing files are kept unless you pass `--force`; `user.md` and `.env.example` are never overwritten.

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
tau ready. Profile: home, session: 20260929-173826-f949. Commands: /help, /tools, /sessions, /resume, /new, /session, /compact, /clear, /status, /model, /lang, /settings, /quit (Ctrl-D also quits).
you>
```

Type a message and Enter. `/help` lists the commands, `/quit` leaves. On the `fake` provider tau answers `Okay.` to everything; that is the scripted model, not a bug. For real answers add credentials: `/settings` in the TUI (or `/settings set ANTHROPIC_API_KEY` here) writes them to `.env` and switches the role, or put them in `.env` yourself and re-run `tau init --force`.

The full-screen interface is one more command:

```sh
tau tui
```

[Talk to tau](talk.md) compares the two and lists every key and command.

## Next

- [First run](first-run.md): credentials in `.env`, the fake provider, `tau doctor` explained.
- [Configure](configure.md): a walk through `tau.toml`.
- [Models and budgets](../guides/models-and-budgets.md): providers, the local model, a hard spend cap per role.
- [Run tau as a service](../guides/hub-service.md) when you want the hub to stay up.
