"""Remote access: reach the hub from the phone over Tailscale, SSH, mosh and tmux (issue 173).

- :mod:`~tau_core.remote.checks` checks Tailscale, sshd with tau's drop-in, mosh and tmux, and
  the values Termius needs; :mod:`~tau_core.remote.cli` is ``tau remote``.
- :mod:`~tau_core.remote.scripts` finds the kit (``infra/remote`` in a checkout, the copy
  shipped in ``tau_core/remote/kit/`` otherwise) whose one command, ``setup-all.sh``, the owner
  runs in their own terminal. tau shows it and never runs it: it needs ``sudo``.

It lives in tau-core, not in a package of its own: ``infra/remote`` belongs to this repository,
the checks need nothing beyond the standard library, and ``tau setup`` offers remote access on a
bare install, where only tau-core is there. ``tau setup`` runs these checks as subprocesses
(``tau remote tailscale|ssh|phone --json``), like every other feature step.
"""

from __future__ import annotations

from tau_core.setup import strings as _strings  # noqa: F401 - registers the message keys
