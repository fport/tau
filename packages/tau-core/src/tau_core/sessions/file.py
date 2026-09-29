"""File session store: one directory per session under ``Config.sessions_dir``.

Layout::

    <sessions_dir>/<session_id>/
        session.json                          Strands Session; updated_at is refreshed on writes
        meta.json                             tau metadata: channel, profile, title, ...
        events.jsonl                          agent events, one JSON object per line, append-only
        agents/<agent_id>/agent.json          Strands SessionAgent
        agents/<agent_id>/messages/000000.json   Strands SessionMessage (zero-padded message id)

JSON files are written atomically (temp file in the same directory, fsync, ``os.replace``), so
a crash leaves the old or the new version, never half of one. Events are appended with
``O_APPEND``; a line cut short by a crash is skipped on read and never glued to the next one.
Directories are 0700 and files 0600 because sessions hold private conversations, and reading
or writing through a symlink below the root is refused.

Nothing is ever deleted: the store has no delete method, creating a message refuses to
overwrite an existing one, and retention is "keep everything" (ADR 0003).
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from strands.types.exceptions import SessionException
from strands.types.session import Session, SessionAgent, SessionMessage, SessionType

from tau_core.config import ConfigError
from tau_core.events import AgentEvent
from tau_core.sessions.base import SessionStore, SessionSummary, utc_now_iso

logger = logging.getLogger(__name__)

SESSION_FILE = "session.json"
META_FILE = "meta.json"
EVENTS_FILE = "events.jsonl"
AGENTS_DIR = "agents"
AGENT_FILE = "agent.json"
MESSAGES_DIR = "messages"

_DIR_MODE = 0o700
_FILE_MODE = 0o600
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_ID_PATTERN = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_MESSAGE_FILE = re.compile(r"\A(\d+)\.json\Z")
_OLDEST = datetime.min.replace(tzinfo=UTC)


class InvalidSessionId(ConfigError, ValueError):
    """An id that cannot be a directory name; the message is meant for the user.

    A ``ConfigError`` so ``tau chat --session <bad id>`` fails with the message instead of a
    traceback; a ``ValueError`` like Strands' own id validation.
    """


def validate_id(value: str, *, what: str = "session") -> str:
    """Return ``value`` if it is a safe directory name (letters, digits, ``.``, ``_``, ``-``)."""
    if not isinstance(value, str) or not _ID_PATTERN.match(value):
        raise InvalidSessionId(
            f"Invalid {what} id: '{value}'. Only letters, digits, '.', '_' and '-' are allowed."
        )
    return value


def _sort_key(summary: SessionSummary) -> tuple[datetime, str]:
    try:
        at = datetime.fromisoformat(summary.updated_at)
    except ValueError:
        at = _OLDEST
    if at.tzinfo is None:
        at = at.replace(tzinfo=UTC)
    return at, summary.session_id


class FileSessionStore(SessionStore):
    """Sessions as local files under ``root`` (normally ``Config.sessions_dir``)."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root).expanduser()
        self._lock = threading.RLock()

    # -- paths -------------------------------------------------------------------------------

    def _session_dir(self, session_id: str) -> Path:
        path = self.root / validate_id(session_id)
        if path.is_symlink():
            raise SessionException(f"Refusing to use symlink at {path}")
        return path

    def _agent_dir(self, session_id: str, agent_id: str) -> Path:
        path = self._session_dir(session_id) / AGENTS_DIR / validate_id(agent_id, what="agent")
        if path.is_symlink():
            raise SessionException(f"Refusing to use symlink at {path}")
        return path

    def _message_path(self, session_id: str, agent_id: str, message_id: int) -> Path:
        if isinstance(message_id, bool) or not isinstance(message_id, int) or message_id < 0:
            raise ValueError(f"message_id=<{message_id}> | must be a non-negative integer")
        return self._agent_dir(session_id, agent_id) / MESSAGES_DIR / f"{message_id:06d}.json"

    # -- file primitives ---------------------------------------------------------------------

    def _make_dirs(self, path: Path) -> None:
        """Create ``path`` (inside the root) and its missing parents, each with mode 0700."""
        self.root.mkdir(mode=_DIR_MODE, parents=True, exist_ok=True)
        current = self.root
        for part in path.relative_to(self.root).parts:
            current = current / part
            if current.is_symlink():
                raise SessionException(f"Refusing to use symlink at {current}")
            current.mkdir(mode=_DIR_MODE, exist_ok=True)

    def _read_json(self, path: Path) -> dict[str, Any] | None:
        if path.is_symlink():
            raise SessionException(f"Refusing to read symlink at {path}")
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise SessionException(f"Invalid JSON in {path}: {exc}") from exc
        if not isinstance(data, dict):
            raise SessionException(f"Expected a JSON object in {path}")
        return data

    def _write_json(self, path: Path, data: dict[str, Any]) -> None:
        """Atomic replace: temp file in the same directory, fsync, ``os.replace``."""
        self._make_dirs(path.parent)
        if path.is_symlink():
            raise SessionException(f"Refusing to write to symlink at {path}")
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".json")  # 0600
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
                json.dump(data, f, ensure_ascii=False, indent=2, default=str)
                f.write("\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)  # only our own unfinished temp file, never a record
            except OSError:
                pass
            raise

    def _append_line(self, path: Path, line: str) -> None:
        self._make_dirs(path.parent)
        if path.is_symlink():
            raise SessionException(f"Refusing to write to symlink at {path}")
        data = line.encode("utf-8")
        fd = os.open(path, os.O_RDWR | os.O_APPEND | os.O_CREAT | _NOFOLLOW, _FILE_MODE)
        try:
            size = os.fstat(fd).st_size
            if size and os.pread(fd, 1, size - 1) != b"\n":
                data = b"\n" + data  # a crash cut the last line short: keep it, start a new one
            view = memoryview(data)
            while view:
                view = view[os.write(fd, view) :]
            os.fsync(fd)
        finally:
            os.close(fd)

    def _session_data(self, session_id: str) -> dict[str, Any] | None:
        return self._read_json(self._session_dir(session_id) / SESSION_FILE)

    def _require_session(self, session_id: str) -> dict[str, Any]:
        data = self._session_data(session_id)
        if data is None:
            raise SessionException(f"Session {session_id} does not exist")
        return data

    def _require_agent(self, session_id: str, agent_id: str) -> dict[str, Any]:
        self._require_session(session_id)
        data = self._read_json(self._agent_dir(session_id, agent_id) / AGENT_FILE)
        if data is None:
            raise SessionException(f"Agent {agent_id} does not exist in session {session_id}")
        return data

    def _touch(self, session_id: str) -> None:
        """Refresh ``updated_at`` in ``session.json`` (the listing order)."""
        data = self._session_data(session_id)
        if data is not None:
            data["updated_at"] = utc_now_iso()
            self._write_json(self._session_dir(session_id) / SESSION_FILE, data)

    def _ensure_session(self, session_id: str) -> None:
        if self._session_data(session_id) is None:
            self.create_session(Session(session_id=session_id, session_type=SessionType.AGENT))

    def _message_ids(self, messages_dir: Path) -> list[int]:
        if messages_dir.is_symlink() or not messages_dir.is_dir():
            return []
        ids = []
        for entry in os.scandir(messages_dir):
            match = _MESSAGE_FILE.match(entry.name)
            if match and entry.is_file(follow_symlinks=False):
                ids.append(int(match.group(1)))
        return sorted(ids)

    # -- SessionRepository -------------------------------------------------------------------

    def create_session(self, session: Session, **kwargs: Any) -> Session:
        with self._lock:
            session_dir = self._session_dir(session.session_id)
            if self._read_json(session_dir / SESSION_FILE) is not None:
                raise SessionException(f"Session {session.session_id} already exists")
            data = session.to_dict()
            data["session_type"] = SessionType(data.get("session_type", SessionType.AGENT)).value
            data["updated_at"] = data.get("updated_at") or utc_now_iso()
            self._make_dirs(session_dir / AGENTS_DIR)
            self._write_json(session_dir / SESSION_FILE, data)
            return session

    def read_session(self, session_id: str, **kwargs: Any) -> Session | None:
        with self._lock:
            data = self._session_data(session_id)
            return Session.from_dict(data) if data is not None else None

    def create_agent(self, session_id: str, session_agent: SessionAgent, **kwargs: Any) -> None:
        with self._lock:
            self._require_session(session_id)
            agent_dir = self._agent_dir(session_id, session_agent.agent_id)
            self._make_dirs(agent_dir / MESSAGES_DIR)
            self._write_json(agent_dir / AGENT_FILE, session_agent.to_dict())
            self._touch(session_id)

    def read_agent(self, session_id: str, agent_id: str, **kwargs: Any) -> SessionAgent | None:
        with self._lock:
            path = self._agent_dir(session_id, agent_id) / AGENT_FILE  # validates both ids
            if self._session_data(session_id) is None:
                return None
            data = self._read_json(path)
            return SessionAgent.from_dict(data) if data is not None else None

    def update_agent(self, session_id: str, session_agent: SessionAgent, **kwargs: Any) -> None:
        with self._lock:
            previous = self._require_agent(session_id, session_agent.agent_id)
            data = session_agent.to_dict()
            data["created_at"] = previous.get("created_at", data.get("created_at"))
            data["updated_at"] = utc_now_iso()
            agent_dir = self._agent_dir(session_id, session_agent.agent_id)
            self._write_json(agent_dir / AGENT_FILE, data)
            self._touch(session_id)

    def create_message(
        self, session_id: str, agent_id: str, session_message: SessionMessage, **kwargs: Any
    ) -> None:
        with self._lock:
            self._require_agent(session_id, agent_id)
            path = self._message_path(session_id, agent_id, session_message.message_id)
            if path.exists() or path.is_symlink():
                # Two writers on one session; overwriting would lose a message.
                raise SessionException(
                    f"Message {session_message.message_id} already exists in session {session_id}"
                )
            self._write_json(path, session_message.to_dict())
            self._touch(session_id)

    def read_message(
        self, session_id: str, agent_id: str, message_id: int, **kwargs: Any
    ) -> SessionMessage | None:
        with self._lock:
            path = self._message_path(session_id, agent_id, message_id)  # validates the ids
            if self._session_data(session_id) is None:
                return None
            data = self._read_json(path)
            return SessionMessage.from_dict(data) if data is not None else None

    def update_message(
        self, session_id: str, agent_id: str, session_message: SessionMessage, **kwargs: Any
    ) -> None:
        """Strands calls this to redact a message; the original stays in ``message``."""
        with self._lock:
            self._require_agent(session_id, agent_id)
            path = self._message_path(session_id, agent_id, session_message.message_id)
            previous = self._read_json(path)
            if previous is None:
                raise SessionException(f"Message {session_message.message_id} does not exist")
            data = session_message.to_dict()
            data["created_at"] = previous.get("created_at", data.get("created_at"))
            data["updated_at"] = utc_now_iso()
            self._write_json(path, data)
            self._touch(session_id)

    def list_messages(
        self,
        session_id: str,
        agent_id: str,
        limit: int | None = None,
        offset: int = 0,
        **kwargs: Any,
    ) -> list[SessionMessage]:
        with self._lock:
            self._require_agent(session_id, agent_id)
            messages_dir = self._agent_dir(session_id, agent_id) / MESSAGES_DIR
            ids = self._message_ids(messages_dir)[offset:]
            if limit is not None:
                ids = ids[:limit]
            messages = []
            for message_id in ids:
                data = self._read_json(self._message_path(session_id, agent_id, message_id))
                if data is not None:
                    messages.append(SessionMessage.from_dict(data))
            return messages

    # -- tau extras --------------------------------------------------------------------------

    def _summary(self, session_id: str) -> SessionSummary | None:
        session = self._session_data(session_id)
        if session is None:
            return None
        meta = self.read_meta(session_id)
        agents_dir = self._session_dir(session_id) / AGENTS_DIR
        message_count = 0
        if agents_dir.is_dir() and not agents_dir.is_symlink():
            for entry in os.scandir(agents_dir):
                if entry.is_dir(follow_symlinks=False):
                    message_count += len(self._message_ids(Path(entry.path) / MESSAGES_DIR))
        return SessionSummary(
            session_id=session_id,
            created_at=str(session.get("created_at", "")),
            updated_at=str(session.get("updated_at") or session.get("created_at", "")),
            channel=str(meta.get("channel", "")),
            profile=str(meta.get("profile", "")),
            title=str(meta.get("title", "")),
            message_count=message_count,
        )

    def list_sessions(self, limit: int = 20) -> list[SessionSummary]:
        """Most recently updated first. Unreadable session directories are logged and skipped."""
        with self._lock:
            if not self.root.is_dir():
                return []
            summaries = []
            for entry in os.scandir(self.root):
                if not entry.is_dir(follow_symlinks=False) or not _ID_PATTERN.match(entry.name):
                    continue
                try:
                    summary = self._summary(entry.name)
                except (SessionException, OSError) as exc:
                    logger.warning("skipping unreadable session %s: %s", entry.name, exc)
                    continue
                if summary is not None:
                    summaries.append(summary)
        summaries.sort(key=_sort_key, reverse=True)
        return summaries[:limit]

    def append_event(self, session_id: str, event: AgentEvent) -> None:
        line = json.dumps(event.to_dict(), ensure_ascii=False, default=str) + "\n"
        with self._lock:
            self._ensure_session(session_id)
            self._append_line(self._session_dir(session_id) / EVENTS_FILE, line)
            self._touch(session_id)

    def read_events(self, session_id: str) -> list[AgentEvent]:
        with self._lock:
            path = self._session_dir(session_id) / EVENTS_FILE
            if path.is_symlink():
                raise SessionException(f"Refusing to read symlink at {path}")
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except FileNotFoundError:
                return []
        events = []
        for number, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                data = json.loads(line)
                if not isinstance(data, dict):
                    raise ValueError("not a JSON object")
                events.append(AgentEvent.from_dict(data))
            except (ValueError, TypeError) as exc:  # JSONDecodeError is a ValueError
                logger.warning("skipping unreadable event line %d in %s: %s", number, path, exc)
        return events

    def write_meta(self, session_id: str, **meta: Any) -> None:
        with self._lock:
            self._ensure_session(session_id)
            path = self._session_dir(session_id) / META_FILE
            current = self._read_json(path) or {}
            current.update(meta)
            self._write_json(path, current)
            self._touch(session_id)

    def read_meta(self, session_id: str) -> dict[str, Any]:
        with self._lock:
            return self._read_json(self._session_dir(session_id) / META_FILE) or {}
