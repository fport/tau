#!/usr/bin/env bash
# Uzaktan erişim — root gerektiren adımlar: Tailscale (pkg), sshd sertleştirmesi, Remote Login.
# Kendi terminalinde normal kullanıcı olarak çalıştır; sudo sadece gereken komutlarda şifre sorar.
set -euo pipefail
source "$(dirname "$0")/lib.sh"

[[ $EUID -ne 0 ]] || die "sudo ile değil, normal kullanıcı olarak çalıştır: ./setup-sudo.sh"

step "1/4 Tailscale"
if [[ -d /Applications/Tailscale.app ]]; then
  ok "Tailscale.app kurulu"
else
  brew install --cask tailscale-app
  ok "Tailscale.app kuruldu"
fi
info "Aç → Gizlilik ve Güvenlik'te sistem uzantısına izin ver → giriş yap"

step "2/4 Yetkili anahtarlar"
ak="$HOME/.ssh/authorized_keys"
if [[ -s "$ak" ]] && ssh-keygen -l -f "$ak" >/dev/null 2>&1; then
  ok "$(grep -c . "$ak") anahtar kayıtlı"
else
  warn "authorized_keys boş: Termius anahtarını ./add-key.sh ile ekleyene kadar uzaktan giriş olmaz"
fi

step "3/4 sshd yapılandırması → $TAU_SSHD_CONF"
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
if sudo /usr/sbin/sshd -t; then
  ok "sshd -t geçti (şifre kapalı, sadece $TAU_REMOTE_USER, sadece tailnet + localhost)"
else
  fail "sshd -t başarısız, geri alınıyor"
  if [[ $had_previous == 1 ]]; then
    sudo install -m 644 -o root -g wheel "$backup" "$TAU_SSHD_CONF"
  else
    sudo rm -f "$TAU_SSHD_CONF"
  fi
  exit 1
fi

step "4/4 Remote Login"
if ssh_port_open; then
  ok "açık (sshd her bağlantıda yeniden başlar, yeni ayarlar hemen geçerli)"
elif sudo systemsetup -setremotelogin on >/dev/null 2>&1 && sleep 1 && ssh_port_open; then
  ok "açıldı"
else
  warn "Otomatik açılamadı (terminalin Tam Disk Erişimi yok). Elle aç:"
  info "Sistem Ayarları → Genel → Paylaşma → Uzaktan Giriş: AÇIK"
  info "(i) → Erişime izin ver: Sadece şu kullanıcılar → $TAU_REMOTE_USER"
fi
