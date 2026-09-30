# ADR 0014 · One installer and a guided setup

Date: 2026-10-01 · Status: accepted · Builds on [ADR 0005](0005-components-and-entry-point-groups.md), [ADR 0006](0006-private-first-topology.md), [ADR 0008](0008-owner-guard.md) and [ADR 0013](0013-hosted-taus-handles-and-public-pages.md).

## Context

A local tau today asks a lot of its owner, who has to:

- pick packages (`--with tau-tui --with tau-net --with tau-sub --with tau-guard`);
- install uv, Node and bun for a spine, and Rust with the Xcode tools to build TauBar;
- find a Telegram chat id;
- run the Tailscale and SSH scripts;
- grant macOS permissions to the right app;
- run each feature's setup command in the right order.

The owner asked for one installer that lets people pick features and sets them up, with TauBar first so the permissions land in one app.

## Decision

1. **One engine: `tau setup` in tau-core.**
   - **A catalog as data.** The features live in `tau_core/templates/features.toml`. Each entry gives:
     - an id and its package;
     - labels from the i18n table;
     - the platforms and the default;
     - the macOS permissions it needs;
     - its steps, as tau commands.
   - **Features:** terminal UI, the app, sub-taus, Telegram, remote access (Tailscale), the owner guard, the tau network and the universe, start at login, cloud mode (a link to the guide).
   - **What it does:** it installs missing packages with one `uv tool install --force tau-core==<running version> --with …` and then re-executes itself in the new environment.
   - **Rules:**
     - A step can be skipped. A failed step is reported and the rest go on.
     - Setup can be re-run to add or remove features.
     - tau-core never imports the feature packages; it runs their CLIs.
   - **A JSON mode for the app.** A line-based protocol serves the app's wizard:
     - `tau setup status --json`, `tau setup install --json`, `tau setup run <feature> --json`;
     - inputs arrive as JSON on stdin, never in argv;
     - the protocol is specified in `docs/reference/setup.md`.
2. **Two front doors.**
   - **The terminal (macOS, Linux, Raspberry Pi):** `curl -fsSL https://tau.getporti.com/install.sh | sh`.
     - It installs uv when missing, installs tau-core and starts `tau setup` on the terminal.
     - The script is small, served by the universe, and readable before it runs.
   - **The Mac app:** download `tau.dmg` from `tau.getporti.com/download`. On first launch the app runs the same engine as a wizard and requests the macOS permissions itself.
3. **One Mac app, "tau".**
   - TauBar (the menu bar, the hub's supervisor) and tau Desktop (chat windows running `tau tui`) merge into one app.
   - The result is one download, one set of permissions (camera for the guard, notifications, the microphone later) and one place for the wizard.
4. **No toolchains for owners.**
   - Python comes through uv.
   - The app is built in CI on each release: no Rust, Node or Xcode tools on the owner's Mac.
   - Deploying a spine no longer needs Node or Wrangler. tau-net deploys the kit through the Cloudflare API with a scoped API token. The owner creates the token in the browser through a pre-filled link and pastes it at a hidden prompt.
5. **Guided feature steps.**
   - **Telegram:** open BotFather, paste the token, then send `/start` to the bot. The hub pairs with the first chat that sends the one-time code the wizard shows, so nobody looks up a chat id.
   - **Tailscale:**
     - install or open the Tailscale app and log in;
     - the SSH and mosh part of `infra/remote` needs `sudo`, so the wizard shows that one command with its explanation and waits;
     - it never runs `sudo` itself.
   - **The guard:** enrolment runs in the app, which holds the camera permission; Touch ID is the fallback (ADR 0008).
   - **The network:** `tau net init`, the spine through the API token, joining the universe, and the claim link.
6. **Signing.**
   - For now the app is not notarised. The owner decided against the Apple Developer Program for the time being.
   - CI signs every build with one stable self-signed code-signing identity, stored as a CI secret. macOS then keeps camera and notification permissions across updates, because the designated requirement stays the same.
   - Gatekeeper still warns on first open, and the download page and the wizard say how to open the app.
   - Moving to a Developer ID later changes only the signing step.

## Consequences

- **Issues:** 169 (the engine and `install.sh`), 170 (the unified app and its CI build), 171 (the app's wizard and permissions), 172 (Telegram pairing), 173 (remote access), 174 (the spine without Node), 175 (the docs and site).
- **Ownership:** the Mac app and the guard are the guard session's area, and the engine, the network and the docs this session's. The JSON protocol is the contract between them.
- **Defaults:** nothing in setup turns on the network, the guard, Telegram or remote access unless the owner chooses it. Tier 2 is unchanged.

## Why not

- **A Homebrew tap first:** Homebrew is one more prerequisite, and a cask would still need signing to avoid the warning. A tap can come later on top of the same builds.
- **The wizard in TauBar only:** Linux and the Raspberry Pi hub have no app. One engine with two front doors keeps them equal.
- **Bundling Python inside the app:** uv already installs a managed Python in seconds, and the app stays small.
