#!/usr/bin/env bash
# Bir cihazın public key'ini ~/.ssh/authorized_keys'e ekler (tekrar eklemez).
# Kullanım: ./add-key.sh "ssh-ed25519 AAAA… iphone-termius"   ya da argümansız çalıştırıp yapıştır.
set -euo pipefail
source "$(dirname "$0")/lib.sh"

key="${1:-}"
if [[ -z "$key" ]]; then
  printf 'Public key: '
  IFS= read -r key
fi
key=$(printf '%s' "$key" | tr -d '\r' | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')

fingerprint=$(printf '%s\n' "$key" | ssh-keygen -l -f - 2>/dev/null) || die "Geçerli bir public key değil"
case "$key" in
  ssh-rsa*) warn "RSA anahtarı; mümkünse Termius'ta ED25519 üret" ;;
esac

mkdir -p "$HOME/.ssh"
chmod 700 "$HOME/.ssh"
ak="$HOME/.ssh/authorized_keys"
touch "$ak"
chmod 600 "$ak"
if grep -qxF -- "$key" "$ak"; then
  ok "Zaten ekli: $fingerprint"
else
  printf '%s\n' "$key" >> "$ak"
  ok "Eklendi: $fingerprint"
fi
