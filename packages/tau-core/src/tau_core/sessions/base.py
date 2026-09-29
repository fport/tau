"""The session store interface: a Strands ``SessionRepository`` plus what tau needs on top.

Strands persists messages and agent state through the repository; tau adds listing (for
``/devam``), agent events (tool calls, approvals, errors) and session metadata (channel,
profile, title). Callers only ever use :class:`SessionStore`; backends are registered in
``tau_core.sessions.SESSION_BACKENDS``.
"""

from __future__ import annotations

import secrets
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from strands.session import SessionRepository

from tau_core.events import AgentEvent


@dataclass(frozen=True)
class SessionSummary:
    session_id: str
    created_at: str
    updated_at: str
    channel: str
    profile: str
    title: str
    message_count: int


class SessionStore(SessionRepository, ABC):
    """Strands session repository + listing, events and metadata."""

    @abstractmethod
    def list_sessions(self, limit: int = 20) -> list[SessionSummary]:
        """Most recently updated first."""

    @abstractmethod
    def append_event(self, session_id: str, event: AgentEvent) -> None: ...

    @abstractmethod
    def read_events(self, session_id: str) -> list[AgentEvent]: ...

    @abstractmethod
    def write_meta(self, session_id: str, **meta: Any) -> None:
        """Merge ``meta`` (channel, profile, title, ...); creates the session record if missing."""

    @abstractmethod
    def read_meta(self, session_id: str) -> dict[str, Any]: ...

    def event_sink(self, session_id: str) -> Callable[[AgentEvent], None]:
        """A subscriber for ``EventBus.subscribe`` that records this session's events.

        Events stamped with another session id are ignored, so one bus can serve several
        sessions (for example after ``/yeni``) without mixing their records.
        """

        def sink(event: AgentEvent) -> None:
            if event.session_id in (None, session_id):
                self.append_event(session_id, event)

        return sink


def new_session_id(clock: Callable[[], datetime] | None = None) -> str:
    """Sortable id like ``20260929-153012-3f9a`` (UTC time + 4 random hex digits)."""
    now = clock() if clock is not None else datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    return f"{now.astimezone(UTC):%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()
