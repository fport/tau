#!/usr/bin/env bash
# Sign a built tau.app and pack what a release carries (.github/workflows/app.yml runs this; it
# runs the same on a Mac for a local check):
#
#   tau.dmg              the app with an Applications link, for the download
#   tau.app.tar.gz       the app for the Tauri updater
#   tau.app.tar.gz.sig   its updater signature, bound to the version     (with the updater key)
#   latest.json          what installed apps read to find an update      (with the updater key)
#
# Usage: apps/tau/scripts/pack-release.sh <tau.app> <out dir> <version>
#
# Signing, from the environment (CI: repository secrets; scripts/make-signing-identity.sh
# creates them):
#   MACOS_SIGNING_P12        the code-signing identity, a base64 p12
#   MACOS_SIGNING_PASSWORD   its password
#     Imported into a temporary keychain that only this run uses; codesign signs with the
#     hardened runtime and src-tauri/Entitlements.plist. Without them the app is signed ad hoc
#     and a warning says so: it runs, but every build is a new app to macOS's privacy settings.
#   TAURI_SIGNING_PRIVATE_KEY, TAURI_SIGNING_PRIVATE_KEY_PASSWORD
#     The updater key. Without it there is no signature and no latest.json, and a warning says
#     so; installed apps then do not see this release as an update.
#   TAU_DOWNLOAD_BASE where installed apps download releases from (default
#                     https://tau.getporti.com/download, the universe serving the R2 bucket
#                     tau-downloads that app.yml uploads to): latest.json names
#                     <base>/v<version>/tau.app.tar.gz
#   TAU_RELEASE_NOTES optional notes for latest.json
#
# No notarisation (ADR 0014 §6): Gatekeeper warns on first open, and the docs say how to open it.

set -euo pipefail

if [ "$#" -ne 3 ]; then
  sed -n '2,/^$/p' "$0" | sed 's/^# \{0,1\}//' >&2
  exit 2
fi
app="$1"
out="$2"
version="$3"
# The version also names the release's directory in the public downloads
# (/download/v<version>/), which the universe serves only for a semver version.
semver='^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(-[0-9A-Za-z-]+(\.[0-9A-Za-z-]+)*)?$'
if ! [[ "$version" =~ $semver ]]; then
  echo "error: $version is not a semver version (0.5.0, 0.5.0-rc1)" >&2
  exit 1
fi
here="$(cd "$(dirname "$0")" && pwd)"
root="$(dirname "$here")"
entitlements="$root/src-tauri/Entitlements.plist"
identity_name="tau (self-signed)"

warn() {
  # A GitHub Actions warning annotation, readable in a terminal too.
  echo "::warning::$*"
}

[ -d "$app" ] || { echo "error: no app at $app" >&2; exit 1; }
mkdir -p "$out"
work="$(mktemp -d "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/tau-pack.XXXXXX")"
keychain=""
# The user's keychain search list as it was, restored on exit.
search_list=()
while IFS= read -r line; do
  line="${line#"${line%%[![:space:]]*}"}"
  line="${line#\"}"
  line="${line%\"}"
  [ -n "$line" ] && search_list+=("$line")
done < <(security list-keychains -d user)
cleanup() {
  if [ -n "$keychain" ]; then
    security list-keychains -d user -s "${search_list[@]}" >/dev/null 2>&1 || true
    security delete-keychain "$keychain" >/dev/null 2>&1 || true
  fi
  rm -rf "$work"
}
trap cleanup EXIT

# -- sign ------------------------------------------------------------------------------------

sign_args=(--force --deep --options runtime --timestamp=none --entitlements "$entitlements")
if [ -n "${MACOS_SIGNING_P12:-}" ] && [ -n "${MACOS_SIGNING_PASSWORD:-}" ]; then
  keychain="$work/tau-signing.keychain-db"
  keychain_password="$(openssl rand -hex 24)"
  printf '%s' "$MACOS_SIGNING_P12" | base64 --decode >"$work/identity.p12"
  security create-keychain -p "$keychain_password" "$keychain"
  security set-keychain-settings -lut 3600 "$keychain"
  security unlock-keychain -p "$keychain_password" "$keychain"
  security import "$work/identity.p12" -k "$keychain" -f pkcs12 \
    -P "$MACOS_SIGNING_PASSWORD" -T /usr/bin/codesign >/dev/null
  rm -f "$work/identity.p12"
  # Let codesign use the key without a prompt.
  security set-key-partition-list -S apple-tool:,apple:,codesign: -s \
    -k "$keychain_password" "$keychain" >/dev/null
  # codesign finds an identity only in a keychain on the search list (`--keychain` alone is not
  # enough); the list is restored on exit.
  security list-keychains -d user -s "$keychain" "${search_list[@]}"
  # The self-signed certificate is not trusted by the system, so it is looked up by its hash in
  # this keychain alone (`-v`, valid only, would leave it out). codesign signs with it all the
  # same, and the designated requirement pins it: `certificate leaf = H"<its SHA-1>"`.
  identity="$(security find-identity -p codesigning "$keychain" |
    awk -v name="\"$identity_name\"" 'index($0, name) { print $2; exit }')"
  if [ -z "$identity" ]; then
    echo "error: MACOS_SIGNING_P12 holds no code-signing identity named \"$identity_name\"" >&2
    exit 1
  fi
  codesign "${sign_args[@]}" --keychain "$keychain" --sign "$identity" "$app"
  echo "Signed $app with \"$identity_name\"."
else
  warn "MACOS_SIGNING_P12 / MACOS_SIGNING_PASSWORD are not set: tau.app is signed ad hoc. It runs, but macOS treats every build as a new app and asks for the camera again after each update. apps/tau/scripts/make-signing-identity.sh creates the identity."
  codesign "${sign_args[@]}" --sign - "$app"
fi

codesign --verify --deep --strict "$app"
# Stable signing: `identifier "com.tau.app" and certificate leaf = H"..."`, the same for every
# build. Ad hoc: `cdhash H"..."`, new with every build.
echo "Designated requirement: $(codesign -d -r- "$app" 2>&1 | sed -n 's/^#* *designated => //p')"
if ! codesign -d --entitlements - "$app" 2>/dev/null | grep -q "com.apple.security.device.camera"; then
  echo "error: the signed app has no camera entitlement" >&2
  exit 1
fi

# -- the updater archive and latest.json -----------------------------------------------------

rm -f "$out/tau.app.tar.gz" "$out/tau.app.tar.gz.sig" "$out/latest.json"
COPYFILE_DISABLE=1 tar -czf "$out/tau.app.tar.gz" -C "$(dirname "$app")" "$(basename "$app")"
if [ -n "${TAURI_SIGNING_PRIVATE_KEY:-}" ]; then
  # The app checks updates against the public key in its config; without it a signed release
  # would be one that no installed app can take.
  if ! grep -Eq '"pubkey": "[^"]+"' "$root/src-tauri/tauri.conf.json"; then
    echo "error: src-tauri/tauri.conf.json has no updater public key; run scripts/make-signing-identity.sh and commit the key it writes" >&2
    exit 1
  fi
  # Bound to the version: the app sets requireSignedVersion, so a manifest cannot pair a new
  # version number with an older archive.
  (cd "$root" && bunx tauri signer sign --app-version "$version" "$out/tau.app.tar.gz") >/dev/null
  [ -s "$out/tau.app.tar.gz.sig" ] || { echo "error: the updater signature is missing" >&2; exit 1; }
  # The archive's own versioned URL, which never changes, rather than the "latest" copy that
  # the next release replaces.
  base="${TAU_DOWNLOAD_BASE:-https://tau.getporti.com/download}"
  base="${base%/}"
  case "$base" in
    https://*) ;;
    *) echo "error: TAU_DOWNLOAD_BASE must be an https URL, not $base" >&2; exit 1 ;;
  esac
  url="$base/v$version/tau.app.tar.gz"
  python3 - "$version" "$url" "$out/tau.app.tar.gz.sig" "$out/latest.json" <<'PY'
import datetime
import json
import os
import sys

version, url, sig_path, out = sys.argv[1:5]
with open(sig_path, encoding="utf-8") as f:
    signature = f.read().strip()
# One universal app serves both Mac architectures.
platform = {"signature": signature, "url": url}
manifest = {
    "version": version,
    "notes": os.environ.get("TAU_RELEASE_NOTES", ""),
    "pub_date": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "platforms": {"darwin-aarch64": platform, "darwin-x86_64": platform},
}
with open(out, "w", encoding="utf-8") as f:
    json.dump(manifest, f, indent=2)
    f.write("\n")
PY
  echo "Wrote the updater signature and latest.json for tau $version ($url)."
else
  warn "TAURI_SIGNING_PRIVATE_KEY is not set: no updater signature and no latest.json, so installed apps do not see this build as an update."
fi

# -- the disk image --------------------------------------------------------------------------

stage="$work/dmg"
mkdir -p "$stage"
ditto "$app" "$stage/$(basename "$app")"
ln -s /Applications "$stage/Applications"
rm -f "$out/tau.dmg"
hdiutil create -quiet -volname "tau" -srcfolder "$stage" -fs HFS+ -format UDZO -ov "$out/tau.dmg"
if [ -n "$keychain" ]; then
  codesign --force --timestamp=none --keychain "$keychain" --sign "$identity" "$out/tau.dmg"
fi
echo "Packed into $out:"
for file in tau.dmg tau.app.tar.gz tau.app.tar.gz.sig latest.json; do
  if [ -e "$out/$file" ]; then echo "  $file"; fi
done
