# 001 · Finish remote access setup on the MacBook and verify from the phone

Status: ready-for-human
Type: HITL
Layer: L0 · Remote access
Packages: infra/remote
Blocked by: none

## What to build

The remote access layer is implemented and its sudo-free part is already installed on the MacBook (tmux, mosh, `~/.zshenv` and `~/.tmux.conf` blocks, `tau-attach`, the `com.tau.keepawake` agent). The sshd hardening was validated with a throwaway sshd: a valid key is accepted from localhost and rejected from the LAN address. What remains needs the user's password, accounts and phone: install Tailscale, apply the sshd drop-in, enable Remote Login, add the Termius key, and prove the whole chain from the phone.

## Acceptance criteria

- [ ] `infra/remote/setup-sudo.sh` has run: Tailscale installed, sshd drop-in installed, `sshd -t` passed, Remote Login on
- [ ] MacBook and iPhone are logged into the same tailnet
- [ ] Termius ED25519 key added with `infra/remote/add-key.sh`; host uses Mosh and the `tau-attach` startup snippet
- [ ] `infra/remote/doctor.sh` exits 0
- [ ] From the phone: connect, start `claude`, lock the phone for 2+ minutes, reconnect — the session is intact
- [ ] If Claude Code asks to log in over SSH, the `claude setup-token` flow from `infra/remote/README.md` is applied

## Blocked by

None - can start immediately

## Comments
