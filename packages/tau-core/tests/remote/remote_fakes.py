"""A fake :class:`~tau_core.remote.system.System` for the ``tau remote`` tests.

Nothing here touches the machine: ``/etc/ssh`` and ``/Applications`` live under ``tmp_path /
"root"``, ``HOME`` is ``tmp_path / "user"``, ``run`` answers ``tailscale status --json`` and the
``ssh`` password probe from fields and records every argv, and port 22 is a boolean. The values
are examples (``my-mac.tailXXXXXX.ts.net``, the first address of the tailnet range).
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from tau_core.remote.checks import BLOCK, MAC_APP_CLI, SSHD_CONF, render_template
from tau_core.remote.system import Ran, System

HOST = "my-mac.tailXXXXXX.ts.net"
IP = "100.64.0.1"
USER = "alice"
RUNNING: dict[str, Any] = {
    "BackendState": "Running",
    "Self": {
        "DNSName": f"{HOST}.",
        "HostName": "my-mac",
        "TailscaleIPs": [IP, "fd7a:115c:a1e0::1"],
    },
    "CurrentTailnet": {"MagicDNSEnabled": True},
}
LOGGED_OUT: dict[str, Any] = {"BackendState": "NeedsLogin", "Self": {"TailscaleIPs": []}}
DENIED = f"{USER}@127.0.0.1: Permission denied (publickey)."
KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExampleExampleExampleExampleExampleExample iphone"
ALL = ("tailscale", "ssh", "mosh", "mosh-server", "tmux", "brew", "tau-attach")


class FakeSystem(System):
    def __init__(
        self,
        tmp_path: Path,
        *,
        platform: str = "darwin",
        programs: Sequence[str] = ("ssh",),
        port: bool = False,
        tailscale: Mapping[str, Any] | None = RUNNING,
        tailscale_code: int = 0,
        probe: str = DENIED,
        checkout: Path | None = None,
        environ: Mapping[str, str] | None = None,
    ):
        self.platform = platform
        self.root = tmp_path / "root"
        self.root.mkdir(exist_ok=True)
        self.homedir = tmp_path / "user"
        self.homedir.mkdir(exist_ok=True)
        self.environ = {
            "HOME": str(self.homedir),
            "TAU_HOME": str(tmp_path / "tau-home"),
            "PATH": "/fake/bin",
            **(environ or {}),
        }
        self.programs = set(programs)
        self.port = port
        self.tailscale = tailscale
        self.tailscale_code = tailscale_code
        self.probe = probe
        self._checkout = checkout
        self.runs: list[list[str]] = []

    # -- the System API ------------------------------------------------------------------------

    def which(self, program: str) -> str | None:
        return f"/fake/bin/{program}" if program in self.programs else None

    def run(self, argv: Sequence[str], *, timeout: float = 10.0) -> Ran:
        self.runs.append(list(argv))
        if list(argv[1:]) == ["status", "--json"]:
            out = json.dumps(self.tailscale) if self.tailscale is not None else ""
            err = "" if self.tailscale is not None else "failed to connect to local tailscaled"
            return Ran(self.tailscale_code, out, err)
        if argv and os.path.basename(argv[0]) == "ssh":
            return Ran(255, "", self.probe)
        return Ran(127)

    def port_open(self, port: int) -> bool:
        return self.port and port == 22

    def user(self) -> str:
        return USER

    def checkout(self) -> Path | None:
        return self._checkout

    # -- helpers for the tests -------------------------------------------------------------------

    def write(self, absolute: str, text: str) -> Path:
        path = self.path(absolute)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def app(self) -> None:
        """Tailscale.app with its CLI inside, as the App Store installs it."""
        self.write(MAC_APP_CLI, "#!/bin/sh\n")

    def harden(self, dropin: str | None = None) -> None:
        """tau's drop-in as setup-sudo.sh writes it, and a main config that includes it."""
        self.write(SSHD_CONF, dropin if dropin is not None else render_template(USER))
        self.write(
            "/etc/ssh/sshd_config",
            "Include /etc/ssh/sshd_config.d/*\nUsePAM yes\nSubsystem sftp /usr/libexec/sftp\n",
        )

    def dotfiles(self) -> None:
        for name in (".zshenv", ".tmux.conf"):
            (self.homedir / name).write_text(f"{BLOCK}\nsomething\n# <<< tau:remote <<<\n")

    def key(self, mode: int = 0o600) -> None:
        ssh = self.homedir / ".ssh"
        ssh.mkdir(mode=0o700, exist_ok=True)
        path = ssh / "authorized_keys"
        path.write_text(f"# the phone\n{KEY}\n", encoding="utf-8")
        path.chmod(mode)

    def ready(self) -> FakeSystem:
        """Everything remote access needs, as after setup-all.sh and add-key.sh."""
        self.programs |= set(ALL)
        self.port = True
        self.harden()
        self.dotfiles()
        self.key()
        return self

    def tailscale_runs(self) -> list[list[str]]:
        return [argv for argv in self.runs if argv[1:] == ["status", "--json"]]

    def ssh_runs(self) -> list[list[str]]:
        return [argv for argv in self.runs if os.path.basename(argv[0]) == "ssh"]
