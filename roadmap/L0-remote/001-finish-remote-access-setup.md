# 001 · Finish remote access setup on the MacBook and verify from the phone

Status: done
Type: HITL
Layer: L0 · Remote access
Packages: infra/remote
Blocked by: none

## What to build

The remote access layer is implemented and its sudo-free part is already installed on the MacBook (tmux, mosh, `~/.zshenv` and `~/.tmux.conf` blocks, `tau-attach`, the `com.tau.keepawake` agent). The sshd hardening was validated with a throwaway sshd: a valid key is accepted from localhost and rejected from the LAN address. What remains needs the user's password, accounts and phone: install Tailscale, apply the sshd drop-in, enable Remote Login, add the Termius key, and prove the whole chain from the phone.

## Acceptance criteria

- [x] `infra/remote/setup-sudo.sh` has run: Tailscale installed, sshd drop-in installed, `sshd -t` passed, Remote Login on
- [x] MacBook and iPhone are logged into the same tailnet
- [x] Termius ED25519 key added with `infra/remote/add-key.sh`; host uses Mosh and the `tau-attach` startup snippet
- [x] `infra/remote/doctor.sh` exits 0
- [x] From the phone: connect, start `claude`, lock the phone for 2+ minutes, reconnect — the session is intact
- [x] If Claude Code asks to log in over SSH, the `claude setup-token` flow from `infra/remote/README.md` is applied

## Blocked by

None - can start immediately

## Comments

### 2026-09-28 — done

Walked through by hand with the user instead of running the scripts, one step at a time; every step has the same effect as `setup-sudo.sh` / `add-key.sh`.

- Tailscale: Mac and iPhone on one tailnet; `tailscale ping` goes direct over the LAN. Termius uses the Mac's full MagicDNS name. Real names, addresses and fingerprints are in the local `.env` (see `.env.example`); `doctor.sh` prints them too.
- Key: Termius ED25519 key in `~/.ssh/authorized_keys` with the comment `iphone-termius`, so a lost phone's line is easy to find.
- sshd: drop-in rendered from the template with `sed` and installed with `install`; it matches the repo byte for byte.
- `sshd -t` first failed with `no hostkeys available`. Remote Login had never been on, so there were no host keys. `sudo ssh-keygen -A` fixed it. `setup-sudo.sh` had the same gap (it runs `sshd -t` before turning Remote Login on); it now runs `ssh-keygen -A` first.
- `systemsetup -setremotelogin on` needs Full Disk Access; Remote Login was turned on in System Settings instead.
- Remote Management and Remote Application Scripting were also on and listening on every interface; both turned off, only port 22 is left. `doctor.sh` did not notice them → #051.
- `doctor.sh` exits 0 with "remote access ready".
- Phone test: Termius host with Mosh + `tau-attach` startup snippet; `claude` started over 5G, phone locked 2+ min, same screen came back. Closing the connection and reconnecting also lands in the running session.
- Claude Code did not ask to log in over SSH, so the `claude setup-token` flow was not needed.
- Verify the Mac's host key on a new client against `ssh-keygen -l -f /etc/ssh/ssh_host_ed25519_key.pub`.
