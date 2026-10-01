"""Simulated lamps: their names from ``[component.sim]``, their state in one private file.

- **Config.** ``[component.sim] lamps = ["desk", "living-room"]`` names the lamps (default
  ``["desk"]``; ``[]`` means none). A name is a slug: lowercase letters, digits and hyphens,
  1 to 40 characters, starting with a letter or digit. Unknown keys, a name that is not a slug
  and a repeated name are :class:`SimConfigError` (a :class:`tau_core.ConfigError`).
- **State.** ``TAU_DATA_DIR/sim/lamps.json`` holds ``{"version": 1, "lamps": {"desk": {"on":
  false, "updated": "<ISO 8601, UTC>"}}}``. Every write goes to a temporary file first and is
  moved into place, mode 0600 in a 0700 directory, so a reader never sees half a file.
- **Lock.** Writers take ``fcntl.flock`` on ``TAU_DATA_DIR/sim/lamps.lock``, so a tool call in
  ``tau tui`` and the hub's ``sim`` service never lose each other's change. The kernel drops
  the lock when its holder dies; the lock file is never deleted.
- **First use.** A configured lamp the file does not know yet is added as off, with ``updated``
  set to that moment, so its ``updated`` stays put until it really changes. A lamp that leaves
  the config keeps its entry in the file (it comes back as it was) but is no longer listed.
- **A broken file** (hand-edited, not JSON) is logged and read as empty: every lamp is off
  again. It is a simulation; nothing real depends on it.

Nothing here talks to hardware. Every :class:`~tau_core.DeviceState` it makes says
``simulated=True``.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import logging
import os
import re
import tempfile
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tau_core import Config, ConfigError, DeviceState

__all__ = [
    "COMPONENT",
    "DEFAULT_LAMPS",
    "KIND",
    "NAME_RE",
    "Lamp",
    "LampStore",
    "SimConfigError",
    "SimSettings",
    "UnknownLamp",
    "device_id",
    "normalize_name",
]

logger = logging.getLogger(__name__)

COMPONENT = "sim"
"""The ``[component.<name>]`` table and the hub service's name."""
DEFAULT_LAMPS = ("desk",)
KIND = "lamp"
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
SETTINGS_KEYS = frozenset({"enabled", "lamps"})
STATE_DIR = "sim"
STATE_FILE = "lamps.json"
LOCK_FILE = "lamps.lock"
STATE_VERSION = 1
FILE_MODE = 0o600
DIR_MODE = 0o700


class SimConfigError(ConfigError):
    """``[component.sim]`` is not valid; the message is meant for the owner."""


class UnknownLamp(KeyError):
    """No configured lamp has this name."""

    def __init__(self, name: str, known: Iterable[str]):
        self.name = name
        self.known = tuple(known)
        super().__init__(name)


def utc_now() -> datetime:
    return datetime.now(UTC)


def device_id(name: str) -> str:
    """The device id of the lamp ``name``: ``sim:lamp:<name>``."""
    return f"{COMPONENT}:{KIND}:{name}"


def normalize_name(text: str) -> str:
    """What the owner or the model may call a lamp, as its slug: ``"Living room lamp"`` →
    ``"living-room"``. It does not check that the lamp exists."""
    words = re.split(r"[\s_-]+", text.strip().lower())
    words = [word for word in words if word]
    if len(words) > 1 and words[-1] == KIND:
        words = words[:-1]
    return "-".join(words)


@dataclass(frozen=True)
class SimSettings:
    """``[component.sim]``: the lamps' names, in the order they are listed."""

    lamps: tuple[str, ...] = DEFAULT_LAMPS

    @classmethod
    def from_mapping(cls, table: Mapping[str, Any]) -> SimSettings:
        unknown = sorted(set(table) - SETTINGS_KEYS)
        if unknown:
            raise SimConfigError(
                f"tau.toml: [component.sim] has unknown keys: {', '.join(unknown)}."
            )
        raw = table.get("lamps", list(DEFAULT_LAMPS))
        if not isinstance(raw, list) or not all(isinstance(name, str) for name in raw):
            raise SimConfigError("tau.toml: [component.sim] 'lamps' must be a list of names.")
        seen: set[str] = set()
        for name in raw:
            if not NAME_RE.match(name):
                raise SimConfigError(
                    f"tau.toml: [component.sim] lamp name {name!r} is not valid: use lowercase "
                    "letters, digits and hyphens, at most 40 characters."
                )
            if name in seen:
                raise SimConfigError(f"tau.toml: [component.sim] lists the lamp {name!r} twice.")
            seen.add(name)
        return cls(lamps=tuple(raw))

    @classmethod
    def from_config(cls, config: Config) -> SimSettings:
        return cls.from_mapping(config.component(COMPONENT))


@dataclass(frozen=True)
class Lamp:
    """One simulated lamp: on or off, and when that last changed (UTC)."""

    name: str
    on: bool
    updated: datetime

    def device(self) -> DeviceState:
        return DeviceState(
            id=device_id(self.name),
            name=self.name,
            kind=KIND,
            simulated=True,
            state={"on": self.on},
            updated=self.updated,
        )


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.utcoffset() is not None else None


def _entry(lamp: Lamp) -> dict[str, Any]:
    return {"on": lamp.on, "updated": lamp.updated.isoformat()}


def _write_private(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` atomically with mode 0600 (temporary file, fsync, rename)."""
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, FILE_MODE)
        os.replace(tmp, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            tmp.unlink()


class LampStore:
    """The lamps of one data dir. Cheap to build; every call reads the file again."""

    def __init__(
        self,
        directory: Path,
        lamps: Iterable[str] = DEFAULT_LAMPS,
        *,
        clock: Callable[[], datetime] = utc_now,
    ):
        self.directory = Path(directory)
        self.path = self.directory / STATE_FILE
        self.lock_path = self.directory / LOCK_FILE
        self.names: tuple[str, ...] = tuple(lamps)
        self._clock = clock

    @classmethod
    def from_config(cls, config: Config, **kwargs: Any) -> LampStore:
        """The store under ``config.data_dir``, with the lamps of ``[component.sim]``."""
        settings = SimSettings.from_config(config)
        return cls(config.data_dir / STATE_DIR, settings.lamps, **kwargs)

    # -- reading -----------------------------------------------------------------------------

    def resolve(self, name: str) -> str:
        """The configured lamp ``name`` means (see :func:`normalize_name`), or
        :class:`UnknownLamp`."""
        slug = normalize_name(name)
        if slug in self.names:
            return slug
        raise UnknownLamp(name, self.names)

    def lamps(self) -> list[Lamp]:
        """Every configured lamp, in config order; adds the ones the file does not know yet."""
        with self._locked():
            entries = self._load()
            if self._fill(entries):
                self._save(entries)
        return [self._lamp(name, entries[name]) for name in self.names]

    def peek(self) -> list[Lamp]:
        """The configured lamps the file knows (with a valid entry), without the lock and
        without writing: the ``sim`` service's watcher. A rename never shows half a file."""
        entries = self._load()
        return [
            self._lamp(name, entries[name]) for name in self.names if self._valid(entries.get(name))
        ]

    def signature(self) -> tuple[int, int, int] | None:
        """``(inode, mtime_ns, size)`` of the state file, ``None`` while it does not exist.
        Every write is a rename, so the inode alone already changes on each one."""
        try:
            stat = os.stat(self.path)
        except FileNotFoundError:
            return None
        return (stat.st_ino, stat.st_mtime_ns, stat.st_size)

    # -- writing -----------------------------------------------------------------------------

    def set(self, name: str, on: bool) -> tuple[Lamp, bool]:
        """Switch the lamp ``name`` (a configured name, see :meth:`resolve`); returns the lamp
        and whether it changed. Switching a lamp to the state it has writes nothing."""
        slug = self.resolve(name)
        with self._locked():
            entries = self._load()
            dirty = self._fill(entries)
            current = self._lamp(slug, entries[slug])
            changed = current.on is not bool(on)
            if changed:
                current = Lamp(slug, bool(on), self._clock())
                entries[slug] = _entry(current)
                dirty = True
            if dirty:
                self._save(entries)
        return current, changed

    # -- internals ---------------------------------------------------------------------------

    def _ensure_dir(self) -> None:
        self.directory.mkdir(mode=DIR_MODE, parents=True, exist_ok=True)
        os.chmod(self.directory, DIR_MODE)

    @contextlib.contextmanager
    def _locked(self) -> Iterator[None]:
        self._ensure_dir()
        fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, FILE_MODE)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            os.close(fd)  # closing the descriptor releases the lock

    def _load(self) -> dict[str, Any]:
        try:
            text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return {}
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            logger.warning("sim: %s is not valid JSON (%s); reading it as empty", self.path, exc)
            return {}
        lamps = data.get("lamps") if isinstance(data, dict) else None
        if not isinstance(lamps, dict):
            logger.warning("sim: %s has no 'lamps' table; reading it as empty", self.path)
            return {}
        return dict(lamps)

    def _valid(self, entry: Any) -> bool:
        return (
            isinstance(entry, dict)
            and isinstance(entry.get("on"), bool)
            and _parse_time(entry.get("updated")) is not None
        )

    def _fill(self, entries: dict[str, Any]) -> bool:
        """Add (or repair) the configured lamps; ``True`` when ``entries`` changed."""
        changed = False
        for name in self.names:
            if not self._valid(entries.get(name)):
                entries[name] = _entry(Lamp(name, False, self._clock()))
                changed = True
        return changed

    def _lamp(self, name: str, entry: dict[str, Any]) -> Lamp:
        """The lamp of a valid entry (see :meth:`_valid`)."""
        updated = _parse_time(entry["updated"])
        assert updated is not None
        return Lamp(name, entry["on"], updated)

    def _save(self, entries: dict[str, Any]) -> None:
        payload = {"version": STATE_VERSION, "lamps": dict(sorted(entries.items()))}
        _write_private(self.path, json.dumps(payload, indent=2, sort_keys=True) + "\n")
