# infra/remote — Remote access

Phone (Termius) → Tailscale → OpenSSH on the MacBook → tmux → Claude Code.

| Part | Job |
|---|---|
| **Tailscale** | Puts the phone and the Mac on the same private network (tailnet) without opening ports |
| **OpenSSH** (macOS Remote Login) | Login by key only, only as your user, only from the tailnet |
| **mosh** | The connection survives network changes and a locked phone |
| **tmux** | The session (and the Claude Code inside it) keeps running when the connection drops |
| **com.tau.keepawake** | The Mac does not sleep while on AC power (`caffeinate -s`). Once the [tau app](../../apps/tau/README.md) is installed in `/Applications`, `setup.sh` removes this agent and the app does the job |

## The guided way

`tau setup` → **Remote access** (or `tau setup run remote` later) walks through all of it:

1. It checks that Tailscale is installed and logged in, and says how to install it or log in.
2. It checks sshd, the drop-in, mosh and tmux, and shows the one command below with what it changes. It never runs it: you run it in your own terminal, type `done`, and it checks again.
3. It prints what to enter in Termius, with the live MagicDNS name and user.

The one command, as your normal user (not with `sudo`; sudo asks for the password only for the steps that need root):

```sh
./infra/remote/setup-all.sh
```

On macOS it runs `setup.sh` and then `setup-sudo.sh`. On Linux it runs `setup-linux.sh`, which installs openssh-server, mosh and tmux from the distribution (apt-get, dnf or pacman), writes the same drop-in, adds the `~/.tmux.conf` block and `tau-attach`, and enables the SSH service. Over SSH without a key in `~/.ssh/authorized_keys` it stops, so you cannot lock yourself out.

`tau remote status` runs the same checks as `doctor.sh` that matter for remote access (Tailscale, sshd, the drop-in, a live password probe, mosh, tmux, the keys), on macOS and Linux. `doctor.sh` stays the fuller macOS check (sleep, firewall).

### Shipped with tau-core

An installed tau has no checkout, so tau-core carries a copy of this directory without this README: `packages/tau-core/src/tau_core/remote/kit/`. When it needs the command, `tau remote ssh` writes the copy to `$TAU_DATA_DIR/remote/` (`~/.local/share/tau/remote/`) and shows `bash ~/.local/share/tau/remote/setup-all.sh`. A test keeps the copy identical to this directory. After a change here, copy it over:

```sh
rsync -a --delete --exclude README.md --exclude config.local.env infra/remote/ packages/tau-core/src/tau_core/remote/kit/
```

## Setup by hand (macOS)

1. **tmux, mosh and user settings** (no sudo needed):
   ```sh
   ./infra/remote/setup.sh
   ```
2. **Tailscale, sshd and Remote Login.** This step asks for the sudo password, so run it in your own terminal:
   ```sh
   ./infra/remote/setup-sudo.sh
   ```
3. **Sign in to Tailscale:** open Tailscale.app on the Mac, allow the system extension under Privacy & Security, then sign in. Install Tailscale on the iPhone too and sign in with the **same account**.
4. **Termius key:** Keychain → **+** → Generate Key → Type **ED25519** → name it `iphone` → open the key and copy the public key. Paste it on the Mac with Universal Clipboard:
   ```sh
   ./infra/remote/add-key.sh
   ```
5. **Termius host settings:**
   - Address: the MagicDNS name that `doctor.sh` prints
   - Username: your Mac user name
   - Key: `iphone`
   - **Mosh: on**
   - **Startup Snippet:** `tau-attach`
6. **Check:**
   ```sh
   ./infra/remote/doctor.sh
   ```

## Daily use

- **When you connect from Termius** you land directly in the `tau` tmux session. Type `claude` to start. If the connection drops, reconnect and continue where you left off.
- **At the Mac, to join the same session** run `tau-attach`. You see the same screen as on the phone.
- **To see a dev server on the phone**, start the server with `--host 0.0.0.0` and open `http://<magicdns-name>:3000` in Safari. This traffic never leaves the tailnet.
- **tmux shortcuts:** prefix `Ctrl-b`. `|` and `-` split, `r` reloads the settings. Scroll with a finger.

## Troubleshooting

**`mosh-server not found`:** run `./setup.sh` again. Non-interactive SSH sessions read only `~/.zshenv`.

**Claude Code asks to sign in again over SSH:** in an SSH session the macOS login keychain can appear locked. Two fixes:

- Unlock it in every session (asks for the password):
  ```sh
  security unlock-keychain ~/Library/Keychains/login.keychain-db
  ```
- Or create a long-lived token:
  ```sh
  claude setup-token
  mkdir -p ~/.config/tau && chmod 700 ~/.config/tau
  printf 'export CLAUDE_CODE_OAUTH_TOKEN=%s\n' '<token>' > ~/.config/tau/remote.env
  chmod 600 ~/.config/tau/remote.env
  ```

`~/.zshenv` loads this file **only in SSH sessions**. You can add `GH_TOKEN` for `gh` and `CLOUDFLARE_API_TOKEN` for `wrangler` to the same file.

**I cannot reach the Mac:** check in order: is Tailscale on on the iPhone, is the Mac asleep, what does `doctor.sh` say. The Mac sleeps with the lid closed. Plug it in and leave the lid open, use it in clamshell mode with an external display, or pick the tau app's "Keep awake with the lid closed" mode (it needs a one-time sudoers rule: `apps/tau/sudoers/install-sudoers.sh`).

**Is the Mac kept awake?** `doctor.sh` checks it under "Sleep". By hand: `pmset -g assertions` shows `PreventSystemSleep 1` and the process holding it, either `caffeinate` (the agent) or `tau-app` (`named: "tau keeps the Mac awake"`; TauBar's was `taubar`, `named: "TauBar keeps the Mac awake for tau"`). On battery the assertion has no effect.

## Security model

- **Key-only login:** password and keyboard-interactive (PAM) logins are off.
- **Only your user, only from the tailnet and localhost:** `100.64.0.0/10`, `fd7a:115c:a1e0::/48`, `127.0.0.1` and `::1`. On macOS sshd listens on every interface, but even if someone in the same cafe reaches port 22, `AllowUsers` does not let them in.
- **Restricted forwarding:** agent forwarding is off. Only local (`-L`) TCP forwarding is allowed.
- **If the phone is lost:** delete that device's line from `~/.ssh/authorized_keys` and remove the device from the Tailscale admin console.

## Settings

Defaults are in `config.env`. Put machine-specific overrides in `config.local.env` (gitignored). For example, to disable the keep-awake agent, set `TAU_KEEPAWAKE=0` and run `./setup.sh` again. With the tau app installed the agent is removed regardless; `TAU_MAC_APP` (formerly `TAU_TAUBAR_APP`, still read) points the scripts at a tau.app outside `/Applications` and `~/Applications`.

## Rollback

```sh
sudo rm /etc/ssh/sshd_config.d/010-tau.conf
launchctl bootout gui/$(id -u)/com.tau.keepawake
rm ~/Library/LaunchAgents/com.tau.keepawake.plist ~/.local/bin/tau-attach
```

In addition:
- Delete the `# >>> tau:remote >>>` blocks from `~/.zshenv` and `~/.tmux.conf`.
- Turn off Remote Login: System Settings → General → Sharing.

On Linux:

```sh
sudo rm /etc/ssh/sshd_config.d/010-tau.conf && sudo systemctl reload ssh   # sshd on Fedora and Arch
rm ~/.local/bin/tau-attach
```

Then delete the `# >>> tau:remote >>>` block from `~/.tmux.conf`.
