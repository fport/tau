"""``TAU_DATA_DIR/routines/``: the routines file and the routine log.

- ``routines.json`` holds ``{"version": 1, "routines": [...]}``. It is written atomically (a
  temporary file in the same directory, flushed to disk, then renamed over the old one) with
  mode ``0600``, in a directory with mode ``0700``.
- Every change is a read-modify-write under an exclusive lock on ``routines/.lock``
  (:meth:`RoutineStore.edit`), so ``tau routine``, the tools and the hub's engine never lose
  each other's changes. Plain reads take no lock: the rename shows them the old file or the
  new one, never half of one. The engine notices changes through :meth:`RoutineStore.stamp`.
- An entry that does not parse (a hand edit gone wrong) is skipped with a warning and written
  back unchanged, so one bad entry neither stops the other routines nor gets lost.
- ``log.jsonl`` gets one JSON object per firing (and per registration, change and removal);
  at 512 KiB it is rotated to ``log.jsonl.1``, keeping three old files.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import logging
import os
import secrets
import tempfile
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tau_core import Config

from tau_routines.model import ID_RE, Routine, stamp
from tau_routines.settings import RoutineError

__all__ = [
    "DIR_MODE",
    "FILE_MODE",
    "FILE_VERSION",
    "LOG_BACKUPS",
    "LOG_MAX_BYTES",
    "RoutineNotFound",
    "RoutineStore",
    "RoutineStoreError",
    "find_routine",
]

logger = logging.getLogger(__name__)

FILE_VERSION = 1
FILE_MODE = 0o600
DIR_MODE = 0o700
LOG_MAX_BYTES = 512 * 1024
LOG_BACKUPS = 3


class RoutineStoreError(RoutineError):
    """``routines.json`` cannot be read or written."""


class RoutineNotFound(RoutineError):
    """No routine has this id or name."""


def find_routine(routines: list[Routine], ref: str) -> Routine:
    """The routine whose id is ``ref``, else the one whose name is ``ref`` (ignoring case)."""
    wanted = " ".join(str(ref).split())
    for routine in routines:
        if routine.id == wanted:
            return routine
    named = [r for r in routines if r.name.casefold() == wanted.casefold()]
    if len(named) == 1:
        return named[0]
    if len(named) > 1:
        ids = ", ".join(r.id for r in named)
        raise RoutineNotFound(f"Several routines are called {wanted!r} ({ids}); use the id.")
    raise RoutineNotFound(f"No routine has the id or name {wanted!r}.")


@dataclass
class _Contents:
    routines: list[Routine]
    unreadable: list[Any]
    """Entries that did not parse, written back as they are."""


class RoutineStore:
    """The routines of one tau, under ``root`` (``TAU_DATA_DIR/routines``)."""

    def __init__(self, root: Path, *, clock: Callable[[], datetime] | None = None):
        self.root = Path(root)
        self._clock = clock or (lambda: datetime.now(UTC))
        """Stamps log entries that bring no ``at`` of their own."""
        self._held = threading.local()

    @classmethod
    def for_config(
        cls, config: Config, *, clock: Callable[[], datetime] | None = None
    ) -> RoutineStore:
        return cls(config.data_dir / "routines", clock=clock)

    @property
    def path(self) -> Path:
        return self.root / "routines.json"

    @property
    def log_path(self) -> Path:
        return self.root / "log.jsonl"

    @property
    def lock_path(self) -> Path:
        return self.root / ".lock"

    # -- reading -------------------------------------------------------------------------

    def stamp(self) -> tuple[int, int, int] | None:
        """``(mtime_ns, size, inode)`` of ``routines.json``; ``None`` when there is none. A
        change means someone wrote the file (each write is a new inode)."""
        try:
            info = os.stat(self.path)
        except FileNotFoundError:
            return None
        return info.st_mtime_ns, info.st_size, info.st_ino

    def _read(self) -> _Contents:
        try:
            text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return _Contents([], [])
        except OSError as exc:
            raise RoutineStoreError(f"{self.path} cannot be read: {exc.strerror or exc}") from exc
        try:
            data = json.loads(text)
        except ValueError as exc:
            raise RoutineStoreError(f"{self.path} is not valid JSON: {exc}") from exc
        if not isinstance(data, dict) or not isinstance(data.get("routines"), list):
            raise RoutineStoreError(f'{self.path} must hold {{"version": 1, "routines": [...]}}.')
        version = data.get("version")
        if version != FILE_VERSION:
            raise RoutineStoreError(
                f"{self.path} has version {version!r}; this tau-routines reads version "
                f"{FILE_VERSION}."
            )
        contents = _Contents([], [])
        seen: set[str] = set()
        for raw in data["routines"]:
            try:
                routine = Routine.from_dict(raw)
            except RoutineError as exc:
                logger.warning("routines: skipping an entry of %s: %s", self.path, exc)
                contents.unreadable.append(raw)
                continue
            if routine.id in seen:
                logger.warning("routines: skipping a second routine with the id %s", routine.id)
                contents.unreadable.append(raw)
                continue
            seen.add(routine.id)
            contents.routines.append(routine)
        return contents

    def load(self) -> list[Routine]:
        """Every routine that parses, in file order."""
        return self._read().routines

    def get(self, ref: str) -> Routine:
        return find_routine(self.load(), ref)

    # -- writing -------------------------------------------------------------------------

    def _private_root(self) -> None:
        self.root.mkdir(mode=DIR_MODE, parents=True, exist_ok=True)
        os.chmod(self.root, DIR_MODE)

    @contextlib.contextmanager
    def _locked(self) -> Iterator[None]:
        """The exclusive lock; re-entrant within one thread (``flock`` on a second descriptor
        of the same file would wait for the first one forever)."""
        if getattr(self._held, "depth", 0):
            self._held.depth += 1
            try:
                yield
            finally:
                self._held.depth -= 1
            return
        self._private_root()
        fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, FILE_MODE)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            self._held.depth = 1
            yield
        finally:
            self._held.depth = 0
            with contextlib.suppress(OSError):
                fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def _write(self, contents: _Contents) -> None:
        data = {
            "version": FILE_VERSION,
            "routines": [r.to_dict() for r in contents.routines] + contents.unreadable,
        }
        text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
        fd, tmp_name = tempfile.mkstemp(prefix=".routines.", suffix=".tmp", dir=self.root)
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(tmp, FILE_MODE)
            os.replace(tmp, self.path)
        finally:
            with contextlib.suppress(FileNotFoundError):
                tmp.unlink()

    @contextlib.contextmanager
    def edit(self) -> Iterator[list[Routine]]:
        """Change the routines under the lock: the block gets the current list, changes it in
        place, and the file is written when the block ends without an exception and the list
        changed."""
        with self._locked():
            contents = self._read()
            before = [r.to_dict() for r in contents.routines]
            yield contents.routines
            if [r.to_dict() for r in contents.routines] != before:
                try:
                    self._write(contents)
                except OSError as exc:
                    raise RoutineStoreError(
                        f"{self.path} cannot be written: {exc.strerror or exc}"
                    ) from exc

    def new_id(self, routines: list[Routine]) -> str:
        """A fresh 8-hex-digit id that no routine in the file has."""
        taken = {r.id for r in routines}
        with contextlib.suppress(RoutineStoreError):
            taken |= {
                raw.get("id")
                for raw in self._read().unreadable
                if isinstance(raw, dict) and isinstance(raw.get("id"), str)
            }
        while True:
            candidate = secrets.token_hex(4)
            if candidate not in taken and ID_RE.match(candidate):
                return candidate

    # -- the log -------------------------------------------------------------------------

    def _rotate(self) -> None:
        try:
            size = self.log_path.stat().st_size
        except FileNotFoundError:
            return
        if size < LOG_MAX_BYTES:
            return
        for index in range(LOG_BACKUPS - 1, 0, -1):
            older = self.log_path.with_name(f"{self.log_path.name}.{index}")
            if older.exists():
                os.replace(older, self.log_path.with_name(f"{self.log_path.name}.{index + 1}"))
        os.replace(self.log_path, self.log_path.with_name(f"{self.log_path.name}.1"))

    def log(self, status: str, routine: Routine | None = None, **fields: Any) -> dict[str, Any]:
        """Append one entry to ``log.jsonl``; returns it. A failing write is logged, never
        raised: the log must not stop a routine."""
        entry: dict[str, Any] = {"at": fields.pop("at", None) or stamp(self._clock())}
        if routine is not None:
            entry |= {"id": routine.id, "name": routine.name, "tool": routine.tool}
        entry["status"] = status
        entry |= {k: v for k, v in fields.items() if v is not None}
        line = json.dumps(entry, ensure_ascii=False, default=str) + "\n"
        try:
            with self._locked():
                self._rotate()
                fd = os.open(self.log_path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, FILE_MODE)
                with os.fdopen(fd, "a", encoding="utf-8") as handle:
                    handle.write(line)
        except OSError as exc:
            logger.error("routines: %s cannot be written: %s", self.log_path, exc)
        return entry

    def read_log(self, *, limit: int = 20, routine_id: str | None = None) -> list[dict[str, Any]]:
        """The last ``limit`` entries, oldest first (of one routine when ``routine_id``)."""
        names = [f"{self.log_path.name}.{i}" for i in range(LOG_BACKUPS, 0, -1)]
        entries: list[dict[str, Any]] = []
        for name in [*names, self.log_path.name]:
            try:
                lines = self.log_path.with_name(name).read_text(encoding="utf-8").splitlines()
            except (FileNotFoundError, OSError):
                continue
            for line in lines:
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(entry, dict):
                    continue
                if routine_id is not None and entry.get("id") != routine_id:
                    continue
                entries.append(entry)
        return entries[-limit:] if limit > 0 else entries
