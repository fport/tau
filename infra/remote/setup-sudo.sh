#!/usr/bin/env bash
# Remote access — the steps that need root: Tailscale (pkg), sshd hardening, Remote Login.
# Run it in your own terminal as a normal user; sudo asks for the password only where needed.
set -euo pipefail
source "$(dirname "$0")/lib.sh"

[[ $EUID -ne 0 ]] || die "run as a normal user, not with sudo: ./setup-sudo.sh"

step "1/4 Tailscale"
if [[ -d /Applications/Tailscale.app ]]; then
  ok "Tailscale.app already installed"
else
  brew install --cask tailscale-app
  ok "Tailscale.app installed"
fi
info "Open it → allow the system extension under Privacy & Security → sign in"

step "2/4 Authorized keys"
ak="$HOME/.ssh/authorized_keys"
if [[ -s "$ak" ]] && ssh-keygen -l -f "$ak" >/dev/null 2>&1; then
  ok "$(grep -c . "$ak") key(s) registered"
else
  warn "authorized_keys is empty: no remote login until the Termius key is added with ./add-key.sh"
fi

step "3/4 sshd configuration → $TAU_SSHD_CONF"
rendered=$(mktemp)
backup=$(mktemp)
trap 'rm -f "$rendered" "$backup"' EXIT
render_sshd_conf > "$rendered"
had_previous=0
if [[ -f "$TAU_SSHD_CONF" ]]; then
  cp "$TAU_SSHD_CONF" "$backup"
  had_previous=1
fi
sudo install -m 644 -o root -g wheel "$rendered" "$TAU_SSHD_CONF"
# A Mac that never had Remote Login on has no host keys, and sshd -t says "no hostkeys available".
# macOS generates them on the first connection; we generate the missing ones before the test
# (existing keys are left alone).
sudo ssh-keygen -A
if sudo /usr/sbin/sshd -t; then
  ok "sshd -t passed (passwords off, only $TAU_REMOTE_USER, only tailnet + localhost)"
else
  fail "sshd -t failed, rolling back"
  if [[ $had_previous == 1 ]]; then
    sudo install -m 644 -o root -g wheel "$backup" "$TAU_SSHD_CONF"
  else
    sudo rm -f "$TAU_SSHD_CONF"
  fi
  exit 1
fi

step "4/4 Remote Login"
if ssh_port_open; then
  ok "on (sshd restarts on every connection, the new settings apply immediately)"
elif sudo systemsetup -setremotelogin on >/dev/null 2>&1 && sleep 1 && ssh_port_open; then
  ok "turned on"
else
  warn "Could not turn it on automatically (the terminal has no Full Disk Access). Turn it on by hand:"
  info "System Settings → General → Sharing → Remote Login: ON"
  info "(i) → Allow access for: Only these users → $TAU_REMOTE_USER"
fi
