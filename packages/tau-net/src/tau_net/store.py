"""The network's state: contacts, sessions, seen ids, the network log and the poll cursor.

:class:`NetStore` keeps five documents (§6.7) behind a small backend:

- :class:`FileBackend` (``[component.net] store = "file"``, the default) writes them under
  ``TAU_DATA_DIR/net/``: ``contacts.json``, ``sessions.json``, ``seen.json``, ``log.jsonl`` and
  ``cursor``, atomically, files 0600 in a 0700 directory.
- :class:`SpineBackend` (``store = "spine"``, cloud mode) keeps them in the spine's state API
  under ``net.contacts``, ``net.sessions``, ``net.seen``, ``net.log`` and ``net.cursor``.

Documents are read again on every access (nothing is cached), so ``tau net accept`` in a
terminal and the running hub see each other's writes; read-modify-write steps hold a
process-wide lock. The log keeps the last 500 entries, the seen list the last 1 000 ids.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import Any, Protocol, TypeVar

from tau_net.spine import SpineClient

__all__ = [
    "DOCUMENTS",
    "LOG_LIMIT",
    "SEEN_LIMIT",
    "STORE_KINDS",
    "DocumentBackend",
    "FileBackend",
    "NetStore",
    "SpineBackend",
]

logger = logging.getLogger(__name__)

DOCUMENTS = ("contacts", "sessions", "seen", "log", "cursor")
STORE_KINDS = ("file", "spine")
LOG_LIMIT = 500
SEEN_LIMIT = 1000
SPINE_LOG_BYTES = 900_000
"""A state value may not exceed 1 MiB; the spine-backed log drops its oldest entries first."""
LOG_DEDUP_WINDOW = 50

T = TypeVar("T")


class DocumentBackend(Protocol):
    """Where the documents live. ``read`` returns ``None`` for a document that is missing."""

    kind: str

    def read(self, name: str) -> Any: ...

    def write(self, name: str, value: Any) -> None: ...

    def describe(self) -> str: ...


# -- files -------------------------------------------------------------------------------------


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        with suppress(OSError):
            os.unlink(tmp)
        raise


class FileBackend:
    """The documents as files under ``root`` (``TAU_DATA_DIR/net``)."""

    kind = "file"
    FILES = {
        "contacts": "contacts.json",
        "sessions": "sessions.json",
        "seen": "seen.json",
        "log": "log.jsonl",
        "cursor": "cursor",
    }

    def __init__(self, root: Path):
        self.root = Path(root)

    def path(self, name: str) -> Path:
        return self.root / self.FILES[name]

    def describe(self) -> str:
        return f"file ({self.root})"

    def read(self, name: str) -> Any:
        path = self.path(name)
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except OSError as exc:
            logger.warning("net: cannot read %s: %s", path, exc)
            return None
        if name == "cursor":
            try:
                return int(text.strip() or "0")
            except ValueError:
                logger.warning("net: ignoring unreadable %s", path)
                return None
        if name == "log":
            entries = []
            for line in text.splitlines():
                with suppress(ValueError):
                    entry = json.loads(line)
                    if isinstance(entry, dict):
                        entries.append(entry)
            return entries
        try:
            return json.loads(text)
        except ValueError:
            logger.warning("net: ignoring unreadable %s", path)
            return None

    def write(self, name: str, value: Any) -> None:
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        with suppress(OSError):
            os.chmod(self.root, 0o700)
        if name == "cursor":
            text = f"{int(value)}\n"
        elif name == "log":
            text = "".join(json.dumps(entry, ensure_ascii=False) + "\n" for entry in value)
        else:
            text = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        _write_atomic(self.path(name), text)


# -- the spine's state API ---------------------------------------------------------------------


class SpineBackend:
    """The documents as ``net.<name>`` keys of the spine's state API (cloud mode only)."""

    kind = "spine"

    def __init__(self, spine: SpineClient):
        self.spine = spine

    def describe(self) -> str:
        return f"spine ({self.spine.host})"

    def read(self, name: str) -> Any:
        return self.spine.state_get(f"net.{name}")

    def write(self, name: str, value: Any) -> None:
        if name == "log":
            value = list(value)
            while value and len(json.dumps(value, ensure_ascii=False).encode()) > SPINE_LOG_BYTES:
                value = value[max(1, len(value) // 10) :]
        self.spine.state_put(f"net.{name}", value)


# -- the store ---------------------------------------------------------------------------------


class NetStore:
    """Typed access to the five documents. Thread-safe within one process."""

    def __init__(self, backend: DocumentBackend):
        self.backend = backend
        self.lock = threading.RLock()

    @property
    def kind(self) -> str:
        return self.backend.kind

    def describe(self) -> str:
        return self.backend.describe()

    def _dict(self, name: str) -> dict[str, Any]:
        value = self.backend.read(name)
        return dict(value) if isinstance(value, dict) else {}

    def _list(self, name: str) -> list[Any]:
        value = self.backend.read(name)
        return list(value) if isinstance(value, list) else []

    # -- contacts ------------------------------------------------------------------------------

    def contacts(self) -> dict[str, dict[str, Any]]:
        """``address → contact record`` (plain dicts; :mod:`tau_net.contacts` types them)."""
        return {k: v for k, v in self._dict("contacts").items() if isinstance(v, dict)}

    def update_contacts(self, change: Callable[[dict[str, dict[str, Any]]], T]) -> T:
        """Read, let ``change`` edit the mapping in place, write it back; returns its result."""
        with self.lock:
            contacts = self.contacts()
            result = change(contacts)
            self.backend.write("contacts", contacts)
            return result

    # -- sessions ------------------------------------------------------------------------------

    def sessions(self) -> dict[str, str]:
        """``address → session id`` of each contact's network-turn session."""
        return {k: v for k, v in self._dict("sessions").items() if isinstance(v, str) and v}

    def set_session(self, address: str, session_id: str) -> None:
        with self.lock:
            sessions = self.sessions()
            if sessions.get(address) == session_id:
                return
            sessions[address] = session_id
            self.backend.write("sessions", sessions)

    # -- seen ids ------------------------------------------------------------------------------

    @staticmethod
    def seen_key(sender: str, envelope_id: str) -> str:
        return f"{sender} {envelope_id}"

    def seen(self) -> list[str]:
        return [item for item in self._list("seen") if isinstance(item, str)]

    def is_seen(self, sender: str, envelope_id: str) -> bool:
        return self.seen_key(sender, envelope_id) in self.seen()

    def mark_seen(self, sender: str, envelope_id: str) -> None:
        key = self.seen_key(sender, envelope_id)
        with self.lock:
            seen = self.seen()
            if key in seen:
                return
            seen.append(key)
            self.backend.write("seen", seen[-SEEN_LIMIT:])

    # -- the network log -----------------------------------------------------------------------

    def log(self, *, address: str | None = None, limit: int | None = None) -> list[dict[str, Any]]:
        """Log entries, oldest first; only ``address`` when given; the last ``limit``."""
        entries = [e for e in self._list("log") if isinstance(e, dict)]
        if address is not None:
            entries = [e for e in entries if e.get("address") == address]
        if limit is not None:
            entries = entries[-limit:] if limit > 0 else []
        return entries

    def append_log(self, entry: dict[str, Any]) -> bool:
        """Append one entry (``{ts, direction, address, kind, id, thread, text}``), keeping
        the last 500. An entry already among the recent ones (same direction, address and id,
        e.g. an envelope handled again after a crash) is not added twice."""
        with self.lock:
            entries = self.log()
            identity = (entry.get("direction"), entry.get("address"), entry.get("id"))
            for recent in entries[-LOG_DEDUP_WINDOW:]:
                if (recent.get("direction"), recent.get("address"), recent.get("id")) == identity:
                    return False
            entries.append(dict(entry))
            self.backend.write("log", entries[-LOG_LIMIT:])
            return True

    # -- the poll cursor -----------------------------------------------------------------------

    def cursor(self) -> int:
        value = self.backend.read("cursor")
        return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0

    def save_cursor(self, seq: int) -> None:
        with self.lock:
            self.backend.write("cursor", int(seq))
