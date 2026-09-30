"""Presence signals for the reflex locks (ADR 0008 decision 10): HID idle and the screen lock.

Every read goes through the :class:`PresenceSource` protocol. :class:`QuartzPresence` is the
macOS implementation; it imports pyobjc's Quartz lazily, in its constructor, so this module
imports anywhere. Tests use :class:`tau_guard.testing.FakePresence`.

- **Idle**: ``CGEventSourceSecondsSinceLastEventType(kCGEventSourceStateHIDSystemState,
  kCGAnyInputEventType)``.
- **Screen lock**: ``CGSessionCopyCurrentDictionary()["CGSSessionScreenIsLocked"]``. A missing
  session (a hub started over SSH, no GUI) reads as unknown (``None``), never as locked or
  unlocked; the key is absent while the screen is unlocked.

A read never raises: a failing call gives ``None`` for that signal, and the state machine caps
an unlock at ``idle_lock_minutes`` while any signal is unknown.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol, runtime_checkable

from tau_guard.state import Reading

__all__ = ["PresenceSource", "PresenceUnavailable", "QuartzPresence", "Reading"]

logger = logging.getLogger(__name__)

SCREEN_LOCKED_KEY = "CGSSessionScreenIsLocked"
ANY_INPUT_EVENT = 0xFFFFFFFF
"""``kCGAnyInputEventType`` (``~0`` as a 32-bit value)."""


class PresenceUnavailable(Exception):
    """The platform offers no presence source (no Quartz)."""


@runtime_checkable
class PresenceSource(Protocol):
    def read(self) -> Reading: ...


class QuartzPresence:
    """HID idle and the screen lock through Quartz. Raises :class:`PresenceUnavailable` when
    Quartz cannot be imported (any platform but macOS, or pyobjc missing)."""

    def __init__(self, quartz: Any | None = None) -> None:
        if quartz is None:
            try:
                import Quartz  # type: ignore[import-not-found]
            except Exception as exc:  # ImportError, or a broken pyobjc install
                raise PresenceUnavailable(f"Quartz is not available: {exc}") from exc
            quartz = Quartz
        self._quartz = quartz
        self._warned = False

    def read(self) -> Reading:
        return Reading(idle_seconds=self._idle(), screen_locked=self._screen_locked())

    def _idle(self) -> float | None:
        quartz = self._quartz
        try:
            event = getattr(quartz, "kCGAnyInputEventType", ANY_INPUT_EVENT)
            seconds = quartz.CGEventSourceSecondsSinceLastEventType(
                quartz.kCGEventSourceStateHIDSystemState, event
            )
            value = float(seconds)
        except Exception as exc:
            self._warn("HID idle", exc)
            return None
        return value if value >= 0 else None

    def _screen_locked(self) -> bool | None:
        try:
            session = self._quartz.CGSessionCopyCurrentDictionary()
        except Exception as exc:
            self._warn("the screen lock", exc)
            return None
        if session is None:
            return None  # no GUI session: unknown
        try:
            value = session.get(SCREEN_LOCKED_KEY, False)
        except Exception as exc:
            self._warn("the screen lock", exc)
            return None
        return bool(value)

    def _warn(self, what: str, exc: Exception) -> None:
        if not self._warned:
            self._warned = True
            logger.warning("guard: %s could not be read (%s); treating it as unknown", what, exc)
