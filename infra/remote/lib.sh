#!/usr/bin/env bash
# infra/remote betiklerinin ortak yardımcıları. Doğrudan çalıştırılmaz, source edilir.

REMOTE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "$REMOTE_DIR/config.local.env" ]]; then
  # shellcheck source=/dev/null
  source "$REMOTE_DIR/config.local.env"
fi
# shellcheck source=config.env
source "$REMOTE_DIR/config.env"

ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
fail() { printf '  \033[31m✗\033[0m %s\n' "$*"; }
info() { printf '    %s\n' "$*"; }
step() { printf '\n\033[1m%s\033[0m\n' "$*"; }
die()  { fail "$*"; exit 1; }

# Dosyadaki `# >>> tau:<ad> >>>` … `# <<< tau:<ad> <<<` bloğunu ekler ya da yeniler.
# Bloğun dışındaki satırlara dokunmaz; tekrar çalıştırmak güvenlidir.
upsert_block() {
  local file=$1 name=$2 content=$3
  local begin="# >>> tau:$name >>>" end="# <<< tau:$name <<<"
  local tmp
  tmp=$(mktemp)
  touch "$file"
  awk -v b="$begin" -v e="$end" '$0==b{skip=1;next} $0==e{skip=0;next} !skip' "$file" > "$tmp"
  { cat "$tmp"; printf '%s\n%s\n%s\n' "$begin" "$content" "$end"; } > "$file"
  rm -f "$tmp"
}

has_block() {
  grep -qxF "# >>> tau:$2 >>>" "$1" 2>/dev/null
}

render_sshd_conf() {
  sed -e "s|__USER__|$TAU_REMOTE_USER|g" \
      -e "s|__TAILNET_V4__|$TAU_TAILNET_V4|g" \
      -e "s|__TAILNET_V6__|$TAU_TAILNET_V6|g" \
      "$REMOTE_DIR/sshd/tau.conf"
}

# Tailscale CLI yolunu yazar; GUI uygulamasının içindeki binary'yi de bulur.
tailscale_cli() {
  if command -v tailscale >/dev/null 2>&1; then
    command -v tailscale
  elif [[ -x /Applications/Tailscale.app/Contents/MacOS/Tailscale ]]; then
    echo /Applications/Tailscale.app/Contents/MacOS/Tailscale
  fi
}

ssh_port_open() {
  nc -z -G 2 127.0.0.1 22 >/dev/null 2>&1
}
