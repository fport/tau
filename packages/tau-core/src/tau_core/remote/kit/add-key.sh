#!/usr/bin/env bash
# Adds a device's public key to ~/.ssh/authorized_keys (never twice).
# Usage: ./add-key.sh "ssh-ed25519 AAAA... iphone-termius"   or run without arguments and paste.
set -euo pipefail
source "$(dirname "$0")/lib.sh"

key="${1:-}"
if [[ -z "$key" ]]; then
  printf 'Public key: '
  IFS= read -r key
fi
key=$(printf '%s' "$key" | tr -d '\r' | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')

fingerprint=$(printf '%s\n' "$key" | ssh-keygen -l -f - 2>/dev/null) || die "Not a valid public key"
case "$key" in
  ssh-rsa*) warn "RSA key; generate an ED25519 key in Termius if you can" ;;
esac

mkdir -p "$HOME/.ssh"
chmod 700 "$HOME/.ssh"
ak="$HOME/.ssh/authorized_keys"
touch "$ak"
chmod 600 "$ak"
if grep -qxF -- "$key" "$ak"; then
  ok "Already added: $fingerprint"
else
  printf '%s\n' "$key" >> "$ak"
  ok "Added: $fingerprint"
fi
