#!/usr/bin/env bash
# Install the one sudoers rule the tau app's "Keep awake with the lid closed" mode needs: your user
# may run exactly `/usr/bin/pmset -a disablesleep 0` and `... 1` as root without a password.
# Nothing else. Run it in your own terminal; sudo asks for your password.
#
#   apps/tau/sudoers/install-sudoers.sh           # render, check and install
#   apps/tau/sudoers/install-sudoers.sh --print   # only render and check (no sudo)
#
# Undo: apps/tau/sudoers/uninstall-sudoers.sh
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
target=/etc/sudoers.d/tau-taubar
user="$(id -un)"

if [[ "$user" == root ]]; then
  echo "Run this as your own user, not as root: the rule is for the user who runs tau." >&2
  exit 1
fi
if [[ ! "$user" =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "Unexpected user name '$user'; not writing a sudoers rule for it." >&2
  exit 1
fi

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
sed "s/__USER__/$user/g" "$here/tau-taubar.sudoers" > "$tmp"
chmod 0440 "$tmp"
if ! /usr/sbin/visudo -c -q -f "$tmp"; then
  echo "The rendered rule did not pass visudo; nothing was installed." >&2
  exit 1
fi

if [[ "${1:-}" == --print ]]; then
  cat "$tmp"
  echo "# checked with visudo; not installed (run without --print to install $target)"
  exit 0
fi

if [[ ! -d /etc/sudoers.d ]]; then
  echo "/etc/sudoers.d does not exist; this macOS does not read drop-in sudoers files." >&2
  exit 1
fi

echo "Installing $target:"
cat "$tmp"
sudo /usr/bin/install -m 0440 -o root -g wheel "$tmp" "$target"
if ! sudo /usr/sbin/visudo -c -q; then
  # Never leave a sudoers configuration that does not parse.
  sudo /bin/rm -f "$target"
  echo "The sudoers configuration did not parse with the rule; it was removed again." >&2
  exit 1
fi
if sudo -n -l /usr/bin/pmset -a disablesleep 1 >/dev/null 2>&1; then
  echo "Done. tau offers \"Keep awake with the lid closed\" within a few seconds."
else
  echo "Installed, but sudo does not allow the command yet: check that /etc/sudoers" >&2
  echo "includes /private/etc/sudoers.d (macOS does by default)." >&2
  exit 1
fi
