"""Agent events: one record type for logs, session records and UIs.

An :class:`AgentEvent` is what the agent did in a session (a tool call, an approval, a turn
limit, an error, a notice). It is not a mesh *Event* on Zenoh. The ``data`` keys per kind are
the contract (see ``docs/adr`` and the tau-core README); UIs render unknown kinds as text.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

logger = logging.getLogger(__name__)

EventKind = Literal["tool_call", "approval", "turn_limit", "error", "notice"]
"""The documented L1 kinds. ``AgentEvent.kind`` is a plain ``str`` so later layers add kinds."""


@dataclass(frozen=True)
class AgentEvent:
    kind: str
    at: datetime
    session_id: str | None
    data: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        kind: str,
        data: dict[str, Any] | None = None,
        *,
        session_id: str | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> AgentEvent:
        """An event stamped with ``clock()`` (default: now, UTC)."""
        at = clock() if clock is not None else datetime.now(UTC)
        return cls(kind=kind, at=at, session_id=session_id, data=dict(data or {}))

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "at": self.at.isoformat(),
            "session_id": self.session_id,
            "data": self.data,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> AgentEvent:
        at = d.get("at")
        parsed = datetime.fromisoformat(at) if isinstance(at, str) else datetime.now(UTC)
        return cls(
            kind=str(d.get("kind", "notice")),
            at=parsed,
            session_id=d.get("session_id"),
            data=dict(d.get("data") or {}),
        )


class EventSink(Protocol):
    def emit(self, event: AgentEvent) -> None: ...


class EventBus:
    """Synchronous fan-out. A failing subscriber is logged and never breaks the emitter."""

    def __init__(self) -> None:
        self._subscribers: list[Callable[[AgentEvent], None]] = []
        self._lock = threading.Lock()

    def subscribe(self, sink: Callable[[AgentEvent], None]) -> Callable[[], None]:
        """Add ``sink``; returns a function that removes it again (idempotent)."""
        with self._lock:
            self._subscribers.append(sink)

        def unsubscribe() -> None:
            with self._lock:
                if sink in self._subscribers:
                    self._subscribers.remove(sink)

        return unsubscribe

    def emit(self, event: AgentEvent) -> None:
        with self._lock:
            subscribers = list(self._subscribers)
        for sink in subscribers:
            try:
                sink(event)
            except Exception:
                logger.exception("event subscriber %r failed on %s", sink, event.kind)
