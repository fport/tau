#!/usr/bin/env bash
# Remote access on Linux (Raspberry Pi OS, Debian and Ubuntu; Fedora and Arch too): the sshd
# drop-in, openssh-server, mosh and tmux from the distribution, the ~/.tmux.conf block,
# tau-attach and the SSH service. The Linux counterpart of setup.sh + setup-sudo.sh.
# Run it as your normal user in your own terminal: sudo asks for the password only for the steps
# that need root. Running it again is safe.
# Tailscale comes from its own installer first: curl -fsSL https://tailscale.com/install.sh | sh
set -euo pipefail
source "$(dirname "$0")/lib.sh"

[[ "$(uname -s)" == Linux ]] || die "this script is for Linux; on macOS run ./setup-all.sh"
[[ $EUID -ne 0 ]] || die "run as a normal user, not with sudo: ./setup-linux.sh"

sshd_bin=/usr/sbin/sshd
ak="$HOME/.ssh/authorized_keys"

step "1/5 Keys"
if [[ -s "$ak" ]] && ssh-keygen -l -f "$ak" >/dev/null 2>&1; then
  ok "$(grep -c . "$ak") key(s) registered"
elif [[ -n "${SSH_CONNECTION:-}" ]]; then
  # Password login ends below; without a key this would be the last SSH session.
  die "you are connected over SSH and $ak has no key: add yours first (./add-key.sh), then run this again"
else
  warn "authorized_keys is empty: no remote login until the Termius key is added with ./add-key.sh"
fi
if [[ -n "${SSH_CONNECTION:-}" ]]; then
  warn "you are connected over SSH: keep this session open until a new connection over Tailscale works"
fi

# The drop-in goes in before openssh-server, so a freshly installed server starts hardened.
step "2/5 sshd configuration → $TAU_SSHD_CONF"
rendered=$(mktemp)
backup=$(mktemp)
trap 'rm -f "$rendered" "$backup"' EXIT
render_sshd_conf > "$rendered"
had_previous=0
if [[ -f "$TAU_SSHD_CONF" ]]; then
  cp "$TAU_SSHD_CONF" "$backup"
  had_previous=1
fi
sudo mkdir -p "$(dirname "$TAU_SSHD_CONF")"
sudo install -m 644 -o root -g root "$rendered" "$TAU_SSHD_CONF"
ok "written (passwords off, only $TAU_REMOTE_USER, only tailnet + localhost)"

rollback() {
  fail "$1, rolling back"
  if [[ $had_previous == 1 ]]; then
    sudo install -m 644 -o root -g root "$backup" "$TAU_SSHD_CONF"
  else
    sudo rm -f "$TAU_SSHD_CONF"
  fi
  exit 1
}

step "3/5 Packages"
if [[ -x $sshd_bin ]] && command -v mosh-server >/dev/null 2>&1 && command -v tmux >/dev/null 2>&1; then
  ok "openssh-server, mosh and tmux already installed"
elif command -v apt-get >/dev/null 2>&1; then
  sudo apt-get update
  sudo apt-get install -y openssh-server mosh tmux
  ok "openssh-server, mosh and tmux installed (apt-get)"
elif command -v dnf >/dev/null 2>&1; then
  sudo dnf install -y openssh-server mosh tmux
  ok "openssh-server, mosh and tmux installed (dnf)"
elif command -v pacman >/dev/null 2>&1; then
  sudo pacman -S --needed --noconfirm openssh mosh tmux
  ok "openssh, mosh and tmux installed (pacman)"
else
  rollback "no apt-get, dnf or pacman: install openssh-server, mosh and tmux yourself"
fi

# sshd reads the drop-in only through an Include line; without it the hardening would be ignored.
main=/etc/ssh/sshd_config
if ! sudo grep -Eqi '^[[:space:]]*Include[[:space:]]+/etc/ssh/sshd_config\.d/' "$main"; then
  rollback "$main does not read /etc/ssh/sshd_config.d/ (add 'Include /etc/ssh/sshd_config.d/*.conf' at its top)"
fi
# A server that never ran may lack host keys and, on Debian, its privilege separation directory.
sudo ssh-keygen -A
[[ -d /run/sshd ]] || sudo install -d -m 0755 /run/sshd
if sudo "$sshd_bin" -t; then
  ok "sshd -t passed"
else
  rollback "sshd -t failed"
fi

step "4/5 tmux and tau-attach"
upsert_block "$HOME/.tmux.conf" remote "source-file \"$REMOTE_DIR/tmux/tau.tmux.conf\""
ok "~/.tmux.conf → $REMOTE_DIR/tmux/tau.tmux.conf"
mkdir -p "$HOME/.local/bin"
ln -sf "$REMOTE_DIR/bin/tau-attach" "$HOME/.local/bin/tau-attach"
ok "tau-attach → ~/.local/bin"

step "5/5 The SSH service"
if ! command -v systemctl >/dev/null 2>&1; then
  warn "no systemctl: enable sshd and reload it with your init system"
elif systemctl is-active --quiet ssh.socket 2>/dev/null; then
  # Socket activation (Ubuntu 22.10 and later): every connection starts an sshd that reads the
  # configuration anew.
  ok "ssh.socket is active: new connections use the new settings"
else
  unit=sshd
  if systemctl cat ssh.service >/dev/null 2>&1; then unit=ssh; fi
  sudo systemctl enable --now "$unit"
  sudo systemctl reload "$unit"
  ok "$unit enabled and reloaded: new connections use the new settings"
fi
