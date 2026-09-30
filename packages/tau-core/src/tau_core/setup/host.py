"""Everything ``tau setup`` does to the machine goes through a :class:`Host`.

The real one (:class:`SystemHost`) runs subprocesses, re-executes the process and asks the
package metadata; tests pass a fake as ``obj["setup_host"]`` in the click context, so no test
ever runs ``uv``, a real ``tau`` step, a network key check or ``os.execv``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping, MutableMapping, Sequence
from importlib import metadata
from pathlib import Path

from tau_core.builder import KeyCheck, check_provider_key

__all__ = ["Host", "LineSink", "SystemHost", "platform_name"]

LineSink = Callable[[str], None]
"""Receives one line of a captured subprocess's output, without the newline."""


def platform_name(value: str | None = None) -> str:
    """``darwin`` or ``linux`` (``sys.platform`` names); anything else as it is."""
    value = sys.platform if value is None else value
    return "linux" if value.startswith("linux") else value


class Host:
    """The side effects of ``tau setup``. Every method has a real implementation in
    :class:`SystemHost`; a test subclass overrides what it needs."""

    platform: str
    environ: MutableMapping[str, str]
    prefix: Path
    """``sys.prefix``: a uv tool environment holds ``uv-receipt.toml`` here."""
    root: Path = Path("/")
    """Where the catalog's absolute paths (``/Applications/tau.app``) are looked up."""

    def tau(self) -> list[str]:
        """The argv that runs this installation's ``tau``."""
        raise NotImplementedError

    def which(self, program: str) -> str | None:
        raise NotImplementedError

    def version_of(self, distribution: str) -> str | None:
        """The installed version of ``distribution`` in this environment, else ``None``."""
        raise NotImplementedError

    def run(
        self,
        argv: Sequence[str],
        *,
        on_line: LineSink | None = None,
        env: Mapping[str, str] | None = None,
    ) -> int:
        """Run ``argv`` and return its exit code.

        Without ``on_line`` the child inherits the terminal (stdin, stdout, stderr): an
        interactive step talks to the owner directly. With ``on_line`` its stdin is
        ``/dev/null`` and every line of stdout and stderr goes to ``on_line``. A program that
        cannot start raises ``OSError``."""
        raise NotImplementedError

    def capture(self, argv: Sequence[str]) -> tuple[int, str]:
        """Run ``argv`` quietly: ``(exit code, stdout)``; stderr is dropped."""
        raise NotImplementedError

    def execv(self, path: str, argv: Sequence[str]) -> None:
        """Replace this process with ``argv`` (returns only when that fails, by raising)."""
        raise NotImplementedError

    def key_check(self, provider: str, key: str) -> KeyCheck:
        raise NotImplementedError

    def stdin_isatty(self) -> bool:
        raise NotImplementedError

    def read_stdin(self, limit: int) -> str:
        """Up to ``limit`` characters of stdin (JSON mode's input object)."""
        raise NotImplementedError

    def over_ssh(self) -> bool:
        return bool(self.environ.get("SSH_CONNECTION") or self.environ.get("SSH_TTY"))


class SystemHost(Host):
    def __init__(self) -> None:
        self.platform = platform_name()
        self.environ = os.environ
        self.prefix = Path(sys.prefix)

    def tau(self) -> list[str]:
        return [sys.executable, "-m", "tau_core"]

    def which(self, program: str) -> str | None:
        return shutil.which(program, path=self.environ.get("PATH"))

    def version_of(self, distribution: str) -> str | None:
        try:
            return metadata.version(distribution)
        except metadata.PackageNotFoundError:
            return None

    def run(
        self,
        argv: Sequence[str],
        *,
        on_line: LineSink | None = None,
        env: Mapping[str, str] | None = None,
    ) -> int:
        environment = dict(self.environ if env is None else env)
        if on_line is None:
            sys.stdout.flush()
            sys.stderr.flush()
            return subprocess.run(list(argv), env=environment, check=False).returncode
        with subprocess.Popen(
            list(argv),
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        ) as process:
            assert process.stdout is not None
            for line in process.stdout:
                on_line(line.rstrip("\r\n"))
            return process.wait()

    def capture(self, argv: Sequence[str]) -> tuple[int, str]:
        try:
            result = subprocess.run(
                list(argv),
                env=dict(self.environ),
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return 127, ""
        return result.returncode, result.stdout

    def execv(self, path: str, argv: Sequence[str]) -> None:
        sys.stdout.flush()
        sys.stderr.flush()
        os.execv(path, list(argv))

    def key_check(self, provider: str, key: str) -> KeyCheck:
        return check_provider_key(provider, key)

    def stdin_isatty(self) -> bool:
        try:
            return sys.stdin.isatty()
        except (AttributeError, ValueError):
            return False

    def read_stdin(self, limit: int) -> str:
        if self.stdin_isatty():
            return ""
        return sys.stdin.read(limit + 1)
