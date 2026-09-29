#!/usr/bin/env bash
# Health check of the remote access layer. Changes nothing.
set -uo pipefail
source "$(dirname "$0")/lib.sh"

problems=0
bad() { fail "$*"; problems=$((problems + 1)); }

step "Packages"
for cmd in tmux mosh mosh-server; do
  if command -v "$cmd" >/dev/null; then ok "$cmd"; else bad "$cmd missing → ./setup.sh"; fi
done

step "Tailscale"
ts=$(tailscale_cli)
if [[ -z "$ts" ]]; then
  bad "not installed → ./setup-sudo.sh"
elif ip4=$("$ts" ip -4 2>/dev/null) && [[ -n "$ip4" ]]; then
  dns=$("$ts" status --json 2>/dev/null | /usr/bin/python3 -c \
    'import json,sys; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))' 2>/dev/null)
  ok "connected: $ip4${dns:+ ($dns)}"
  info "Termius host address: ${dns%%.*}  (if MagicDNS is off: $ip4)"
else
  bad "installed but not connected → open Tailscale.app and sign in"
fi

step "SSH server"
if ssh_port_open; then ok "Remote Login is on"; else bad "Remote Login is off → ./setup-sudo.sh"; fi
if [[ ! -f "$TAU_SSHD_CONF" ]]; then
  bad "$TAU_SSHD_CONF missing → ./setup-sudo.sh"
elif diff -q <(render_sshd_conf) "$TAU_SSHD_CONF" >/dev/null; then
  ok "hardening is up to date"
else
  bad "$TAU_SSHD_CONF differs from the repo → ./setup-sudo.sh"
fi
if ssh_port_open; then
  # Try to log in with a password: passwords are really off only if the server offers just "publickey".
  probe=$(ssh -o BatchMode=yes -o PubkeyAuthentication=no \
    -o PreferredAuthentications=password,keyboard-interactive \
    -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=3 \
    "$TAU_REMOTE_USER@127.0.0.1" true 2>&1)
  case "$probe" in
    *"Permission denied (publickey)"*) ok "password login is off, key only" ;;
    *password*|*keyboard-interactive*) bad "password login is still on → ./setup-sudo.sh" ;;
    *) warn "could not verify the login methods: $probe" ;;
  esac
fi

step "Keys"
ak="$HOME/.ssh/authorized_keys"
if [[ -s "$ak" ]] && keys=$(ssh-keygen -l -f "$ak" 2>/dev/null); then
  ok "$(printf '%s\n' "$keys" | grep -c .) key(s)"
  printf '%s\n' "$keys" | while IFS= read -r line; do info "$line"; done
  perms=$(stat -f '%Lp' "$ak")
  [[ "$perms" == 600 ]] || bad "authorized_keys permissions are $perms, must be 600"
else
  bad "authorized_keys is empty → ./add-key.sh"
fi

step "Shell environment"
if has_block "$HOME/.zshenv" remote; then ok "~/.zshenv block present"; else bad "~/.zshenv block missing → ./setup.sh"; fi
# Imitate a non-interactive SSH session: mosh-server must be on PATH.
if env -i HOME="$HOME" USER="$USER" /bin/zsh -c 'command -v mosh-server' >/dev/null 2>&1; then
  ok "non-interactive session finds mosh-server"
else
  bad "non-interactive session cannot find mosh-server → ./setup.sh"
fi

step "tmux"
if has_block "$HOME/.tmux.conf" remote; then
  if err=$(tmux -L tau-doctor -f "$HOME/.tmux.conf" start-server \; kill-server 2>&1) && [[ -z "$err" ]]; then
    ok "~/.tmux.conf loads without errors"
  else
    bad "~/.tmux.conf reports an error: $err"
  fi
else
  bad "~/.tmux.conf block missing → ./setup.sh"
fi
if command -v tau-attach >/dev/null; then ok "tau-attach"; else bad "tau-attach is not on PATH → ./setup.sh"; fi

step "Sleep"
if launchctl print "gui/$(id -u)/com.tau.keepawake" >/dev/null 2>&1; then
  ok "com.tau.keepawake is running (no sleep on AC power; inactive on battery)"
elif [[ "$TAU_KEEPAWAKE" == 1 ]]; then
  bad "com.tau.keepawake is not loaded → ./setup.sh"
else
  warn "TAU_KEEPAWAKE=0: the Mac is unreachable once it sleeps"
fi
power=$(pmset -g batt | head -1 | sed -e "s/.*'\(.*\)'.*/\1/")
info "Current power source: $power"

step "Firewall"
if /usr/libexec/ApplicationFirewall/socketfilterfw --getglobalstate | grep -q enabled; then
  real=$(realpath "$(command -v mosh-server 2>/dev/null)" 2>/dev/null)
  if [[ -n "$real" ]] && /usr/libexec/ApplicationFirewall/socketfilterfw --getappblocked "$real" | grep -q 'permitted'; then
    ok "on, mosh-server is allowed"
  else
    warn "on; mosh UDP may be blocked → socketfilterfw --add/--unblockapp $real"
  fi
else
  ok "off (nothing blocks mosh)"
fi

step "Result"
if [[ $problems -eq 0 ]]; then
  ok "remote access ready"
else
  fail "$problems problem(s) found"
  exit 1
fi
