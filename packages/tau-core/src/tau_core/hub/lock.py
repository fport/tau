"""Single-instance lock: ``fcntl.flock`` on ``<hub_dir>/hub.lock``.

The kernel drops the lock when the holder dies (even on ``kill -9``), so a stale lock file never
blocks the next start. The holder writes its pid into the file for error messages and
``tau hub stop``; the file itself is never deleted (deleting a lock file invites races).
"""

from __future__ import annotations

import fcntl
import os
from contextlib import suppress
from pathlib import Path
from types import TracebackType

ALREADY_RUNNING = "tau hub zaten çalışıyor (pid {pid}). Aynı makinede tek hub çalışabilir."


class AlreadyRunning(Exception):
    """Another process holds the hub lock. The message is Turkish and meant for the user."""

    def __init__(self, pid: int | None):
        self.pid = pid
        super().__init__(ALREADY_RUNNING.format(pid=pid if pid is not None else "?"))


def _read_pid(fd: int) -> int | None:
    with suppress(OSError):
        os.lseek(fd, 0, os.SEEK_SET)
        raw = os.read(fd, 64).decode("ascii", errors="ignore").strip()
        if raw.isdigit():
            return int(raw)
    return None


class HubLock:
    """``acquire()`` or raise :class:`AlreadyRunning`; ``release()`` when done."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._fd: int | None = None

    @property
    def held(self) -> bool:
        return self._fd is not None

    def acquire(self) -> None:
        if self._fd is not None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            pid = _read_pid(fd)
            os.close(fd)
            raise AlreadyRunning(pid) from None
        except BaseException:
            os.close(fd)
            raise
        os.ftruncate(fd, 0)
        os.lseek(fd, 0, os.SEEK_SET)
        os.write(fd, f"{os.getpid()}\n".encode("ascii"))
        self._fd = fd

    def release(self) -> None:
        if self._fd is None:
            return
        fd, self._fd = self._fd, None
        with suppress(OSError):
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)

    def __enter__(self) -> HubLock:
        self.acquire()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.release()

    @staticmethod
    def probe(path: Path) -> tuple[bool, int | None]:
        """``(held, pid)`` without keeping the lock: is a hub running, and which pid wrote it."""
        try:
            fd = os.open(path, os.O_RDONLY)
        except FileNotFoundError:
            return False, None
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
            except BlockingIOError:
                return True, _read_pid(fd)
            fcntl.flock(fd, fcntl.LOCK_UN)
            return False, None
        finally:
            os.close(fd)
