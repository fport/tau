#!/usr/bin/env bash
# Remove TauBar's sudoers rule and make sure the Mac can sleep again (pmset disablesleep 0).
# Run it in your own terminal; sudo asks for your password.
#
#   apps/taubar/sudoers/uninstall-sudoers.sh           # reset disablesleep, remove the rule
#   apps/taubar/sudoers/uninstall-sudoers.sh --print   # only show what it would do (no sudo)
set -euo pipefail

target=/etc/sudoers.d/tau-taubar

if [[ "${1:-}" == --print ]]; then
  echo "sudo /usr/bin/pmset -a disablesleep 0"
  if [[ -e "$target" ]]; then
    echo "sudo /bin/rm -f $target"
  else
    echo "# $target is not installed; nothing to remove"
  fi
  exit 0
fi

# First re-enable sleep, so removing the rule can never leave the Mac unable to sleep.
sudo /usr/bin/pmset -a disablesleep 0
if [[ -e "$target" ]]; then
  sudo /bin/rm -f "$target"
  echo "Removed $target."
else
  echo "$target was not installed."
fi
echo "Sleep is enabled again. TauBar shows the lid-closed mode as unavailable within a few seconds."
