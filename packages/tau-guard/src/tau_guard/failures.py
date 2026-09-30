"""``TAU_DATA_DIR/guard/failures.json``: the failure count and the cooldown across hub restarts.

A hub restart (TauBar's "Run the hub" switch, a crash-restart, ``tau hub stop`` and ``run``)
must not reset the rate limit on failed checks (ADR 0008 decision 13), so the service writes
:meth:`tau_guard.state.GuardMachine.failure_state` here whenever it changes and hands it back
to :meth:`~tau_guard.state.GuardMachine.restore_failures` at start. The state holds wall times
only (the monotonic clock starts over with every boot); the machine converts them back.

The file is 0600 in the 0700 ``guard/`` directory and replaced atomically (a temporary file,
``fsync``, ``os.replace``), so a crash never leaves half a file. It holds counts and times,
nothing about a face. A missing file is a clean start; an unreadable or malformed one is
ignored with a warning in the hub log.
"""

from __future__ import annotations

import json
import logging
import os
from contextlib import suppress
from pathlib import Path
from typing import Any

from tau_guard.audit import secure_dir

__all__ = ["FAILURES_FILE", "MAX_BYTES", "FailureFile"]

logger = logging.getLogger(__name__)

FAILURES_FILE = "failures.json"
MAX_BYTES = 16 * 1024


class FailureFile:
    """Reads and writes ``directory/failures.json``."""

    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)
        self.path = self.directory / FAILURES_FILE

    def load(self) -> object | None:
        """The saved state (validated by the machine), ``None`` without a readable file."""
        try:
            with self.path.open("rb") as handle:
                raw = handle.read(MAX_BYTES + 1)
        except FileNotFoundError:
            return None
        except OSError as exc:
            logger.warning("guard: %s could not be read (%s); starting without it", self.path, exc)
            return None
        if len(raw) > MAX_BYTES:
            logger.warning("guard: %s is too large; starting without it", self.path)
            return None
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError, RecursionError):
            logger.warning("guard: %s is not valid JSON; starting without it", self.path)
            return None

    def save(self, state: dict[str, Any]) -> None:
        """Replace the file with ``state``; an error is logged, never raised."""
        data = (json.dumps(state, separators=(",", ":")) + "\n").encode("utf-8")
        temporary = self.directory / f".{FAILURES_FILE}.tmp"
        try:
            secure_dir(self.directory)
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            try:
                os.fchmod(fd, 0o600)
                os.write(fd, data)
                os.fsync(fd)
            finally:
                os.close(fd)
            os.replace(temporary, self.path)
        except OSError as exc:
            logger.error("guard: %s could not be written: %s", self.path, exc)
            with suppress(OSError):
                temporary.unlink()
