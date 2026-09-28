#!/usr/bin/env bash
# Uzaktan erişim katmanı — sudo gerektirmeyen kurulum. Tekrar çalıştırmak güvenlidir.
# Root isteyen adımlar (Tailscale pkg, sshd, Remote Login) için: ./setup-sudo.sh
set -euo pipefail
source "$(dirname "$0")/lib.sh"

step "1/4 Paketler"
command -v brew >/dev/null || die "Homebrew yok: https://brew.sh"
for formula in tmux mosh; do
  if brew list --formula "$formula" >/dev/null 2>&1; then
    ok "$formula kurulu"
  else
    brew install "$formula"
    ok "$formula kuruldu"
  fi
done

step "2/4 Kabuk ortamı (~/.zshenv)"
upsert_block "$HOME/.zshenv" remote "$(cat "$REMOTE_DIR/shell/zshenv.zsh")"
ok "etkileşimsiz SSH oturumları Homebrew'u görecek (mosh-server için gerekli)"

step "3/4 tmux"
upsert_block "$HOME/.tmux.conf" remote "source-file \"$REMOTE_DIR/tmux/tau.tmux.conf\""
ok "~/.tmux.conf → $REMOTE_DIR/tmux/tau.tmux.conf"
mkdir -p "$HOME/.local/bin"
ln -sf "$REMOTE_DIR/bin/tau-attach" "$HOME/.local/bin/tau-attach"
ok "tau-attach → ~/.local/bin"

step "4/4 Uyku: şarjdayken uyuma"
agent="com.tau.keepawake"
plist="$HOME/Library/LaunchAgents/$agent.plist"
if [[ "$TAU_KEEPAWAKE" == 1 ]]; then
  mkdir -p "$HOME/Library/LaunchAgents"
  cp "$REMOTE_DIR/launchd/$agent.plist" "$plist"
  launchctl bootout "gui/$(id -u)/$agent" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$plist"
  ok "$agent yüklendi (caffeinate -s; pilde ve kapak kapalıyken normal uyur)"
else
  launchctl bootout "gui/$(id -u)/$agent" 2>/dev/null || true
  rm -f "$plist"
  warn "TAU_KEEPAWAKE=0: $agent kaldırıldı"
fi

step "Sıradaki adımlar"
info "1. Kendi terminalinde (sudo şifre soracak): ./infra/remote/setup-sudo.sh"
info "2. Termius'ta ED25519 anahtar üret, public key'i ekle: ./infra/remote/add-key.sh"
info "3. Kontrol: ./infra/remote/doctor.sh"
