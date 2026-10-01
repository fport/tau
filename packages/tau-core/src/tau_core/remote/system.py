"""Everything ``tau remote`` reads from the machine goes through a :class:`System`.

The checks look at programs on ``PATH``, run ``tailscale status --json`` and one ``ssh`` probe,
connect to port 22 and read ``/etc/ssh`` and a few dot files. Tests pass a fake as
``obj["remote_system"]`` whose ``root`` and ``HOME`` are temporary directories, so no test runs
``tailscale`` or ``ssh``, reads the real ``/etc/ssh`` or touches the owner's home. Nothing here
ever runs ``sudo`` or a script of the kit.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from tau_core.setup.host import platform_name

__all__ = ["BREW_DIRS", "LocalSystem", "Ran", "System"]

BREW_DIRS = ("/opt/homebrew/bin", "/usr/local/bin")
"""Where Homebrew puts mosh and tmux on macOS. The tau app may start tau with a short PATH, so
these are searched as well."""


@dataclass(frozen=True)
class Ran:
    code: int
    """The exit code; 127 when the program could not start, 124 when it timed out."""
    out: str = ""
    err: str = ""


class System:
    """The machine as ``tau remote`` sees it; :class:`LocalSystem` is the real one."""

    platform: str
    environ: Mapping[str, str]
    root: Path = Path("/")
    """Absolute system paths (``/etc/ssh/...``, ``/Applications/...``) are looked up under it."""

    def which(self, program: str) -> str | None:
        raise NotImplementedError

    def run(self, argv: Sequence[str], *, timeout: float = 10.0) -> Ran:
        """Run ``argv`` quietly, stdin from ``/dev/null``."""
        raise NotImplementedError

    def port_open(self, port: int) -> bool:
        """Whether ``127.0.0.1:port`` accepts a TCP connection."""
        raise NotImplementedError

    def user(self) -> str:
        """The login name of the user running tau (``AllowUsers`` must name it)."""
        raise NotImplementedError

    def checkout(self) -> Path | None:
        """``infra/remote`` of the repository checkout tau runs from, if it does."""
        raise NotImplementedError

    # -- derived -------------------------------------------------------------------------------

    def path(self, absolute: str) -> Path:
        return self.root / absolute.lstrip("/")

    def home(self) -> Path:
        return Path(self.environ.get("HOME") or Path.home())

    def read(self, path: Path) -> str | None:
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None


class LocalSystem(System):
    def __init__(self) -> None:
        self.platform = platform_name()
        self.environ = os.environ

    def which(self, program: str) -> str | None:
        search = self.environ.get("PATH", os.defpath)
        if self.platform == "darwin":
            search = os.pathsep.join([search, *BREW_DIRS])
        return shutil.which(program, path=search)

    def run(self, argv: Sequence[str], *, timeout: float = 10.0) -> Ran:
        try:
            done = subprocess.run(
                list(argv),
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return Ran(124)
        except OSError:
            return Ran(127)
        return Ran(done.returncode, done.stdout, done.stderr)

    def port_open(self, port: int) -> bool:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=2):
                return True
        except OSError:
            return False

    def user(self) -> str:
        try:
            import pwd

            return pwd.getpwuid(os.getuid()).pw_name
        except (ImportError, KeyError):
            import getpass

            return getpass.getuser()

    def checkout(self) -> Path | None:
        import tau_core

        # <repo>/packages/tau-core/src/tau_core/__init__.py: an editable install from a checkout.
        repo = Path(tau_core.__file__).resolve().parents[4]
        remote = repo / "infra" / "remote"
        if (remote / "setup-all.sh").is_file() and (repo / "packages" / "tau-core").is_dir():
            return remote
        return None
