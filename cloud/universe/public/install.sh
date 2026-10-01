#!/bin/sh
# tau installer (ADR 0014). Served at https://tau.getporti.com/install.sh
#
# Read it before you run it:
#   curl -fsSL https://tau.getporti.com/install.sh | less
# Run it:
#   curl -fsSL https://tau.getporti.com/install.sh | sh
#
# What it does, and nothing else:
#   1. Checks that this is macOS or Linux on a 64-bit x86 or ARM CPU.
#   2. When uv (https://docs.astral.sh/uv/) is missing, installs it with Astral's official
#      installer, into ~/.local/bin (or $UV_INSTALL_DIR). uv's installer may add that
#      directory to your shell profile; see its own options.
#   3. Installs tau with `uv tool install tau-core --with tau-tui`: its own environment, a
#      Python that uv manages, the `tau` command in uv's tool bin directory.
#   4. Starts `tau setup`, which asks which features you want and sets them up.
#
# It never runs sudo. An existing tau is left as it is: `tau setup` adds features and
# `tau setup --upgrade` upgrades it. A tau older than `tau setup` (0.5.0) is upgraded first.
#
# Environment:
#   TAU_INSTALL_VERSION=x.y.z  install this version of tau-core and tau-tui (default: latest)
#   TAU_INSTALL_NO_SETUP=1     install only; run `tau setup` yourself later

set -eu

UV_INSTALLER_URL="https://astral.sh/uv/install.sh"

say() {
  printf '%s\n' "$*"
}

fail() {
  printf 'tau install: %s\n' "$*" >&2
  exit 1
}

check_platform() {
  os=$(uname -s)
  arch=$(uname -m)
  case "$os" in
    Darwin) system="macOS" ;;
    Linux) system="Linux" ;;
    *) fail "tau runs on macOS and Linux; this system is $os." ;;
  esac
  case "$arch" in
    x86_64 | amd64 | arm64 | aarch64) ;;
    *) fail "tau needs a 64-bit x86 or ARM CPU; this one is $arch." ;;
  esac
}

check_version() {
  case "$1" in
    "") ;;
    [0-9]*)
      case "$1" in
        *[!0-9A-Za-z.+-]*) fail "TAU_INSTALL_VERSION=$1 is not a version like 0.4.0." ;;
      esac
      ;;
    *) fail "TAU_INSTALL_VERSION=$1 is not a version like 0.4.0." ;;
  esac
}

download() {
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL "$1"
  elif command -v wget >/dev/null 2>&1; then
    wget -qO- "$1"
  else
    fail "neither curl nor wget was found; install one of them and run this again."
  fi
}

find_uv() {
  if command -v uv >/dev/null 2>&1; then
    uv=$(command -v uv)
    return 0
  fi
  for dir in "${UV_INSTALL_DIR:-}" "${XDG_BIN_HOME:-}" "$HOME/.local/bin" "$HOME/.cargo/bin"; do
    if [ -n "$dir" ] && [ -x "$dir/uv" ]; then
      uv="$dir/uv"
      return 0
    fi
  done
  return 1
}

install_uv() {
  say "Installing uv with Astral's official installer ($UV_INSTALLER_URL)."
  installer=$(mktemp "${TMPDIR:-/tmp}/tau-uv-installer.XXXXXX")
  if ! download "$UV_INSTALLER_URL" >"$installer"; then
    rm -f "$installer"
    fail "the uv installer could not be downloaded from $UV_INSTALLER_URL."
  fi
  if ! sh "$installer"; then
    rm -f "$installer"
    fail "the uv installer failed; see its output above."
  fi
  rm -f "$installer"
  find_uv || fail "uv was installed but cannot be found; open a new terminal and run this again."
}

main() {
  check_platform
  version="${TAU_INSTALL_VERSION:-}"
  check_version "$version"
  if [ -n "$version" ]; then
    core="tau-core==$version"
    tui="tau-tui==$version"
  else
    core="tau-core"
    tui="tau-tui"
  fi

  have_uv=1
  find_uv || have_uv=0

  say "tau installer · $system $arch"
  say "This will:"
  if [ "$have_uv" = 0 ]; then
    say "  - install uv, the Python package manager, into ${UV_INSTALL_DIR:-$HOME/.local/bin}"
  fi
  say "  - install tau: uv tool install $core --with $tui"
  if [ "${TAU_INSTALL_NO_SETUP:-}" != 1 ]; then
    say "  - start tau setup, which asks which features you want"
  fi
  say "Nothing here runs with sudo."
  say ""

  if [ "$have_uv" = 0 ]; then
    install_uv
  fi

  if "$uv" tool list 2>/dev/null | grep -q '^tau-core '; then
    say "tau is already installed with uv; it is left as it is."
    say "tau setup adds features; tau setup --upgrade upgrades tau."
  else
    say "Installing tau..."
    "$uv" tool install "$core" --with "$tui" || fail "uv tool install $core failed; see above."
  fi

  bin_dir=$("$uv" tool dir --bin 2>/dev/null || true)
  if [ -n "$bin_dir" ] && [ -x "$bin_dir/tau" ]; then
    tau="$bin_dir/tau"
  elif command -v tau >/dev/null 2>&1; then
    tau=$(command -v tau)
  else
    fail "tau was installed but cannot be found; run \`uv tool update-shell\` and open a new terminal."
  fi
  case ":$PATH:" in
    *":$bin_dir:"*) ;;
    *)
      if [ -n "$bin_dir" ]; then
        say "Note: $bin_dir is not on your PATH yet. \`$uv tool update-shell\` adds it; then open a new terminal."
      fi
      ;;
  esac
  # An older tau (before 0.5.0) has no `tau setup`: upgrade it, then install it afresh.
  if ! "$tau" setup --help >/dev/null 2>&1; then
    say "This tau has no \`tau setup\` yet (it is older than 0.5.0); upgrading it..."
    # --refresh: a release minutes old may not be in uv's cached copy of the index yet.
    "$uv" tool upgrade --refresh tau-core >/dev/null 2>&1 || true
    if ! "$tau" setup --help >/dev/null 2>&1; then
      "$uv" tool install --force --refresh "$core" --with "$tui" || fail "uv tool install $core failed; see above."
    fi
    if ! "$tau" setup --help >/dev/null 2>&1; then
      fail "tau setup needs tau-core 0.5.0 or newer, and the package index does not offer it yet; try again in a few minutes."
    fi
  fi
  say ""

  if [ "${TAU_INSTALL_NO_SETUP:-}" = 1 ]; then
    say "Done. Run \`tau setup\` when you are ready."
    return 0
  fi
  if [ -t 0 ]; then
    exec "$tau" setup
  fi
  if (exec </dev/tty) 2>/dev/null; then
    exec "$tau" setup </dev/tty
  fi
  say "Done. There is no terminal to ask on here: run \`tau setup\` yourself."
}

main "$@"
