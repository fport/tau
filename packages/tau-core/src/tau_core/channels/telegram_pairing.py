"""Telegram pairing: the owner's chat without looking up a chat id (ADR 0014 §5, issue 172).

``tau telegram pair`` stores the bot token in ``<home>/.env`` and a one-time code in
``TAU_DATA_DIR/telegram/pairing.json``. The owner sends ``/start <code>`` to the bot (the deep
link ``https://t.me/<bot>?start=<code>`` does it in one tap). Whoever polls the Bot API accepts
it with :func:`try_pair`: the hub's Telegram service while a hub runs, else the command itself.
One process polls at a time, from the offset in ``TAU_DATA_DIR/telegram/offset``, and no server
sits between Telegram and the hub (ADR 0006 §2).

- **The code**: :data:`CODE_LENGTH` characters from :data:`CODE_ALPHABET` (no ``0/O`` or
  ``1/I/L``), drawn with :mod:`secrets`, shown as ``ABCD-EFGH`` and compared without case,
  dashes or spaces. It is valid :data:`CODE_TTL_SECONDS` and works once.
- **At rest** only a salted PBKDF2-SHA256 hash is stored (mode 0600 in a 0700 directory); the
  code itself is never written or logged.
- **Accepted** only from a private chat (never a group or a channel), before it expires. Each
  wrong code counts, and after :data:`MAX_FAILURES` the code is void. A wrong, expired or void
  code stores nothing and gets no answer, so the bot still does not confirm itself to strangers.
- **Paired**: ``TELEGRAM_ALLOWED_CHAT_IDS`` in ``<home>/.env`` becomes that chat (the one line is
  replaced, every other line kept, the file kept at 0600) and the record says ``paired``.

Changes to the record happen under an exclusive ``flock`` on ``pairing.lock``, so a hub and a
command that race over one code cannot both accept it.
"""

from __future__ import annotations

import fcntl
import hashlib
import hmac
import json
import logging
import os
import secrets
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

__all__ = [
    "CODE_ALPHABET",
    "CODE_LENGTH",
    "CODE_TTL_SECONDS",
    "MAX_FAILURES",
    "Pairing",
    "PairResult",
    "PairingStore",
    "deep_link",
    "format_code",
    "message_name",
    "new_code",
    "normalize_code",
    "start_payload",
    "try_pair",
    "write_owner_chat",
]

logger = logging.getLogger(__name__)

CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
"""Upper-case letters and digits without the look-alikes ``0 O 1 I L``."""
CODE_LENGTH = 8
CODE_TTL_SECONDS = 600
MAX_FAILURES = 10
"""Wrong codes (from any chat) a pending code survives; the next one voids it."""
KDF = "pbkdf2-sha256"
KDF_ITERATIONS = 100_000
PAIRING_FILE = "pairing.json"
LOCK_FILE = "pairing.lock"
MAX_PAYLOAD = 64
"""Telegram's limit for a deep-link ``start`` parameter."""

Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(UTC)


# -- the code ------------------------------------------------------------------------------------


def new_code() -> str:
    """A fresh code of :data:`CODE_LENGTH` characters, cryptographically random."""
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


def normalize_code(text: str) -> str:
    """``text`` in upper case without dashes and whitespace (``abcd-efgh`` → ``ABCDEFGH``)."""
    return "".join(ch for ch in text.upper() if ch != "-" and not ch.isspace())


def format_code(code: str) -> str:
    """The code as the owner reads and types it: ``ABCD-EFGH``."""
    code = normalize_code(code)
    half = len(code) // 2
    return f"{code[:half]}-{code[half:]}" if half else code


def deep_link(username: str, code: str) -> str:
    """``https://t.me/<bot>?start=<code>``: Telegram opens the bot and sends ``/start <code>``."""
    return f"https://t.me/{username.lstrip('@')}?start={format_code(code)}"


def start_payload(text: object) -> str | None:
    """The normalized code of ``/start <code>`` (also ``/start@bot <code>``); ``None`` for any
    other text, for a bare ``/start`` and for a payload longer than Telegram allows."""
    if not isinstance(text, str):
        return None
    parts = text.strip().split(maxsplit=1)
    if len(parts) != 2 or parts[0].split("@", 1)[0].casefold() != "/start":
        return None
    code = normalize_code(parts[1])
    return code if 0 < len(code) <= MAX_PAYLOAD else None


def _digest(code: str, salt: bytes, iterations: int) -> str:
    return hashlib.pbkdf2_hmac("sha256", code.encode("utf-8"), salt, iterations).hex()


def message_name(message: Mapping[str, Any]) -> str:
    """How the pairing chat names itself (first name and ``@username``), for the owner to
    check that the paired chat is theirs. Never a chat id."""
    person = message.get("from") or message.get("chat") or {}
    first = str(person.get("first_name") or "").strip()
    username = str(person.get("username") or "").strip()
    parts = [first] if first else []
    if username:
        parts.append(f"@{username}")
    return " ".join(parts) or "?"


# -- the record ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Pairing:
    """The pairing record as a reader sees it. ``state`` is ``pending``, ``paired``,
    ``expired`` (the clock passed ``expires_at``) or ``void`` (too many wrong codes)."""

    state: str
    expires_at: datetime | None = None
    failures: int = 0
    name: str | None = None
    """The paired chat's :func:`message_name`, once ``paired``."""
    dropped: int = 0
    """Chats that were allowed before the pairing and are not any more."""

    @property
    def pending(self) -> bool:
        return self.state == "pending"


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="seconds")


class PairingStore:
    """``TAU_DATA_DIR/telegram/pairing.json`` and its lock. ``clock`` is for tests."""

    def __init__(self, root: Path, *, clock: Clock = _utc_now):
        self.root = Path(root)
        self.path = self.root / PAIRING_FILE
        self.lock_path = self.root / LOCK_FILE
        self.clock = clock

    # -- files ------------------------------------------------------------------------------

    def _ensure_dir(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        with suppress(OSError):
            os.chmod(self.root, 0o700)

    @contextmanager
    def locked(self) -> Iterator[None]:
        """Hold the exclusive lock of the record (a blocking ``flock``)."""
        self._ensure_dir()
        fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            with suppress(OSError):
                fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def _read(self) -> dict[str, Any] | None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as exc:
            logger.warning("telegram: ignoring unreadable %s: %s", self.path, exc)
            return None
        return raw if isinstance(raw, dict) else None

    def _write(self, record: Mapping[str, Any]) -> None:
        from tau_core.channels.telegram import _write_atomic

        self._ensure_dir()
        _write_atomic(self.path, json.dumps(dict(record), indent=2) + "\n")

    def _remove(self) -> None:
        with suppress(FileNotFoundError):
            self.path.unlink()

    def _view(self, record: Mapping[str, Any] | None) -> Pairing | None:
        if record is None:
            return None
        state = record.get("state")
        expires_at = _parse_time(record.get("expires_at"))
        if state == "pending" and (expires_at is None or self.clock() >= expires_at):
            state = "expired"
        if state not in ("pending", "paired", "expired", "void"):
            return None
        failures = record.get("failures")
        dropped = record.get("dropped")
        name = record.get("name")
        return Pairing(
            state=str(state),
            expires_at=expires_at,
            failures=failures if isinstance(failures, int) else 0,
            name=name if isinstance(name, str) else None,
            dropped=dropped if isinstance(dropped, int) else 0,
        )

    # -- the record -------------------------------------------------------------------------

    def create(
        self, *, code: str | None = None, ttl: float = CODE_TTL_SECONDS
    ) -> tuple[str, Pairing]:
        """Store a new pending code (replacing any earlier record) and return it with its
        view. Only the salted hash reaches the disk."""
        code = normalize_code(code) if code is not None else new_code()
        salt = secrets.token_bytes(16)
        now = self.clock()
        expires_at = now + timedelta(seconds=ttl)
        record = {
            "v": 1,
            "state": "pending",
            "kdf": KDF,
            "iterations": KDF_ITERATIONS,
            "salt": salt.hex(),
            "hash": _digest(code, salt, KDF_ITERATIONS),
            "created_at": _iso(now),
            "expires_at": _iso(expires_at),
            "failures": 0,
        }
        with self.locked():
            self._write(record)
        view = self._view(record)
        assert view is not None
        return code, view

    def current(self) -> Pairing | None:
        """The record as it stands now (``None`` when there is none)."""
        return self._view(self._read())

    def pending(self) -> bool:
        """Is a code waiting and still valid?"""
        view = self.current()
        return view is not None and view.pending

    def finish(self) -> Pairing | None:
        """Remove the record and return how it ended: a pending code is withdrawn (it no longer
        works). The command calls this once it stops waiting, whatever the outcome."""
        with self.locked():
            view = self._view(self._read())
            self._remove()
        return view

    def attempt(
        self, code: str, on_match: Callable[[], Mapping[str, Any]]
    ) -> tuple[str, Mapping[str, Any]]:
        """Check ``code`` against the pending record under the lock.

        Returns ``(outcome, details)``: ``none`` (no pending record), ``expired``, ``wrong``,
        ``void`` (this wrong code used up the last try) or ``paired``. On a match ``on_match``
        runs while the lock is held (it writes ``.env``) and its mapping is stored with the
        ``paired`` record; if it raises, the code stays pending and the error propagates."""
        with self.locked():
            record = self._read()
            view = self._view(record)
            if record is None or view is None or view.state in ("paired", "void"):
                return "none", {}
            if view.state == "expired":
                if record.get("state") == "pending":
                    record["state"] = "expired"
                    self._write(record)
                return "expired", {}
            try:
                salt = bytes.fromhex(str(record.get("salt")))
                iterations = int(record.get("iterations") or KDF_ITERATIONS)
                expected = str(record.get("hash"))
            except (TypeError, ValueError):
                return "none", {}
            given = _digest(normalize_code(code), salt, iterations)
            if not hmac.compare_digest(given.encode(), expected.encode()):
                failures = view.failures + 1
                record["failures"] = failures
                outcome = "wrong"
                if failures >= MAX_FAILURES:
                    record["state"] = "void"
                    outcome = "void"
                self._write(record)
                return outcome, {}
            details = dict(on_match())
            paired = {
                "v": 1,
                "state": "paired",
                "created_at": record.get("created_at"),
                "expires_at": record.get("expires_at"),
                "paired_at": _iso(self.clock()),
                **{k: v for k, v in details.items() if k in ("name", "dropped")},
            }
            self._write(paired)
            return "paired", details


# -- accepting a code ----------------------------------------------------------------------------


@dataclass(frozen=True)
class PairResult:
    """What :func:`try_pair` did with a ``/start <code>`` message."""

    ok: bool
    reason: str
    """``paired``, ``wrong``, ``void``, ``expired`` or ``not_private``."""
    chat_id: int | None = None
    name: str | None = None
    allowed: frozenset[int] = frozenset()
    dropped: int = 0


def write_owner_chat(home: Path, chat_id: int) -> tuple[frozenset[int], int]:
    """Make ``chat_id`` the only entry of ``TELEGRAM_ALLOWED_CHAT_IDS`` in ``<home>/.env``
    (that line replaced or appended, every other line kept, the file at 0600). Returns the new
    allowlist and how many chats that were allowed before are not any more."""
    from dotenv import dotenv_values

    from tau_core.channels.telegram import ALLOWED_CHATS_ENV, parse_chat_ids
    from tau_core.settings import set_credential

    dotenv = Path(home) / ".env"
    before = dotenv_values(dotenv).get(ALLOWED_CHATS_ENV) if dotenv.is_file() else None
    previous, _ = parse_chat_ids(before)
    set_credential(home, ALLOWED_CHATS_ENV, str(chat_id))
    return frozenset({chat_id}), len(previous - {chat_id})


def try_pair(store: PairingStore, home: Path, message: Mapping[str, Any]) -> PairResult | None:
    """Pair the chat of ``message`` when it is ``/start <the pending code>``.

    ``None`` when the message is no pairing attempt at all (not ``/start <code>``, or no code
    is pending): the caller handles it as any other message. A refused attempt stores nothing
    and the caller answers nothing. Blocking (a PBKDF2 check and a file write): the hub runs
    it in a thread."""
    code = start_payload(message.get("text"))
    if code is None or not store.pending():
        return None
    chat = message.get("chat") or {}
    sender = message.get("from") or {}
    chat_id = chat.get("id")
    if (
        chat.get("type") != "private"
        or not isinstance(chat_id, int)
        or sender.get("is_bot")
        or sender.get("id", chat_id) != chat_id
    ):
        return PairResult(False, "not_private")
    name = message_name(message)
    written: dict[str, Any] = {}

    def on_match() -> Mapping[str, Any]:
        allowed, dropped = write_owner_chat(home, chat_id)
        written.update(allowed=allowed)
        return {"name": name, "dropped": dropped}

    outcome, details = store.attempt(code, on_match)
    if outcome == "none":
        return None
    if outcome != "paired":
        return PairResult(False, outcome)
    return PairResult(
        True,
        "paired",
        chat_id=chat_id,
        name=name,
        allowed=written["allowed"],
        dropped=int(details.get("dropped") or 0),
    )
