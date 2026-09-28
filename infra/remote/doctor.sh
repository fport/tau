#!/usr/bin/env bash
# Uzaktan erişim katmanının sağlık kontrolü. Hiçbir şeyi değiştirmez.
set -uo pipefail
source "$(dirname "$0")/lib.sh"

problems=0
bad() { fail "$*"; problems=$((problems + 1)); }

step "Paketler"
for cmd in tmux mosh mosh-server; do
  if command -v "$cmd" >/dev/null; then ok "$cmd"; else bad "$cmd yok → ./setup.sh"; fi
done

step "Tailscale"
ts=$(tailscale_cli)
if [[ -z "$ts" ]]; then
  bad "kurulu değil → ./setup-sudo.sh"
elif ip4=$("$ts" ip -4 2>/dev/null) && [[ -n "$ip4" ]]; then
  dns=$("$ts" status --json 2>/dev/null | /usr/bin/python3 -c \
    'import json,sys; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))' 2>/dev/null)
  ok "bağlı: $ip4${dns:+ ($dns)}"
  info "Termius host adresi: ${dns%%.*}  (MagicDNS kapalıysa: $ip4)"
else
  bad "kurulu ama bağlı değil → Tailscale.app'i aç ve giriş yap"
fi

step "SSH sunucusu"
if ssh_port_open; then ok "Remote Login açık"; else bad "Remote Login kapalı → ./setup-sudo.sh"; fi
if [[ ! -f "$TAU_SSHD_CONF" ]]; then
  bad "$TAU_SSHD_CONF yok → ./setup-sudo.sh"
elif diff -q <(render_sshd_conf) "$TAU_SSHD_CONF" >/dev/null; then
  ok "sertleştirme güncel"
else
  bad "$TAU_SSHD_CONF repodakinden farklı → ./setup-sudo.sh"
fi
if ssh_port_open; then
  # Şifreyle girmeyi dene: sunucu sadece "publickey" diyorsa şifre gerçekten kapalı.
  probe=$(ssh -o BatchMode=yes -o PubkeyAuthentication=no \
    -o PreferredAuthentications=password,keyboard-interactive \
    -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=3 \
    "$TAU_REMOTE_USER@127.0.0.1" true 2>&1)
  case "$probe" in
    *"Permission denied (publickey)"*) ok "şifreyle giriş kapalı, sadece anahtar" ;;
    *password*|*keyboard-interactive*) bad "şifreyle giriş hâlâ açık → ./setup-sudo.sh" ;;
    *) warn "giriş yöntemleri doğrulanamadı: $probe" ;;
  esac
fi

step "Anahtarlar"
ak="$HOME/.ssh/authorized_keys"
if [[ -s "$ak" ]] && keys=$(ssh-keygen -l -f "$ak" 2>/dev/null); then
  ok "$(printf '%s\n' "$keys" | grep -c .) anahtar"
  printf '%s\n' "$keys" | while IFS= read -r line; do info "$line"; done
  perms=$(stat -f '%Lp' "$ak")
  [[ "$perms" == 600 ]] || bad "authorized_keys izinleri $perms, 600 olmalı"
else
  bad "authorized_keys boş → ./add-key.sh"
fi

step "Kabuk ortamı"
if has_block "$HOME/.zshenv" remote; then ok "~/.zshenv bloğu var"; else bad "~/.zshenv bloğu yok → ./setup.sh"; fi
# Etkileşimsiz SSH oturumunu taklit et: mosh-server PATH'te görünmeli.
if env -i HOME="$HOME" USER="$USER" /bin/zsh -c 'command -v mosh-server' >/dev/null 2>&1; then
  ok "etkileşimsiz oturum mosh-server'ı buluyor"
else
  bad "etkileşimsiz oturum mosh-server'ı bulamıyor → ./setup.sh"
fi

step "tmux"
if has_block "$HOME/.tmux.conf" remote; then
  if err=$(tmux -L tau-doctor -f "$HOME/.tmux.conf" start-server \; kill-server 2>&1) && [[ -z "$err" ]]; then
    ok "~/.tmux.conf hatasız yükleniyor"
  else
    bad "~/.tmux.conf hata veriyor: $err"
  fi
else
  bad "~/.tmux.conf bloğu yok → ./setup.sh"
fi
if command -v tau-attach >/dev/null; then ok "tau-attach"; else bad "tau-attach PATH'te değil → ./setup.sh"; fi

step "Uyku"
if launchctl print "gui/$(id -u)/com.tau.keepawake" >/dev/null 2>&1; then
  ok "com.tau.keepawake çalışıyor (şarjdayken uyumaz; pildeyken devre dışı)"
elif [[ "$TAU_KEEPAWAKE" == 1 ]]; then
  bad "com.tau.keepawake yüklü değil → ./setup.sh"
else
  warn "TAU_KEEPAWAKE=0: Mac uyuyunca uzaktan erişilemez"
fi
power=$(pmset -g batt | head -1 | sed -e "s/.*'\(.*\)'.*/\1/")
info "Şu anki güç: $power"

step "Güvenlik duvarı"
if /usr/libexec/ApplicationFirewall/socketfilterfw --getglobalstate | grep -q enabled; then
  real=$(realpath "$(command -v mosh-server 2>/dev/null)" 2>/dev/null)
  if [[ -n "$real" ]] && /usr/libexec/ApplicationFirewall/socketfilterfw --getappblocked "$real" | grep -q 'permitted'; then
    ok "açık, mosh-server'a izin var"
  else
    warn "açık; mosh UDP'si engellenebilir → socketfilterfw --add/--unblockapp $real"
  fi
else
  ok "kapalı (mosh için engel yok)"
fi

step "Sonuç"
if [[ $problems -eq 0 ]]; then
  ok "uzaktan erişim hazır"
else
  fail "$problems sorun var"
  exit 1
fi
