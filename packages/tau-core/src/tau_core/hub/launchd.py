"""launchd user agent management behind a small :class:`Launchctl` protocol.

Everything that touches the service manager or sends signals (``launchctl bootstrap``,
``bootout``, ``print``, ``kill``) goes through :class:`Launchctl`, so the CLI is tested with
:class:`FakeLaunchctl` and never loads a real agent or signals a real process by accident.
"""

from __future__ import annotations

import os
import plistlib
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from tau_core.config import Config
from tau_core.hub.state import write_text_atomic
from tau_core.hub.units import LABEL, PLIST_NAME, ServicePaths, render_plist

LAUNCHCTL = "/bin/launchctl"


class LaunchctlError(Exception):
    """A launchctl call failed; the message is meant for the user."""


class Launchctl(Protocol):
    def bootstrap(self, domain: str, plist: Path) -> None: ...

    def bootout(self, domain: str, label: str) -> None: ...

    def is_loaded(self, domain: str, label: str) -> bool: ...

    def kill(self, pid: int, sig: int) -> None: ...


def gui_domain() -> str:
    """The launchd domain of the logged-in user's GUI session, ``gui/<uid>``."""
    return f"gui/{os.getuid()}"


def launch_agents_dir() -> Path:
    return Path.home() / "Library" / "LaunchAgents"


class SystemLaunchctl:
    """The real ``/bin/launchctl`` (macOS) and ``os.kill``."""

    def __init__(self, executable: str = LAUNCHCTL):
        self.executable = executable

    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                [self.executable, *args], capture_output=True, text=True, timeout=30
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise LaunchctlError(f"launchctl could not be run: {exc}") from exc

    def _check(self, result: subprocess.CompletedProcess[str], action: str) -> None:
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip() or f"exit code {result.returncode}"
            raise LaunchctlError(f"launchctl {action} failed: {detail}")

    def bootstrap(self, domain: str, plist: Path) -> None:
        self._check(self._run("bootstrap", domain, str(plist)), "bootstrap")

    def bootout(self, domain: str, label: str) -> None:
        self._check(self._run("bootout", f"{domain}/{label}"), "bootout")

    def is_loaded(self, domain: str, label: str) -> bool:
        return self._run("print", f"{domain}/{label}").returncode == 0

    def kill(self, pid: int, sig: int) -> None:
        os.kill(pid, sig)


class FakeLaunchctl:
    """In-memory launchctl for tests: records calls, never touches launchd or processes.

    ``on_kill(pid, sig)`` lets a test play the process that receives the signal.
    """

    def __init__(self, *, on_kill: Callable[[int, int], None] | None = None):
        self.calls: list[tuple[Any, ...]] = []
        self.loaded: dict[str, Path] = {}  # "<domain>/<label>" → plist path
        self.killed: list[tuple[int, int]] = []
        self.on_kill = on_kill

    def bootstrap(self, domain: str, plist: Path) -> None:
        self.calls.append(("bootstrap", domain, Path(plist)))
        label = plistlib.loads(Path(plist).read_bytes())["Label"]
        target = f"{domain}/{label}"
        if target in self.loaded:
            raise LaunchctlError(f"launchctl bootstrap failed: {target} is already loaded")
        self.loaded[target] = Path(plist)

    def bootout(self, domain: str, label: str) -> None:
        self.calls.append(("bootout", domain, label))
        if self.loaded.pop(f"{domain}/{label}", None) is None:
            raise LaunchctlError(f"launchctl bootout failed: {domain}/{label} is not loaded")

    def is_loaded(self, domain: str, label: str) -> bool:
        return f"{domain}/{label}" in self.loaded

    def kill(self, pid: int, sig: int) -> None:
        self.calls.append(("kill", pid, sig))
        self.killed.append((pid, sig))
        if self.on_kill is not None:
            self.on_kill(pid, sig)


@dataclass(frozen=True)
class InstallResult:
    plist: Path
    replaced: bool  # an already loaded agent was booted out first


def _wait_unloaded(launchctl: Launchctl, domain: str, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while launchctl.is_loaded(domain, LABEL) and time.monotonic() < deadline:
        time.sleep(0.2)


def install_launch_agent(
    config: Config,
    launchctl: Launchctl,
    *,
    agents_dir: Path | None = None,
    domain: str | None = None,
    python: str | None = None,
    path: str | None = None,
) -> InstallResult:
    """Render the plist into ``~/Library/LaunchAgents`` and bootstrap it (idempotent)."""
    domain = domain or gui_domain()
    paths = ServicePaths.from_config(config, python=python, path=path)
    plist = (agents_dir or launch_agents_dir()) / PLIST_NAME
    Path(paths.log_dir).mkdir(parents=True, exist_ok=True)  # launchd does not create it
    replaced = launchctl.is_loaded(domain, LABEL)
    if replaced:
        launchctl.bootout(domain, LABEL)
        _wait_unloaded(launchctl, domain, timeout=10)
    write_text_atomic(plist, render_plist(paths), mode=0o644)
    launchctl.bootstrap(domain, plist)
    return InstallResult(plist=plist, replaced=replaced)


def uninstall_launch_agent(
    launchctl: Launchctl, *, agents_dir: Path | None = None, domain: str | None = None
) -> bool:
    """Boot the agent out (the hub gets SIGTERM) and delete the plist; False if neither existed."""
    domain = domain or gui_domain()
    plist = (agents_dir or launch_agents_dir()) / PLIST_NAME
    removed = False
    if launchctl.is_loaded(domain, LABEL):
        launchctl.bootout(domain, LABEL)
        removed = True
    if plist.exists():
        plist.unlink()
        removed = True
    return removed
