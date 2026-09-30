"""``TAU_DATA_DIR/guard/audit.jsonl``: what the guard did, one JSON object per line (ADR 0008
decision 13).

Schema (version 1)::

    {v: 1, at, event, channel, client_id, trigger, ok, reason, score?, liveness?,
     duration_ms, request_id?, tool?}

- ``at`` is UTC ISO 8601 with seconds; ``event`` is one of :data:`EVENTS`.
- ``channel``, ``client_id``, ``trigger``, ``ok``, ``reason`` and ``duration_ms`` are always
  present (``null`` when they do not apply); ``score`` (rounded to 2 decimals), ``liveness``,
  ``request_id`` and ``tool`` only when set. ``liveness`` is ``challenge`` or ``passive`` for a
  face match, and for a ``spoof`` the code of the liveness rule that failed
  (:data:`tau_guard.liveness.FAILURES`).
- A record never holds an embedding, a frame or anything about another person: only the keys
  above, each a string, a bool, a small number or ``null``.
- Strings are cut to 128 characters and every non-printable character (C0 and C1 controls such
  as ESC and CR, bidi overrides) becomes ``?``: a caller-supplied label such as ``channel``
  or ``tool`` can never drive the owner's terminal when ``tau guard log`` prints it.

The file is 0600 in the 0700 ``guard/`` directory (both chmod explicitly), rotated at
:data:`MAX_BYTES` with :data:`KEEP` files in all (``audit.jsonl``, ``audit.jsonl.1``,
``audit.jsonl.2``). ``tau guard log`` reads it through :meth:`AuditLog.read`.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from collections.abc import Callable, Iterator
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

__all__ = [
    "AUDIT_FILE",
    "EVENTS",
    "KEEP",
    "MAX_BYTES",
    "OPTIONAL_KEYS",
    "REQUIRED_KEYS",
    "AuditLog",
    "printable",
    "secure_dir",
]

logger = logging.getLogger(__name__)

AUDIT_FILE = "audit.jsonl"
MAX_BYTES = 1024 * 1024
KEEP = 3
VERSION = 1
EVENTS = (
    "verify",
    "step_up",
    "recheck",
    "lock",
    "unlock",
    "enroll",
    "forget",
    "cooldown",
    "camera_open",
    "touch_id",
)
REQUIRED_KEYS = (
    "v",
    "at",
    "event",
    "channel",
    "client_id",
    "trigger",
    "ok",
    "reason",
    "duration_ms",
)
OPTIONAL_KEYS = ("score", "liveness", "request_id", "tool")
MAX_TEXT = 128


def secure_dir(path: Path) -> Path:
    """Create ``path`` if needed and chmod it 0700 (``mkdir(mode=)`` alone does not change an
    existing directory)."""
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path, 0o700)
    return path


def printable(value: str) -> str:
    """``value`` with every non-printable character replaced by ``?``."""
    if value.isprintable():
        return value
    return "".join(char if char.isprintable() else "?" for char in value)


def _text(value: Any) -> str | None:
    """A string field: only a string is kept (cut to 128 characters, see :func:`printable`);
    anything else is null, so no list, number array or object can ever reach a record."""
    return printable(value[:MAX_TEXT]) if isinstance(value, str) else None


def _utc(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="seconds")


class AuditLog:
    """Appends records to ``directory/audit.jsonl`` and reads them back.

    ``now`` returns the wall time (UTC); tests pass a fake clock's ``wall``."""

    def __init__(self, directory: Path, *, now: Callable[[], datetime] | None = None) -> None:
        self.directory = Path(directory)
        self.path = self.directory / AUDIT_FILE
        self._now = now or (lambda: datetime.now(UTC))
        self._lock = threading.Lock()

    def files(self) -> list[Path]:
        """The log files, oldest first."""
        rotated = [self.directory / f"{AUDIT_FILE}.{i}" for i in range(KEEP - 1, 0, -1)]
        return [p for p in [*rotated, self.path] if p.is_file()]

    def record(
        self,
        event: str,
        *,
        channel: str | None = None,
        client_id: str | None = None,
        trigger: str | None = None,
        ok: bool | None = None,
        reason: str | None = None,
        score: float | None = None,
        liveness: str | None = None,
        duration_ms: int | None = None,
        request_id: str | None = None,
        tool: str | None = None,
    ) -> dict[str, Any]:
        """Append one record and return it. ``event`` must be one of :data:`EVENTS`."""
        if event not in EVENTS:
            raise ValueError(f"unknown audit event {event!r}")
        entry: dict[str, Any] = {
            "v": VERSION,
            "at": _utc(self._now()),
            "event": event,
            "channel": _text(channel),
            "client_id": _text(client_id),
            "trigger": _text(trigger),
            "ok": ok if isinstance(ok, bool) else None,
            "reason": _text(reason),
            "duration_ms": (
                int(duration_ms)
                if isinstance(duration_ms, int | float) and not isinstance(duration_ms, bool)
                else None
            ),
        }
        if isinstance(score, int | float) and not isinstance(score, bool):
            entry["score"] = round(float(score), 2)
        if liveness is not None:
            entry["liveness"] = _text(liveness)
        if request_id is not None:
            entry["request_id"] = _text(request_id)
        if tool is not None:
            entry["tool"] = _text(tool)
        line = (json.dumps(entry, ensure_ascii=False) + "\n").encode("utf-8")
        with self._lock:
            try:
                self._append(line)
            except OSError as exc:
                logger.error("guard audit log %s could not be written: %s", self.path, exc)
        return entry

    def _append(self, line: bytes) -> None:
        secure_dir(self.directory)
        try:
            size = self.path.stat().st_size
        except FileNotFoundError:
            size = 0
        if size and size + len(line) > MAX_BYTES:
            self._rotate()
        fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.fchmod(fd, 0o600)
            os.write(fd, line)
        finally:
            os.close(fd)

    def _rotate(self) -> None:
        oldest = self.directory / f"{AUDIT_FILE}.{KEEP - 1}"
        with suppress(FileNotFoundError):
            oldest.unlink()
        for index in range(KEEP - 2, 0, -1):
            source = self.directory / f"{AUDIT_FILE}.{index}"
            if source.exists():
                os.replace(source, self.directory / f"{AUDIT_FILE}.{index + 1}")
        os.replace(self.path, self.directory / f"{AUDIT_FILE}.1")

    def read(self, *, since: datetime | None = None) -> list[dict[str, Any]]:
        """Every readable record, oldest first; ``since`` keeps those at or after it."""
        return list(self._iter(since))

    def _iter(self, since: datetime | None) -> Iterator[dict[str, Any]]:
        for path in self.files():
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            for line in lines:
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(entry, dict):
                    continue
                if since is not None:
                    try:
                        at = datetime.fromisoformat(str(entry.get("at")))
                    except ValueError:
                        continue
                    if at.tzinfo is None:
                        at = at.replace(tzinfo=UTC)
                    if at < since:
                        continue
                yield entry
