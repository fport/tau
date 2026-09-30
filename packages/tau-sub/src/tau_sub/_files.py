"""Private files: written atomically, mode 0600, in directories with mode 0700."""

from __future__ import annotations

import contextlib
import os
import tempfile
from pathlib import Path

FILE_MODE = 0o600
DIR_MODE = 0o700


def private_dir(path: Path) -> Path:
    """Create ``path`` (and missing parents) and make ``path`` itself 0700.

    Missing parents get the default mode, like ``mkdir -p``; only the leaf is tightened.
    """
    path.mkdir(mode=DIR_MODE, parents=True, exist_ok=True)
    os.chmod(path, DIR_MODE)
    return path


def write_private(path: Path, text: str, *, overwrite: bool) -> None:
    """Write ``text`` to ``path`` atomically with mode 0600.

    The text goes to a temporary file in the same directory first (``mkstemp`` creates it
    0600), is flushed to disk and then moved into place, so a reader never sees half a file.
    With ``overwrite=False`` an existing ``path`` raises ``FileExistsError`` and is left
    untouched: the move is a hard link, which fails when the name is taken.
    """
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, FILE_MODE)
        if overwrite:
            os.replace(tmp, path)
            return
        try:
            os.link(tmp, path)
        except FileExistsError:
            raise
        except OSError:
            # A filesystem without hard links: check, then move (a narrow race remains).
            if path.exists():
                raise FileExistsError(path) from None
            os.replace(tmp, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            tmp.unlink()
