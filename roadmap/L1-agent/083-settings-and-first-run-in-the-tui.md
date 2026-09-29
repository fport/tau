# 083 · Settings and first run inside the TUI: edit tau.toml and .env from `/settings`, set up without `tau init`

Status: done
Type: AFK
Layer: L1 · Agent
Packages: tau-core, tau-tui
Blocked by: none

## What to build

After `uv tool install tau-core --with tau-tui` a new user has no idea where tau is configured: the model roles, the credentials, the UI language and the profile live in `tau.toml` and `.env` under `TAU_HOME`, and the only help is the `tau init` wizard and a warning line at start-up. The bootstrap config becomes editable from the channels, and the TUI guides a user who has nothing configured yet.

- **tau-core `tau_core.settings`**: a small, testable editor for the two files. `tau.toml` through tomlkit (`load_document`, `set_role`, `set_ui_language`, `set_agent_option` with `Config`'s validation, `save_document` atomic and mode-preserving, `check_document` so a document `Config` refuses is never written, `validate`); `.env` through python-dotenv (`set_credential` / `clear_credential`, file created and kept at mode `0600`, `export=True` updates the running process); `credential_names_for`, `credential_status` (ok · none · missing · fallback · unavailable), `known_env_names`, `known_providers`, `describe_home`, `default_home`, `mask` (`sk-…abcd`), `report_lines`. No function returns, logs or prints a credential value. `Config.load` raises `ConfigNotFound` when there is no `tau.toml`.
- **`/settings`** (`/ayarlar`, `/ayar`) in the shared command spec. Terminal: the report (roles → provider · model id · credential status, language, profile, context, files, how to change things) and the setters `language en|tr`, `profile NAME`, `model ROLE PROVIDER MODEL_ID`, `set NAME` (value read with `getpass`, never echoed), `clear NAME`; a change that affects the model rebuilds the agent on the same session.
- **TUI `SettingsScreen`** (`/settings [section]`, F10): a keyboard-only modal in the family of the approval dialog — sections Model roles · Credentials · Interface · Agent · Doctor · Files on the left, the form on the right, a status line for validation errors, `ctrl+s` / F2 to save (the app's F2 picker is disabled while it is up), Esc to close. Works at 80x24 and 50x24; the header stays visible above it. A save validates, writes, validates the saved files, applies the UI language live and rebuilds the agent when a role, an agent option, a credential or the profile changed (`Settings saved; model reloaded.` / `Settings saved.`). Credential inputs are password fields; the value never reaches a `Static`, a notice, the `text` oracle, a screenshot or the log. Refused while a turn is busy.
- **First run in the TUI**: `tau tui` with no `tau.toml` opens `SetupScreen` (home directory, provider detected like `tau init` with `fake` as the credential-free option, UI language); **Create** runs `init_home` and the command continues into the app on that home; Esc is exit code 2. `Config.load` ok but `MissingCredentials`: the app opens without an agent on the Credentials section with the missing names marked, the composer takes only `/settings`, `/help`, `/lang`, `/quit` and says *Add credentials in /settings*; the agent is built once a save gives the provider its key. A corrupt `tau.toml` and an unknown `--resume` id keep exit code 2.
- The start-up fallback warning (`role brain: bedrock has no credentials …`) stays a terminal line in `tau chat`; the TUI shows a transcript notice (`brain: using the fallback provider anthropic (bedrock has no credentials). Add them in /settings.`) read off the model's `tau_fallback_of` tag.

## Acceptance criteria

- [x] `tau_core.settings` round-trips `tau.toml` with comments intact, writes atomically, keeps a private mode, refuses a document `Config` would not load, and validates the saved files
- [x] `.env` is created and kept at mode `0600`; `set_credential` / `clear_credential` (with `export`) work; `credential_status` covers every case; `mask` never reveals a short value; no function returns a value
- [x] `/settings` in `tau chat` prints the report and the setters write, reload and rebuild on the same session; `set NAME` reads through `getpass` and nothing is echoed (CliRunner and REPL tests)
- [x] The TUI's `/settings` and F10 open the screen; sections switch by keyboard; saving the language relabels the app; saving a model change rebuilds on the same session (factory spy); invalid values stay in the dialog; the credential input is password-masked and its value appears in no widget text, snapshot or log; busy refusal
- [x] `tau tui` with no config runs the setup screen, creates the home with `init_home` and continues; `MissingCredentials` opens the Credentials section and the agent is built after the save; a corrupt config and an unknown `--resume` id still exit 2
- [x] Snapshots `test_settings_80x24` and `test_setup_80x24` contain no local path fragment (the user, home, tmp and private prefixes are checked); the menu snapshot shows thirteen rows
- [x] Docs (first run, configure, talk, slash commands, CLI, environment, development), both READMEs and `CONTEXT.md` updated; `mkdocs build --strict` passes; `uv run ruff check . && uv run ruff format . && uv run pytest -q` green (except 082 while a real hub runs)

## Blocked by

None.

## Comments

- 2026-09-29: done in one pass. New modules `tau_core/settings.py` (tomlkit added as a tau-core dependency, `tomlkit>=0.13`), `tau_tui/settings.py` (`SettingsScreen`, `SettingsOutcome`), `tau_tui/setup.py` (`SetupScreen`, `SetupApp`, `run_setup`, `SetupResult`); `ConfigNotFound` and `resolve_home` in `tau_core.config`; `/settings` in `tau_core.commands` (the Telegram channel already leaves it out); `TauApp` accepts `agent=None` with a `config` (the no-credentials start), `open_settings` / `apply_settings`, `check_action` keeps the app's F-keys out of the modal, `build_app(show_paths=…)` and an `agent_factory(config=…)` that remembers the last config; the command menu grew to thirteen rows (usage column 22). Decisions beyond the brief: the issue id is 083 (081 and 082 were taken by the Telegram wave meanwhile); `save_document` validates the document before writing rather than after; the Credentials section also lists the variables of providers not yet in `tau.toml`, so a key for the provider the user is switching to has a row; a changed credential is exported to the running process (`os.environ`) so the rebuilt agent sees it, while the next start follows the usual `.env`-never-overrides-the-shell rule; `/settings` in the no-agent state defaults to the Credentials section. Tests: `packages/tau-core/tests/test_settings.py`, `packages/tau-tui/tests/test_settings.py`, updated `test_cli.py` in both packages. The runtime settings file with hot reload stays issue 019.
