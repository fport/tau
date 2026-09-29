# Reach tau from your phone (Tailscale + Termius)

The goal: open Termius on the phone, land in a tmux session on the hub, run `tau tui`, and keep that session alive when the phone locks or the network changes. Nothing is exposed to the internet: the phone and the hub talk over a Tailscale private network, SSH accepts keys only and only from that network, and mosh keeps the connection through roaming.

```text
Phone (Termius) ──▶ Tailscale ──▶ OpenSSH on the hub ──▶ mosh ──▶ tmux ──▶ tau tui
```

| Part | Job |
|---|---|
| **Tailscale** | Puts the phone and the hub on the same private network (a *tailnet*) without opening ports. |
| **OpenSSH** (macOS Remote Login) | Login by key only, only as your user, only from the tailnet. |
| **mosh** | The connection survives network changes and a locked phone. |
| **tmux** | The session, and whatever runs in it, keeps running when the connection drops. |
| **keep-awake agent** | The Mac does not sleep while on AC power (`caffeinate -s`). Once [TauBar](taubar.md) is installed, `setup.sh` removes it and TauBar does the job. |

The scripts live in [`infra/remote/`](https://github.com/fport/tau/tree/main/infra/remote) of the repository. They were written for a MacBook hub; the Linux notes below cover a Raspberry Pi.

## 1. Set up the hub

=== "macOS"

    From a checkout of the repository. The first script needs no sudo; the second asks for your password, so run it in your own terminal:

    ```sh
    ./infra/remote/setup.sh          # tmux, mosh, ~/.tmux.conf, ~/.zshenv, tau-attach, keep-awake agent
    ./infra/remote/setup-sudo.sh     # Tailscale, sshd hardening, Remote Login
    ```

    Then sign in: open Tailscale.app, allow the system extension under **Privacy & Security**, and sign in.

    What the sudo script writes into `/etc/ssh/sshd_config.d/010-tau.conf`:

    - password and keyboard-interactive (PAM) logins off; keys only;
    - `AllowUsers` restricted to your user from the tailnet (`100.64.0.0/10`, `fd7a:115c:a1e0::/48`) and localhost;
    - agent forwarding off; only local (`-L`) TCP forwarding allowed.

    On macOS sshd listens on every interface, but even someone on the same café network who reaches port 22 is stopped by `AllowUsers`.

=== "Linux (Raspberry Pi)"

    The scripts are macOS-specific (`launchctl`, Remote Login). Do the same by hand:

    ```sh
    curl -fsSL https://tailscale.com/install.sh | sh
    sudo tailscale up
    sudo apt install -y openssh-server mosh tmux
    ```

    Harden sshd with a drop-in that mirrors the macOS one, then restart it:

    ```sh
    sudo tee /etc/ssh/sshd_config.d/010-tau.conf >/dev/null <<'EOF'
    PasswordAuthentication no
    KbdInteractiveAuthentication no
    PubkeyAuthentication yes
    AllowAgentForwarding no
    AllowTcpForwarding local
    AllowUsers you@100.64.0.0/10 you@fd7a:115c:a1e0::/48 you@127.0.0.1 you@::1
    EOF
    sudo systemctl restart ssh
    ```

    Replace `you` with your user name. Test from a second session before you close the first one.

## 2. Set up the phone

1. Install **Tailscale** on the phone and sign in with the **same account** as the hub.
2. Install **Termius**.
3. Create a key: Termius → **Keychain** → **+** → **Generate Key** → type **ED25519** → name it `iphone`. Open the key and copy the public key.
4. Add the public key to the hub. On macOS with Universal Clipboard:

    ```sh
    ./infra/remote/add-key.sh
    ```

    Anywhere else, append it to `~/.ssh/authorized_keys` on the hub (`chmod 600` on the file, `chmod 700` on the directory).

5. Create the host in Termius:

    | Field | Value |
    |---|---|
    | Address | the hub's MagicDNS name, e.g. `my-mac.tailXXXXXX.ts.net` (`infra/remote/doctor.sh` prints it) |
    | Username | your user name on the hub |
    | Key | `iphone` |
    | **Mosh** | on |
    | **Startup Snippet** | `tau-attach` |

`tau-attach` is a tiny script that `setup.sh` installs into `~/.local/bin`: it attaches to the tmux session named `tau`, creating it if needed. With it as the startup snippet, every connection lands in the same session.

## 3. Check the chain

```sh
./infra/remote/doctor.sh
```

It prints the MagicDNS name and the tailnet IP of the hub, checks Tailscale, sshd's configuration, mosh, tmux and the keep-awake agent, and flags anything exposed. Connect from Termius: you should land in tmux without typing anything.

!!! warning "Personal values stay out of the repository"
    Hostnames, tailnet names, IPs and key fingerprints are personal. The `.env.example` lists them as `TAU_MAC_MAGICDNS=my-mac.tailXXXXXX.ts.net`, `TAU_MAC_TAILNET_IP=100.x.y.z`, `TAU_MAC_SSH_HOST_KEY_FP=SHA256:...` and so on. Put the real values in your gitignored `.env`; the doctor prints them live anyway.

## 4. Run the TUI in tmux

Once in the tmux session:

```sh
cd /path/to/tau && uv run tau tui        # from a checkout
tau tui                                  # from a uv tool install
```

Leave the TUI running. Lock the phone, switch from Wi-Fi to mobile data, come back: mosh reconnects and the same screen is there. If mosh gives up (a long offline gap), reconnect in Termius; `tau-attach` brings the session back with the TUI still in it.

To see the same screen from the hub's own keyboard, run `tau-attach` there.

## 5. The 50-column layout

A phone terminal is around 50 columns by 24 rows. The TUI has a dedicated **phone** band below 60 columns:

```text
 τ tau · home                                  en
 › Salon lambası açık mı? Açıksa kapat.
 ○ set_light(room="salon", on=false)
   ⎿  tier 2 · running
 ✻ Running set_light…
 ❯
 esc cancel · ^j newline                     busy
```

- The header drops the session id; `/session` shows it.
- Tool badges move to the result line; the composer has no border.
- Replies stream as plain text and settle into markdown when a segment ends.
- The approval dialog is full width with stacked **Approve** / **Reject** buttons.
- Below 20 rows the hint row disappears and the composer grows to two rows.

If the block characters render badly, start with `TAU_TUI_ASCII=1 tau tui` for an ASCII vocabulary and borders.

## 6. Keys on a phone keyboard

Termius shows an extra keys row above the keyboard with **Esc**, **Tab**, **Ctrl**, arrows and the function keys. The TUI binds an F-key next to every Ctrl chord for this reason:

| Key | Effect |
|---|---|
| F1 or `?` | help |
| F2 | session picker (Enter resumes, `n` new, Esc closes) |
| F3 | `/tools` |
| F4 | events view (below 100 columns it replaces the transcript; Esc returns) |
| F6 | expand or collapse the last turn's tool cards |
| F7 / F8 | scroll the transcript up / down |
| F9 | back to the bottom |
| Esc | cancel the running turn, close the menu, leave the events view |
| Ctrl-J (`^j`) | newline in the composer |
| Ctrl-Q | quit the TUI (tmux and the session stay) |

Typing `/` opens the command menu; arrows pick, Tab completes, Enter runs.

## 7. Approvals from the phone

A tier-2 call opens the approval dialog on whichever screen is attached, so the phone sees the same dialog the hub's keyboard would. `y` or `e` approves, `n`, `h` or Esc rejects, and the arming delay of half a second means a key you were typing cannot approve by accident.

Nothing else can approve. The tmux session is the trusted channel here: it runs under your user on the hub, and only your key from your tailnet can attach to it. Silence never approves; if the phone dies with a dialog open, the call is rejected when the wait is cancelled.

## Troubleshooting

**`mosh-server not found`.** Run `./infra/remote/setup.sh` again. Non-interactive SSH sessions read only `~/.zshenv`, which is where the script puts the `PATH` entry.

**I cannot reach the hub.** Check in order: is Tailscale on on the phone, is the hub asleep, what does `doctor.sh` say. A MacBook sleeps with the lid closed; plug it in and leave the lid open, use clamshell mode with an external display, or pick TauBar's "Keep awake with the lid closed" mode (it needs a one-time sudoers rule, see [TauBar](taubar.md#set-up-the-lid-closed-mode)).

**The TUI is black and white.** Termius over mosh drops 24-bit colour escapes; 256 colours come through. `infra/remote/tmux/tau.tmux.conf` therefore does not force truecolor (`RGB`) for `xterm-256color` clients, so tmux maps the TUI's colours to the 256-colour palette for the phone. If you set such an override in your own `~/.tmux.conf`, remove it, reload with `Ctrl-b r` and reconnect in Termius (tmux decides a client's colours when it attaches). Outside tmux, `TEXTUAL_COLOR_SYSTEM=256 uv run tau tui` does the same for one run.

**The TUI shows an older version than the checkout.** A `uv tool install tau-core --with tau-tui` puts its own `tau` in `~/.local/bin`, and that comes first on `PATH`, even inside the checkout. Run `uv run tau tui` in the checkout, or update the tool with `uv tool upgrade tau-core`. The welcome card shows the version that is running.

**Claude Code asks to sign in again over SSH.** The macOS login keychain can look locked in an SSH session. Either `security unlock-keychain ~/Library/Keychains/login.keychain-db` in the session, or create a long-lived token with `claude setup-token` and export it from `~/.config/tau/remote.env`, which `~/.zshenv` loads only in SSH sessions. `GH_TOKEN` and `CLOUDFLARE_API_TOKEN` can live in the same file.

**The phone is lost.** Delete that device's line from `~/.ssh/authorized_keys` on the hub and remove the device from the Tailscale admin console. Both take a minute; do them in that order.

**Rollback.** On macOS: `sudo rm /etc/ssh/sshd_config.d/010-tau.conf`, `launchctl bootout gui/$(id -u)/com.tau.keepawake`, delete the plist and `~/.local/bin/tau-attach`, remove the `# >>> tau:remote >>>` blocks from `~/.zshenv` and `~/.tmux.conf`, and turn off Remote Login under **System Settings → General → Sharing**.

## One-shot questions from an iOS Shortcut

!!! info "Planned (roadmap issue 073)"
    `tau ask "…"` will be a one-shot command for scripts and iOS Shortcuts: an SSH Shortcut action over Tailscale runs `tau ask "what is on my desk?"` and shows the reply. It answers with the same persona and session store, and it **never approves a tier-2 call**: such a call is refused with a pointer to a trusted channel (the TUI, TauBar, the web UI or Telegram). The command does not exist yet; the recipe will be:

    1. Shortcuts → new Shortcut → **Dictate Text**.
    2. Add **Run Script Over SSH**. Host: the hub's MagicDNS name (`my-mac.tailXXXXXX.ts.net`); user: yours; authentication: the Shortcut's SSH key, added to `authorized_keys` like the Termius key. Script: `tau ask "<Dictated Text>"`.
    3. Add **Speak Text** (or **Show Result**) on the script's output.
    4. Tailscale must be on on the phone; the same prerequisites as this guide.

    `tau ask` prints plain text with no ANSI when stdout is not a terminal, so **Speak Text** reads it cleanly; exit code 2 means the turn was refused (a tier-2 call) or hit a limit.
