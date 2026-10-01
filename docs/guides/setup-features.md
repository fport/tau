# Setup features

`tau setup` and the Mac app's setup wizard offer the same list of features. This page goes through each one: what it is, what it installs, where it runs, the macOS permissions it asks for, its steps, and how to add or remove it later. The decision behind the wizard is [ADR 0014](../adr/0014-one-installer-and-onboarding.md). The catalog's schema and the JSON protocol the app speaks are in the [`tau setup` reference](../reference/setup.md).

## Two ways in

- **The Mac app.** Download `tau.dmg` from [tau.getporti.com/download](https://tau.getporti.com/download). Its first launch opens the wizard, and **Set up tau…** in the menu opens it again ([the app guide](taubar.md#first-launch)).
- **The terminal**, on macOS, Linux and a Raspberry Pi:

    ```sh
    curl -fsSL https://tau.getporti.com/install.sh | sh
    ```

    It installs uv when it is missing, then tau, and starts `tau setup` ([Install](../getting-started/install.md)).

Both show the same checklist and run the same steps. A feature that is set up already is marked `✓` and never asked again.

## At a glance

| Feature | id | Installs | Platforms | On by default | Asks macOS for | Needs you for |
|---|---|---|---|---|---|---|
| [Terminal UI](#terminal-ui) | `tui` | `tau-tui` | macOS, Linux | yes | – | – |
| [The tau app](#the-tau-app) | `app` | the app, from the download page | macOS | no | notifications | the download |
| [Sub-taus](#sub-taus) | `sub` | `tau-sub` | macOS, Linux | yes | – | – |
| [Telegram](#telegram) | `telegram` | nothing (in tau-core) | macOS, Linux | no | – | a bot token, then `/start` on your phone |
| [Remote access](#remote-access) | `remote` | nothing (in tau-core) | macOS, Linux | no | – | Tailscale's login, one `sudo` command, your phone's key |
| [Owner guard](#owner-guard) | `guard` | `tau-guard` | macOS | no | camera | your face, at the Mac |
| [The tau network](#the-tau-network) | `net` | `tau-net` | macOS, Linux | no | – | a name; for the spine, a Cloudflare API token |
| [Start at login](#start-at-login) | `autostart` | nothing | macOS, Linux | on macOS | – | – |
| [Cloud mode](#cloud-mode) | `cloud` | `tau-cloud` (and `tau-net`) | macOS, Linux | no | – | the cloud mode guide |

Before the features, setup runs two steps of its own: `tau init` (the language, your model provider and its key, at a hidden prompt) when there is no configuration yet, and a short "about you" for `persona/user.md` (your name, how tau should address you, your languages). After them it runs `tau doctor`.

## How setup behaves

- **One install.** The packages of the chosen features are installed with one `uv tool install`, pinned to the running tau-core's version, and setup then goes on in the new environment ([details](../reference/setup.md#installing-and-the-re-execution)).
- **Every step asks first** and can be skipped. A step that fails is reported, and the others go on.
- **Never `sudo`.** When something needs the administrator password, setup shows the one command with what it changes and waits while you run it in your own terminal. Neither tau nor the app runs it.
- **Secrets stay hidden.** Keys and tokens are typed at hidden prompts (hidden fields in the app) and written to `<TAU_HOME>/.env` with mode `0600`. They never appear on a command line.
- **At the Mac only.** The guard's enrollment refuses to run over SSH. Run setup at the Mac for it.
- **Opt-in.** Nothing turns on Telegram, remote access, the guard or the network unless you choose it. Tier 2 is unchanged: an action in the physical world, or a message in your name to another tau, still waits for your yes.

### Adding a feature later

```sh
tau setup                  # the checklist: tick what you want
tau setup run telegram     # one feature's steps, even when it is set up already
tau setup status           # every feature, its id and its state
```

In the app: **Set up tau…** in the menu, the panel or the settings window.

### Removing a feature

```sh
tau setup --remove sub
```

`--remove` uninstalls a feature's package with the same pinned `uv tool install`, after a confirmation. Settings and data stay. A feature without a package (Telegram, remote access, start at login, the app) is switched off by hand; each section below says how.

## Terminal UI

The full-screen interface, `tau tui`: streamed replies, tool cards, approvals in a dialog and the sessions list. [Talk to tau](../getting-started/talk.md) compares it with `tau chat`.

- **Installs:** `tau-tui`, released together with tau-core and pinned to its version. The one-line installer always includes it.
- **Platforms:** macOS and Linux. On by default.
- **Steps:** none.
- **Remove:** `tau setup --remove tui`. `tau chat` stays.

## The tau app

The Mac app: a **τ** in the menu bar, the hub's supervisor, chat windows that run `tau tui`, sleep modes, launch at login and its own copy of this wizard. See [the app guide](taubar.md).

- **Installs:** nothing through uv. The step points to [the download page](https://tau.getporti.com/download), where `tau.dmg` is (macOS 13 or later, Apple silicon and Intel). The app is not notarised yet, so macOS asks once before it opens it; the download page shows the two ways to open it.
- **Platforms:** macOS. Off by default in the terminal; in the app it is there already.
- **Permissions:** notifications. The app also holds the camera permission for a hub it runs, which the [owner guard](#owner-guard) needs.
- **Set up when:** `tau.app` is in `/Applications` or `~/Applications`.
- **Remove:** untick **Launch at login**, quit tau (it stops the hub it started) and move `tau.app` to the Trash.

## Sub-taus

Named specialists of your tau, each with its own character: a running coach, a chef, a tutor. See [Public sub-taus with a web page](public-sub-taus.md) and [ADR 0012](../adr/0012-sub-taus.md).

- **Installs:** `tau-sub`.
- **Platforms:** macOS and Linux. On by default.
- **Steps:** a note on making the first one when you like:

    ```sh
    tau sub new coach --describe "a patient running coach"
    tau sub chat coach          # or /coach in tau tui
    ```

- **Remove:** `tau setup --remove sub`. The sub-taus' files stay in your configuration.

## Telegram

Talk to tau from your phone through your own bot. The hub polls Telegram itself, so no server sits in between and no port opens. See [Telegram](telegram.md).

- **Installs:** nothing; the channel is part of tau-core.
- **Platforms:** macOS and Linux.
- **Steps:** one, `tau telegram pair`, which needs you:
    1. Make a bot with [@BotFather](https://t.me/botfather) (`/newbot`) and copy its token.
    2. Paste the token at the hidden prompt (in the app, a hidden field). tau checks it with Telegram and writes `TELEGRAM_BOT_TOKEN` to `.env`.
    3. tau shows a one-time code and a `t.me` link. Open it on your phone and press **Start**, or send `/start <code>` to the bot. The chat that sends the code becomes the only one tau answers (`TELEGRAM_ALLOWED_CHAT_IDS`), so there is no chat id to look up.
- **Set up when:** both values are in the environment or `.env`. A running hub picks the pairing up at once; otherwise start the hub.
- **Remove:** delete the two `TELEGRAM_…` lines from `<TAU_HOME>/.env` and restart the hub. `/deletebot` in BotFather removes the bot itself.

## Remote access

Reach this machine from your phone: Tailscale puts both on one private network, SSH accepts keys only from it, and mosh with tmux keeps the session through a locked phone. See [Reach tau from your phone](phone-tailscale-termius.md).

- **Installs:** nothing through uv. tau-core carries the setup scripts and writes them to `~/.local/share/tau/remote/` before it shows a command.
- **Platforms:** macOS and Linux (a Raspberry Pi included).
- **Steps:** three checks. Each passes on its own, or says what only you can do and waits; **Enter** (in the app **Done, check again**) checks again, `skip` goes on:
    1. **Tailscale.** Install it and log in. On macOS the step opens the download page on request; on Linux it shows Tailscale's official install command for you to run.
    2. **SSH and mosh.** If anything is missing, it shows **one command** and what it changes:

        ```sh
        bash ~/.local/share/tau/remote/setup-all.sh
        ```

        Run it in your own terminal, as yourself: it asks for your password (`sudo`) only for the parts that need root. tau never runs it.

    3. **Your phone.** The values to enter in Termius (the address, your user name, port 22, mosh on) and how to add the key Termius generates.
- **Set up when:** `tau remote status` exits 0.
- **Remove:** the rollback under [Troubleshooting](phone-tailscale-termius.md#troubleshooting) in the phone guide: the SSH drop-in, the keep-awake agent, the shell blocks and Remote Login.

## Owner guard

tau answers only while you are at the Mac: the TUI and `tau chat` open locked and unlock with a face check, with Touch ID as the fallback, and a tier-2 action needs one more check after your approval. See [Owner guard](guard.md) and [ADR 0008](../adr/0008-owner-guard.md).

- **Installs:** `tau-guard`, released together with tau-core and pinned to its version. The face model (about 40 MB) is downloaded once by the setup step.
- **Platforms:** macOS only. It uses the Mac's built-in camera and Touch ID.
- **Permissions:** the camera. In the app the wizard asks for it, so the grant belongs to tau.app, which runs the hub.
- **Steps:**
    1. `tau guard doctor` checks the prerequisites. Before setup it reports problems, as expected; the next step fixes them.
    2. `tau guard setup` enrolls your face behind Touch ID or your Mac password. **You at the Mac:** it is refused over SSH. In the app it runs in the wizard's own terminal.
    3. Restart the hub: the guard starts with the next hub, locked. Unlock once in `tau tui`.
- **Set up when:** your face is enrolled.
- **Remove:** run `tau guard forget` at the Mac first, then `tau setup --remove guard`. Setup refuses to remove the package while you are enrolled, because a hub without tau-guard but with the enrollment would stay locked.

## The tau network

An address for your tau, contacts with other taus, signed and sealed messages, and if you like a place in the public universe. See [Join the tau network](tau-network.md).

- **Installs:** `tau-net`.
- **Platforms:** macOS and Linux.
- **Steps:**
    1. `tau net init` creates your tau's network identity. It asks for the display name on your card.
    2. A note on the **spine**: your tau's address is a small Worker in your own Cloudflare account, and the free plan is enough. The next two steps are optional; you can deploy later.
    3. `tau net spine init` writes the spine project (default `~/tau-spine`), with your address if you have a domain on Cloudflare, else a `workers.dev` one.
    4. `tau net spine deploy` deploys it through the Cloudflare API. **A token from you:** tau opens Cloudflare's token page with the permissions filled in; you create the token and paste it at the hidden prompt, and it is saved as `CLOUDFLARE_API_TOKEN` in `.env`. No Node.js or Wrangler is needed.
    5. `tau net universe join` lists your tau on the universe (optional; your name and one line about your tau).
    6. `tau net universe claim` prints a GitHub sign-in link that claims a handle for your tau (optional).
- **Set up when:** the identity exists.
- **Remove:** `tau net universe leave` takes your tau off the universe. `tau setup --remove net` uninstalls the package; your identity and contacts stay in the data directory, so a later install picks them up again.

## Start at login

The hub as a service that starts when you log in and comes back after a crash. See [Run tau as a service](hub-service.md).

- **Installs:** nothing.
- **Platforms:** macOS and Linux. On by default on macOS.
- **Steps:**
    - **macOS, in the terminal:** `tau hub install`, a launchd user agent.
    - **macOS, in the app:** the app itself runs the hub and opens at login. Only a hub the app runs can use the camera for the guard.
    - **Linux:** a systemd user unit, no `sudo`:

        ```sh
        mkdir -p ~/.config/systemd/user
        tau hub systemd-unit > ~/.config/systemd/user/tau-hub.service
        systemctl --user enable --now tau-hub
        ```

- **Remove:** `tau hub uninstall` on macOS (or untick **Launch at login** in the app); `systemctl --user disable --now tau-hub` and delete the unit file on Linux.

## Cloud mode

Advanced: the hub itself runs in a container in your own Cloudflare account, for owners without a machine that stays on. It needs Workers Paid and Docker. See [Run tau in Cloudflare](cloud-mode.md).

- **Installs:** `tau-cloud`, and `tau-net` with it.
- **Platforms:** macOS and Linux. Marked as advanced in the checklist.
- **Steps:** a note that points to the guide; `tau cloud push` comes when you are ready.
- **Remove:** `tau setup --remove cloud`. [Going back to local mode](cloud-mode.md#going-back-to-local-mode) covers the account side.
