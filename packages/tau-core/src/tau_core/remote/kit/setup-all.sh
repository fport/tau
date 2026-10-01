#!/usr/bin/env bash
# Remote access in one command: the command `tau setup` → Remote access (and `tau remote ssh`)
# shows. Run it as your normal user in your own terminal, not with sudo: sudo asks for your
# password only for the steps that need root, and tau never runs this script for you.
# Running it again is safe.
#
#   macOS  setup.sh (tmux, mosh, the ~/.zshenv and ~/.tmux.conf blocks, tau-attach, keep-awake),
#          then setup-sudo.sh (Tailscale.app, the sshd drop-in, Remote Login)
#   Linux  setup-linux.sh (openssh-server, mosh and tmux from the distribution, the sshd
#          drop-in, the ~/.tmux.conf block, tau-attach, the SSH service)
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"

if [[ $EUID -eq 0 ]]; then
  echo "Run it as your normal user, not with sudo: it asks for the password where it needs root." >&2
  exit 1
fi

# setup.sh then leaves out its "Next steps": the next step runs right here.
export TAU_REMOTE_ALL=1
case "$(uname -s)" in
  Darwin)
    bash "$here/setup.sh"
    bash "$here/setup-sudo.sh"
    ;;
  Linux)
    bash "$here/setup-linux.sh"
    ;;
  *)
    echo "Remote access is set up on macOS and Linux only." >&2
    exit 1
    ;;
esac

printf '\nDone. Check it with: tau remote status\n'
printf 'Then add the phone key (%s/add-key.sh) and set up Termius: tau remote phone\n' "$here"
