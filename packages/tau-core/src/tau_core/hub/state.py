"""The hub's files under ``<data_dir>/hub``: heartbeat state, crash marker and crash reports.

``state.json`` is rewritten on start, on every heartbeat and on a clean stop (which sets
``stopped_at``). A ``state.json`` without ``stopped_at`` found by the next start therefore means
the previous hub died without a clean shutdown; that start turns it into a :class:`CrashReport`,
appends it to ``crash_reports.jsonl`` and keeps the latest one in ``last_crash.json``.
``crash.json`` is the marker a failing hub writes on its way down so the next start knows the
reason; a ``kill -9`` leaves none, and the reason becomes :data:`UNCLEAN_EXIT`.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from contextlib import suppress
from dataclasses import asdict, dataclass, fields
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

LOCK_FILE = "hub.lock"
STATE_FILE = "state.json"
CRASH_FILE = "crash.json"
CRASH_REPORTS_FILE = "crash_reports.jsonl"
LAST_CRASH_FILE = "last_crash.json"
LOGS_DIR = "logs"

UNCLEAN_EXIT = "unexpected exit (no clean shutdown)"


def utc_now() -> datetime:
    return datetime.now(UTC)


def timestamp(moment: datetime) -> str:
    """ISO 8601 in UTC with seconds, e.g. ``2026-09-29T12:30:12+00:00``."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC).isoformat(timespec="seconds")


def parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


@dataclass
class HubState:
    """What ``state.json`` holds while the hub runs and after it stopped."""

    pid: int
    started_at: str
    heartbeat_at: str
    version: str
    role: str
    profile: str
    last_crash: dict[str, Any] | None
    stopped_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HubState:
        """Build from a dict; unknown keys are ignored, missing required keys raise."""
        known = {f.name for f in fields(cls)}
        state = cls(**{k: v for k, v in data.items() if k in known})
        if not isinstance(state.pid, int):
            raise ValueError("pid must be an integer")
        return state


@dataclass(frozen=True)
class CrashReport:
    """Why and when the previous hub died, as noticed by the next start."""

    pid: int
    started_at: str
    last_heartbeat_at: str
    reason: str
    detected_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CrashReport:
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


def write_text_atomic(path: Path, text: str, *, mode: int = 0o600) -> None:
    """Write ``text`` to ``path`` through a temporary file in the same directory + rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        with suppress(OSError):
            os.unlink(tmp)
        raise


def _dump(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


class HubFiles:
    """Paths and reads/writes for everything the hub keeps in ``hub_dir``."""

    def __init__(self, hub_dir: Path):
        self.dir = Path(hub_dir)

    @property
    def lock(self) -> Path:
        return self.dir / LOCK_FILE

    @property
    def state(self) -> Path:
        return self.dir / STATE_FILE

    @property
    def crash(self) -> Path:
        return self.dir / CRASH_FILE

    @property
    def crash_reports(self) -> Path:
        return self.dir / CRASH_REPORTS_FILE

    @property
    def last_crash(self) -> Path:
        return self.dir / LAST_CRASH_FILE

    @property
    def logs(self) -> Path:
        return self.dir / LOGS_DIR

    def _read_json(self, path: Path) -> Any:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as exc:
            logger.warning("unreadable hub file %s: %s", path, exc)
            return None

    def read_state(self) -> HubState | None:
        """The last written state, or ``None`` when missing or unreadable."""
        data = self._read_json(self.state)
        if not isinstance(data, dict):
            return None
        try:
            return HubState.from_dict(data)
        except (TypeError, ValueError) as exc:
            logger.warning("invalid hub state %s: %s", self.state, exc)
            return None

    def write_state(self, state: HubState) -> None:
        write_text_atomic(self.state, _dump(state.to_dict()))

    def write_crash_marker(self, *, pid: int, reason: str, at: str, traceback: str | None) -> None:
        """Called by a failing hub on its way down; read by the next start."""
        marker = {"pid": pid, "reason": reason, "at": at, "traceback": traceback}
        write_text_atomic(self.crash, _dump(marker))

    def secure_logs(self) -> None:
        """Keep ``logs/`` private: the directory 0700 and every file in it 0600.

        launchd creates the log files with the default umask (0644) before the hub starts, and
        ``mkdir(mode=)`` does not change an existing directory, so the hub chmods them at every
        start. Missing paths and chmod errors are ignored."""
        logs = self.logs
        if not logs.is_dir() or logs.is_symlink():
            return
        with suppress(OSError):
            os.chmod(logs, 0o700)
        with suppress(OSError):
            for path in logs.iterdir():
                if path.is_file() and not path.is_symlink():
                    with suppress(OSError):
                        os.chmod(path, 0o600)

    def read_last_crash(self) -> dict[str, Any] | None:
        data = self._read_json(self.last_crash)
        return data if isinstance(data, dict) else None

    def read_crash_reports(self) -> list[CrashReport]:
        """Every recorded crash, oldest first; unreadable lines are skipped."""
        try:
            lines = self.crash_reports.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            return []
        reports = []
        for line in lines:
            try:
                reports.append(CrashReport.from_dict(json.loads(line)))
            except (TypeError, ValueError):
                continue
        return reports

    def check_previous_run(self, *, now: datetime) -> CrashReport | None:
        """Turn a stale ``state.json`` (no ``stopped_at``) into a recorded crash report.

        Call it while holding the hub lock and before the new state is written. The crash
        marker is consumed either way, so an old reason never sticks to a later crash.
        """
        state = self.read_state()
        marker = self._read_json(self.crash)
        with suppress(FileNotFoundError):
            self.crash.unlink()
        if state is None or state.stopped_at:
            return None
        reason = UNCLEAN_EXIT
        if isinstance(marker, dict) and marker.get("pid") == state.pid and marker.get("reason"):
            reason = str(marker["reason"])
        report = CrashReport(
            pid=state.pid,
            started_at=state.started_at,
            last_heartbeat_at=state.heartbeat_at,
            reason=reason,
            detected_at=timestamp(now),
        )
        self.dir.mkdir(parents=True, exist_ok=True)
        # Append with an explicit 0600 mode so the file matches the other hub files
        # instead of inheriting the umask.
        fd = os.open(self.crash_reports, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(report.to_dict(), ensure_ascii=False) + "\n")
        write_text_atomic(self.last_crash, _dump(report.to_dict()))
        return report
