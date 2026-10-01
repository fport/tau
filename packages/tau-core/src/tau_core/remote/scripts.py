"""The remote kit: ``infra/remote`` as the owner runs it, from a checkout or from tau-core.

The SSH and mosh part of remote access needs ``sudo``, so tau never runs it: it shows one
command, ``bash <kit>/setup-all.sh``, for the owner to run in their own terminal.

- **In a checkout** the kit is the repository's ``infra/remote``, the source of truth.
- **In an installed tau** there is no checkout, so tau-core ships a copy of ``infra/remote``
  (without its README) as package data in ``tau_core/remote/kit/``. It is written to
  ``<data dir>/remote/`` (``~/.local/share/tau/remote/``) before its command is shown: the
  scripts link ``tau-attach`` and source the tmux settings from their own directory, so that
  directory must stay put across upgrades, which a path inside the uv tool environment does not.

Why package data and not a download: the copy comes with the tau-core release the owner already
installed (its hashes in the wheel's RECORD), works offline, and always matches the running tau.
A download from GitHub raw would need network access, a pinned commit and a sha256 per release,
all for the same bytes. A test keeps the copy identical to ``infra/remote``.
"""

from __future__ import annotations

import os
import shlex
import tempfile
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path

from tau_core.remote.system import System

__all__ = [
    "ADD_KEY",
    "ENTRY",
    "KIT_DIR",
    "KitError",
    "kit_dir",
    "kit_files",
    "shell_path",
    "write_kit",
]

ENTRY = "setup-all.sh"
"""The one command: setup.sh + setup-sudo.sh on macOS, setup-linux.sh on Linux."""
ADD_KEY = "add-key.sh"
KIT_DIR = "remote"
"""The kit's directory under the data dir."""
_EXECUTABLE = ("bin/tau-attach",)


class KitError(OSError):
    """The kit could not be written; the message says where."""


def _walk(node: Traversable, prefix: str = "") -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    for child in node.iterdir():
        name = f"{prefix}{child.name}"
        if child.is_dir():
            if child.name != "__pycache__":
                files.update(_walk(child, f"{name}/"))
        elif child.is_file():
            files[name] = child.read_bytes()
    return files


def kit_files() -> dict[str, bytes]:
    """The kit shipped with tau-core: ``{relative path: content}``."""
    return _walk(resources.files("tau_core.remote") / "kit")


def _mode(name: str) -> int:
    return 0o755 if name.endswith(".sh") or name in _EXECUTABLE else 0o644


def write_kit(target: Path) -> Path:
    """Write the kit to ``target`` (mode 0700): every file whose content or mode differs is
    replaced atomically, anything else there (``config.local.env``) is left alone."""
    try:
        target.mkdir(parents=True, exist_ok=True, mode=0o700)
        if target.is_symlink() or not target.is_dir():
            raise KitError(f"{target} is not a directory")
        for name, content in sorted(kit_files().items()):
            path = target / name
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            mode = _mode(name)
            try:
                same = (
                    not path.is_symlink()
                    and path.read_bytes() == content
                    and (path.stat().st_mode & 0o777) == mode
                )
            except OSError:
                same = False
            if same:
                continue
            fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(content)
                os.chmod(tmp, mode)
                os.replace(tmp, path)  # replaces a symlink itself, never writes through it
            except BaseException:
                Path(tmp).unlink(missing_ok=True)
                raise
    except KitError:
        raise
    except OSError as exc:
        raise KitError(f"{target}: {exc.strerror or exc}") from None
    return target


def kit_dir(system: System, data: Path) -> Path:
    """The kit to show commands from: the checkout's ``infra/remote``, else the shipped copy
    written to ``<data>/remote``."""
    checkout = system.checkout()
    if checkout is not None:
        return checkout
    return write_kit(data / KIT_DIR)


def shell_path(path: Path, home: Path) -> str:
    """``path`` as the owner types it: ``~/…`` under the home directory, quoted when needed."""
    try:
        relative = path.relative_to(home)
    except ValueError:
        return shlex.quote(str(path))
    text = relative.as_posix()
    if text == ".":
        return "~"
    if shlex.quote(text) == text:
        return f"~/{text}"
    return shlex.quote(str(path))
