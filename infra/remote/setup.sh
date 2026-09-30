#!/usr/bin/env bash
# Remote access layer — the setup that needs no sudo. Running it again is safe.
# For the steps that need root (Tailscale pkg, sshd, Remote Login): ./setup-sudo.sh
set -euo pipefail
source "$(dirname "$0")/lib.sh"

step "1/4 Packages"
command -v brew >/dev/null || die "Homebrew is missing: https://brew.sh"
for formula in tmux mosh; do
  if brew list --formula "$formula" >/dev/null 2>&1; then
    ok "$formula already installed"
  else
    brew install "$formula"
    ok "$formula installed"
  fi
done

step "2/4 Shell environment (~/.zshenv)"
upsert_block "$HOME/.zshenv" remote "$(cat "$REMOTE_DIR/shell/zshenv.zsh")"
ok "non-interactive SSH sessions will see Homebrew (needed for mosh-server)"

step "3/4 tmux"
upsert_block "$HOME/.tmux.conf" remote "source-file \"$REMOTE_DIR/tmux/tau.tmux.conf\""
ok "~/.tmux.conf → $REMOTE_DIR/tmux/tau.tmux.conf"
mkdir -p "$HOME/.local/bin"
ln -sf "$REMOTE_DIR/bin/tau-attach" "$HOME/.local/bin/tau-attach"
ok "tau-attach → ~/.local/bin"

step "4/4 Sleep: stay awake on AC power"
agent="com.tau.keepawake"
plist="$HOME/Library/LaunchAgents/$agent.plist"
if app=$(mac_app); then
  # The tau app holds the same PreventSystemSleep assertion (and offers the lid-closed mode).
  launchctl bootout "gui/$(id -u)/$agent" 2>/dev/null || true
  rm -f "$plist"
  ok "$(basename "$app" .app) is installed ($app): it keeps the Mac awake; $agent removed"
elif [[ "$TAU_KEEPAWAKE" == 1 ]]; then
  mkdir -p "$HOME/Library/LaunchAgents"
  cp "$REMOTE_DIR/launchd/$agent.plist" "$plist"
  launchctl bootout "gui/$(id -u)/$agent" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$plist"
  ok "$agent loaded (caffeinate -s; sleeps as usual on battery and with the lid closed)"
else
  launchctl bootout "gui/$(id -u)/$agent" 2>/dev/null || true
  rm -f "$plist"
  warn "TAU_KEEPAWAKE=0: $agent removed"
fi

step "Next steps"
info "1. In your own terminal (sudo will ask for the password): ./infra/remote/setup-sudo.sh"
info "2. Generate an ED25519 key in Termius and add its public key: ./infra/remote/add-key.sh"
info "3. Check: ./infra/remote/doctor.sh"
