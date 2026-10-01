"""Paired devices: the browsers allowed to use the hub's web app (ADR 0015 §2).

``tau web device add <name>`` (another process than the hub) writes a pending pairing: the
SHA-256 of a one-time code, the name and an expiry 10 minutes out. The owner opens
``/pair#<code>``; the page posts the code, the hub turns the pairing into a device with a fresh
key, keeps only the key's hash and sets the key as a cookie. Both files live in
``TAU_DATA_DIR/web/`` with mode 0600 and are written atomically under a file lock, so the CLI
and the hub never lose each other's writes.

A device id is the web channel's ``client_id`` (the guard's per-client grants, 117, key on it).
Keys and codes are 32 random bytes; nothing secret is ever stored or logged in the clear.
"""

from __future__ import annotations

import fcntl
import hashlib
import hmac
import json
import os
import re
import secrets
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

PAIRING_MINUTES = 10
NAME_RE = re.compile(r"\A[\w .'-]{1,40}\Z")

_DIR_MODE = 0o700
_FILE_MODE = 0o600


class DeviceError(ValueError):
    """A device command cannot be done; the message is for the owner (English)."""


def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class Device:
    id: str
    name: str
    key_hash: str
    created: str
    last_seen: str | None = None

    def public(self) -> dict[str, Any]:
        """What may leave the hub: everything but the key's hash."""
        return {
            "id": self.id,
            "name": self.name,
            "created": self.created,
            "last_seen": self.last_seen,
        }


class DeviceRegistry:
    """``devices.json`` and ``pairing.json`` under ``root`` (``TAU_DATA_DIR/web``)."""

    def __init__(self, root: Path, *, clock: Callable[[], datetime] = _now) -> None:
        self.root = Path(root)
        self.devices_path = self.root / "devices.json"
        self.pairing_path = self.root / "pairing.json"
        self._lock_path = self.root / ".lock"
        self._clock = clock

    # -- files -----------------------------------------------------------------------------

    @contextmanager
    def _locked(self) -> Iterator[None]:
        self.root.mkdir(mode=_DIR_MODE, parents=True, exist_ok=True)
        fd = os.open(self._lock_path, os.O_RDWR | os.O_CREAT, _FILE_MODE)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def _read(self, path: Path, key: str) -> list[dict[str, Any]]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        except (OSError, ValueError) as exc:
            raise DeviceError(f"{path} is unreadable: {exc}") from exc
        items = data.get(key) if isinstance(data, dict) else None
        return [item for item in items or [] if isinstance(item, dict)]

    def _write(self, path: Path, key: str, items: list[dict[str, Any]]) -> None:
        fd, tmp = tempfile.mkstemp(dir=self.root, prefix=".tmp-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({key: items}, f, indent=2)
                f.write("\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        except BaseException:
            with_suppressed_unlink(tmp)
            raise

    def _devices(self) -> list[Device]:
        devices = []
        for item in self._read(self.devices_path, "devices"):
            try:
                devices.append(
                    Device(
                        id=str(item["id"]),
                        name=str(item["name"]),
                        key_hash=str(item["key_hash"]),
                        created=str(item["created"]),
                        last_seen=item.get("last_seen"),
                    )
                )
            except KeyError:
                continue
        return devices

    def _save(self, devices: list[Device]) -> None:
        self._write(self.devices_path, "devices", [asdict(device) for device in devices])

    # -- pairing -----------------------------------------------------------------------------

    def start_pairing(self, name: str) -> str:
        """A one-time code for a new device called ``name``; replaces a pending pairing."""
        name = " ".join(str(name).split())
        if not NAME_RE.match(name):
            raise DeviceError("A device name is 1-40 letters, digits, spaces, dots or dashes.")
        code = secrets.token_urlsafe(32)
        expires = self._clock() + timedelta(minutes=PAIRING_MINUTES)
        with self._locked():
            if any(device.name == name for device in self._devices()):
                raise DeviceError(f"A device called {name!r} is already paired.")
            entry = {"code_hash": _hash(code), "name": name, "expires": expires.isoformat()}
            self._write(self.pairing_path, "pairings", [entry])
        return code

    def pair(self, code: str) -> tuple[Device, str]:
        """Turn the pending pairing that ``code`` opens into a device; returns it and its key.
        The code works once, and not after its expiry."""
        if not isinstance(code, str) or not code:
            raise DeviceError("No pairing code.")
        wanted = _hash(code)
        now = self._clock()
        with self._locked():
            pairings = self._read(self.pairing_path, "pairings")
            match = next(
                (
                    entry
                    for entry in pairings
                    if hmac.compare_digest(str(entry.get("code_hash", "")), wanted)
                ),
                None,
            )
            if match is None:
                raise DeviceError("This pairing link is not valid. Run tau web device add again.")
            remaining = [entry for entry in pairings if entry is not match]
            self._write(self.pairing_path, "pairings", remaining)
            try:
                expired = datetime.fromisoformat(str(match["expires"])) <= now
            except (KeyError, ValueError):
                expired = True
            if expired:
                raise DeviceError("This pairing link has expired. Run tau web device add again.")
            key = secrets.token_urlsafe(32)
            device = Device(
                id=f"web-{secrets.token_hex(6)}",
                name=str(match["name"]),
                key_hash=_hash(key),
                created=now.isoformat(),
            )
            self._save([*self._devices(), device])
        return device, key

    # -- devices -----------------------------------------------------------------------------

    def verify(self, key: str | None) -> Device | None:
        """The device whose key this is, or ``None``."""
        if not key:
            return None
        wanted = _hash(key)
        found = None
        for device in self._devices():
            if hmac.compare_digest(device.key_hash, wanted):
                found = device
        return found

    def touch(self, device: Device) -> None:
        """Record that ``device`` was seen now (best effort, at most once a minute)."""
        now = self._clock()
        if device.last_seen:
            try:
                if now - datetime.fromisoformat(device.last_seen) < timedelta(minutes=1):
                    return
            except ValueError:
                pass
        with self._locked():
            devices = [
                Device(**{**asdict(d), "last_seen": now.isoformat()}) if d.id == device.id else d
                for d in self._devices()
            ]
            self._save(devices)

    def list(self) -> list[Device]:
        return self._devices()

    def remove(self, which: str) -> Device:
        """Remove the device with this id or name; its cookie stops working at once."""
        with self._locked():
            devices = self._devices()
            match = [d for d in devices if which in (d.id, d.name)]
            if not match:
                raise DeviceError(f"No paired device is called {which!r}.")
            self._save([d for d in devices if d not in match])
        return match[0]


def with_suppressed_unlink(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass
