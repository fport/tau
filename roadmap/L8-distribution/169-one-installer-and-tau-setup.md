# 169 · One installer and `tau setup`: pick the features, install and configure them

Status: in-progress
Type: AFK
Layer: L8 · Distribution
Packages: tau-core, cloud/universe, docs
Blocked by: –

## What to build

The owner: "People may not manage to use all this. We should have one installer: run it, let people pick the features they want, then it can set up the guard and so on."

Today a person has to know which packages exist (`--with tau-tui --with tau-net --with tau-sub --with tau-guard`) and which setup commands each needs (`tau init`, `tau hub install`, `tau guard setup`, `tau net init`, `tau net spine init|deploy`, `tau net universe join|claim`, `tau sub new`). Two pieces fix that.

1. **The one-line installer**
   - `curl -fsSL https://tau.getporti.com/install.sh | sh`
   - The script is served by the universe Worker as a static file. It is small, readable and POSIX `sh` for macOS and Linux.
   - It installs uv when missing (Astral's official installer, after saying so) and runs `uv tool install tau-core`.
   - It then starts `tau setup`, reading from `/dev/tty` so the prompts work under `curl | sh`.
   - It honours `TAU_INSTALL_NO_SETUP=1`.
   - It never asks for `sudo`.
   - The page says how to read the script first.

2. **`tau setup` in tau-core**, an interactive wizard, re-runnable to add features later.

   **Features.** They are listed as data (a catalog in `tau_core/templates/`, not code), each with:
   - the package, a one-line description in the i18n table, the platforms, and whether it is selected by default;
   - its setup steps as tau commands.

   Proposed features:
   - **Terminal UI** (`tau-tui`): on by default.
   - **Sub-taus** (`tau-sub`): on.
   - **The tau network and the universe** (`tau-net`): off.
     - Steps: `tau net init`; optionally deploy a spine with the kit, which needs Node 24 (+ bun) and a Cloudflare login. The wizard checks these and explains.
     - Optionally join the universe and print the claim link.
   - **Owner guard** (`tau-guard`): off, macOS only.
     - Steps: `tau guard doctor`, then `tau guard setup` at the Mac, never over SSH.
   - **Cloud mode** (`tau-cloud`): off, advanced; points to the guide.
   - **Start the hub at login** (`tau hub install`): on on macOS.
   - **TauBar**: shown only when a downloadable build exists; until then it points to the guide.

   **Flow.**
   1. It detects what is installed (`importlib.metadata`) and what is configured (`TAU_HOME`, `.env`, the guard's enrollment marker, the network profile).
   2. It shows a checklist; the arrow and space keys come from `prompt_toolkit` or `rich`. It works without colours and in Turkish (`--lang tr`, or asked first).
   3. It installs the missing packages with one `uv tool install --force tau-core==<same version> --with …`, pinning the running tau-core's version so the set stays in lockstep.
   4. It re-executes itself in the new environment (`tau setup --resume <state file>`).
   5. It runs the configuration steps in order:
      - `tau init` (provider and key) when there is no config;
      - a short "about you" for `user.md` (name, how tau should address you, languages), skippable;
      - the steps of each chosen feature, then `tau doctor`.
   6. Every step can be skipped, and a failed step is reported without stopping the others.
   7. It ends with a summary: what is on, what was skipped and why, what to run next (`tau chat`, `tau tui`, TauBar), and docs links.

   **Rules.**
   - Keys are only typed at hidden prompts.
   - `tau setup` never runs `sudo`, never enables the guard or the network without the person choosing them, and never changes tier 2.
   - tau-core does not import tau-guard, tau-net or tau-sub. It runs their CLIs as subprocesses and discovers them by entry point, so the package split stays clean.
   - `--yes --features tui,sub,net` makes it scriptable, which also serves the tests and the smoke test.
   - Outside a uv tool install, for example in a repo checkout, it tells you to use `uv sync --all-packages` instead of reinstalling.

3. **Docs and site.**
   - The landing page's "Run it on your machine" way shows the one-liner.
   - The docs' Install page and "Three ways" lead with it (EN + TR).
   - The README's step 1 becomes the one-liner, with `uv tool install …` as the manual way.
   - The release workflow's smoke test runs `tau setup --yes --features tui,sub` in a fresh environment.

## Acceptance criteria

- [ ] `install.sh` served at `https://<universe>/install.sh`, with a `text/plain` content type; shellcheck clean; tested in a temp HOME with a fake uv and a real one
- [ ] `tau setup` interactive and `--yes` flows, re-runnable (adds features, never re-asks for what is set up); tests with fake subprocess runners and a fake uv; i18n en + tr
- [ ] Choosing the guard runs `tau guard doctor` and `tau guard setup` on macOS and explains why it is unavailable elsewhere; choosing the network walks through `tau net init`, the spine kit and the universe with clear skips
- [ ] Docs, the README, the site and the release smoke test updated (EN + TR)

## Comments

- 2026-10-01: filed at the owner's request.
