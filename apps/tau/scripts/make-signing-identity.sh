#!/usr/bin/env bash
# Create the signing material for tau.app's release builds (.github/workflows/app.yml), once, on
# your own Mac:
#
#   1. A self-signed code-signing certificate, "tau (self-signed)", as a password-protected p12.
#      CI signs every build with it, so every build has the same designated requirement and macOS
#      keeps the camera and notification permissions across updates (ADR 0014 §6).
#   2. The Tauri updater's key pair. CI signs tau.app.tar.gz with the private key; the app checks
#      the signature with the public key, which this script writes into
#      src-tauri/tauri.conf.json (plugins.updater.pubkey) for you to commit.
#
# Everything goes into apps/tau/.signing/ (gitignored; the directory is 0700, the files 0600). The
# script prints the `gh secret set` commands that feed those files to the repository's secrets on
# stdin. It never prints a secret, and it never sets one itself.
#
# Usage:
#   apps/tau/scripts/make-signing-identity.sh           # create what is missing, print the commands
#   apps/tau/scripts/make-signing-identity.sh --force   # replace both (see below)
#
#   TAU_SIGNING_DIR=/some/dir   writes there instead of apps/tau/.signing
#
# Keep a copy of .signing/ in your password manager. Replace the certificate only when it is
# lost or leaked: builds signed with a new one are a new app to macOS, which asks for the camera
# again after that update. A new updater key needs a release with the new public key before
# older installs can update past it, so replace that only when it leaked, too.

set -euo pipefail
umask 077

NAME="tau (self-signed)"
DAYS=3650

usage() {
  sed -n '2,/^$/p' "$0" | sed 's/^# \{0,1\}//'
}

force=0
case "${1:-}" in
  "") ;;
  --force) force=1 ;;
  -h | --help) usage; exit 0 ;;
  *) usage >&2; exit 2 ;;
esac

here="$(cd "$(dirname "$0")" && pwd)"
app="$(dirname "$here")"
out="${TAU_SIGNING_DIR:-$app/.signing}"
config="$app/src-tauri/tauri.conf.json"

need() {
  command -v "$1" >/dev/null 2>&1 || { echo "error: $1 is needed ($2)" >&2; exit 1; }
}
need openssl "the certificate"
need base64 "the p12 for the secret"
need bunx "the updater key: bun from https://bun.sh, then bun install in apps/tau"

# A path as the person running the script can type it: relative to the current directory
# when it is inside it.
show() {
  case "$1" in
    "$PWD"/*) printf '%s' "${1#"$PWD"/}" ;;
    *) printf '%s' "$1" ;;
  esac
}

# A random password: 32 characters, letters and digits only, no newline.
password() {
  openssl rand -base64 48 | LC_ALL=C tr -dc 'A-Za-z0-9' | cut -c1-32 | tr -d '\n'
}

mkdir -p "$out"
chmod 700 "$out"

p12="$out/tau-signing.p12"
p12_b64="$out/tau-signing.p12.base64"
p12_pw="$out/tau-signing.p12.password"
cert="$out/tau-signing.cert.pem"
key="$out/updater.key"
key_pw="$out/updater.key.password"

# -- 1. the code-signing identity -----------------------------------------------------------

if [ -s "$p12" ] && [ -s "$p12_b64" ] && [ -s "$p12_pw" ] && [ "$force" = 0 ]; then
  echo "Keeping the code-signing identity in $(show "$out") (--force replaces it)."
else
  work="$(mktemp -d "${TMPDIR:-/tmp}/tau-signing.XXXXXX")"
  trap 'rm -rf "$work"' EXIT
  # codesign wants the digitalSignature key usage and the codeSigning extended key usage; a
  # certificate that is not a CA and signs itself is all a stable designated requirement needs.
  cat >"$work/req.cnf" <<EOF
[req]
distinguished_name = dn
prompt = no
x509_extensions = ext
[dn]
CN = $NAME
[ext]
basicConstraints = critical,CA:false
keyUsage = critical,digitalSignature
extendedKeyUsage = critical,codeSigning
subjectKeyIdentifier = hash
EOF
  openssl req -x509 -new -newkey rsa:3072 -sha256 -days "$DAYS" -nodes \
    -config "$work/req.cnf" -keyout "$work/key.pem" -out "$work/cert.pem" 2>/dev/null
  password >"$p12_pw"
  # 3DES and SHA-1 MACs: the p12 algorithms `security import` reads (OpenSSL 3 defaults to
  # AES and PBKDF2, which macOS rejects). LibreSSL and OpenSSL both take these options.
  openssl pkcs12 -export -name "$NAME" -inkey "$work/key.pem" -in "$work/cert.pem" \
    -keypbe PBE-SHA1-3DES -certpbe PBE-SHA1-3DES -macalg sha1 \
    -passout "file:$p12_pw" -out "$p12"
  base64 <"$p12" | tr -d '\n' >"$p12_b64"
  cp "$work/cert.pem" "$cert"
  chmod 600 "$p12" "$p12_b64" "$p12_pw" "$cert"
  echo "Created the code-signing identity \"$NAME\" in $(show "$out"), valid for $DAYS days."
fi

# -- 2. the updater key --------------------------------------------------------------------

if [ -s "$key" ] && [ -s "$key.pub" ] && [ -s "$key_pw" ] && [ "$force" = 0 ]; then
  echo "Keeping the updater key in $(show "$out") (--force replaces it)."
else
  password >"$key_pw"
  # `tauri signer generate` takes the password as an argument only; it runs for a moment on
  # your own Mac. Its output names the files and is not shown.
  (cd "$app" && bunx tauri signer generate --ci --force \
    --password "$(cat "$key_pw")" --write-keys "$key") >/dev/null
  chmod 600 "$key" "$key.pub" "$key_pw"
  echo "Created the updater key in $(show "$out")."
fi

# -- the public key in tauri.conf.json -----------------------------------------------------

pubkey="$(tr -d '\n' <"$key.pub")"
current="$(sed -n 's/^ *"pubkey": "\(.*\)",$/\1/p' "$config")"
if [ "$current" = "$pubkey" ]; then
  echo "$(show "$config") already has this updater public key."
elif [ -z "$current" ] || [ "$force" = 1 ]; then
  sed -i.bak "s|^\( *\"pubkey\": \)\".*\",\$|\1\"$pubkey\",|" "$config" && rm -f "$config.bak"
  echo "Wrote the updater public key into $(show "$config"): commit that change."
else
  echo "warning: $(show "$config") has another updater public key; --force replaces it." >&2
fi

# -- what to run next ----------------------------------------------------------------------

cat <<EOF

Set the repository secrets (gh reads each value from the file on stdin; nothing is printed):

  gh secret set MACOS_SIGNING_P12 < $(show "$p12_b64")
  gh secret set MACOS_SIGNING_PASSWORD < $(show "$p12_pw")
  gh secret set TAURI_SIGNING_PRIVATE_KEY < $(show "$key")
  gh secret set TAURI_SIGNING_PRIVATE_KEY_PASSWORD < $(show "$key_pw")

Keep a copy of $(show "$out") in your password manager: a lost certificate means macOS asks
for the camera again after the next update, and a lost updater key means installed apps
cannot update to builds signed with a new one.
EOF
