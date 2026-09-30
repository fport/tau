"""The ``spine`` session backend: sessions in the spine's D1 through its hub API (cloud mode).

``[sessions] backend = "spine"`` picks :func:`make_store` (entry point ``tau.sessions``
``spine``). :class:`SpineSessionStore` speaks the session routes of §5 of
``docs/reference/tau-network.md`` with :class:`tau_net.spine.SpineClient` and mirrors
:class:`tau_core.sessions.FileSessionStore`:

- ids are validated before any request (letters, digits, ``.``, ``_``, ``-``; at most 128),
  and a bad one raises :class:`tau_core.sessions.InvalidSessionId`;
- creating a session or a message that exists, updating an agent or a message that does not,
  and adding an agent or listing messages without the record raise Strands'
  ``SessionException``;
- updates keep the record's ``created_at`` and set ``updated_at``; reads of missing records
  return ``None`` (``{}`` for meta, ``[]`` for events);
- ``write_meta`` merges and ``append_event`` appends, both creating a missing session;
- nothing is ever deleted: the store has no delete method, and the spine has no delete route.

The spine keeps every body as opaque JSON (Strands' ``to_dict()``). A spine that cannot be
reached, or that says no, raises :class:`SpineStoreError` (a ``SessionException``) with the
spine's URL and error code, never the token: a write is never dropped silently.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from strands.types.exceptions import SessionException
from strands.types.session import Session, SessionAgent, SessionMessage, SessionType
from tau_core import Config, ConfigError, SessionStore
from tau_core.events import AgentEvent
from tau_core.sessions import InvalidSessionId, SessionSummary
from tau_net.config import SPINE_TOKEN_ENV, SPINE_URL_ENV, NetConfigError, net_env, spine_from_env
from tau_net.spine import SpineClient, SpineResponse, SpineUnreachable, Transport

__all__ = [
    "MAX_SESSIONS_LIMIT",
    "MESSAGE_PAGE",
    "SpineSessionStore",
    "SpineStoreError",
    "make_store",
    "validate_id",
]

logger = logging.getLogger(__name__)

MAX_SESSIONS_LIMIT = 200
"""The most sessions ``GET /hub/sessions`` returns in one answer."""
MESSAGE_PAGE = 1000
"""Messages fetched per request by :meth:`SpineSessionStore.list_messages`."""
RETRY_DELAY = 0.5
_RETRY_METHODS = frozenset({"GET", "PUT", "PATCH"})
_RETRY_STATUSES = frozenset({502, 503, 504})
_ID_PATTERN = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")


class SpineStoreError(SessionException):
    """The spine could not be reached or refused a session request; meant for the user."""


def validate_id(value: str, *, what: str = "session") -> str:
    """``value`` when it is a valid session or agent id (the rule of the file store and of the
    spine), else :class:`InvalidSessionId` with the file store's message."""
    if not isinstance(value, str) or not _ID_PATTERN.match(value):
        raise InvalidSessionId(
            f"Invalid {what} id: '{value}'. Only letters, digits, '.', '_' and '-' are allowed."
        )
    return value


def _message_id(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"message_id=<{value}> | must be a non-negative integer")
    return value


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _plain(value: Any) -> Any:
    """``value`` as plain JSON types; anything else becomes its ``str`` (like the file store's
    ``json.dump(default=str)``)."""
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


class SpineSessionStore(SessionStore):
    """Sessions stored by a cloud-mode spine (see the module doc)."""

    def __init__(self, spine: SpineClient, *, retry_delay: float = RETRY_DELAY) -> None:
        self.spine = spine
        self.retry_delay = retry_delay
        self._agent_created: dict[tuple[str, str], str] = {}
        self._lock = threading.Lock()

    def __repr__(self) -> str:
        return f"SpineSessionStore({self.spine.url!r})"

    # -- requests ------------------------------------------------------------------------------

    def _fail(self, response: SpineResponse) -> SpineStoreError:
        code, detail = response.error()
        if code == "cloud_mode_off":
            return SpineStoreError(
                f"The spine at {self.spine.url} is not in cloud mode (404 cloud_mode_off); "
                'the "spine" session backend needs a spine deployed with the cloud configuration.'
            )
        text = f"The spine at {self.spine.url} answered {response.status} {code}"
        return SpineStoreError(f"{text}: {detail}" if detail else text)

    def _request(self, method: str, path: str, **kwargs: Any) -> SpineResponse:
        """One request; a safe one (GET, PUT, PATCH) is tried once more after a network error
        or a 502/503/504. Raises :class:`SpineStoreError` when no answer came."""
        attempts = 2 if method in _RETRY_METHODS else 1
        for attempt in range(attempts):
            last = attempt == attempts - 1
            try:
                response = self.spine.request(method, path, **kwargs)
            except SpineUnreachable as exc:
                if last:
                    raise SpineStoreError(
                        f"The spine at {self.spine.url} is unreachable: {exc.detail}"
                    ) from None
            else:
                if response.status not in _RETRY_STATUSES or last:
                    return response
            logger.info("session store: retrying %s %s", method, path)
            time.sleep(self.retry_delay)
        raise AssertionError("unreachable")  # pragma: no cover

    @staticmethod
    def _missing(response: SpineResponse) -> bool:
        """A plain ``404 not_found`` (``cloud_mode_off`` is a 404 too, but an error)."""
        return response.status == 404 and response.error()[0] == "not_found"

    def _data(self, response: SpineResponse, key: str = "data") -> Any:
        if not response.ok:
            raise self._fail(response)
        try:
            body = response.json()
        except ValueError:
            raise SpineStoreError(f"The spine at {self.spine.url} sent invalid JSON.") from None
        if not isinstance(body, dict) or key not in body:
            raise SpineStoreError(f"The spine at {self.spine.url} sent an answer without {key}.")
        return body[key]

    def _record(self, response: SpineResponse) -> dict[str, Any] | None:
        """``data`` of a record read, ``None`` for a missing one."""
        if self._missing(response):
            return None
        data = self._data(response)
        if not isinstance(data, dict):
            raise SpineStoreError(
                f"The spine at {self.spine.url} holds a record that is not a JSON object."
            )
        return data

    @staticmethod
    def _session_path(session_id: str) -> str:
        return f"/hub/sessions/{validate_id(session_id)}"

    def _agent_path(self, session_id: str, agent_id: str) -> str:
        return f"{self._session_path(session_id)}/agents/{validate_id(agent_id, what='agent')}"

    def _message_path(self, session_id: str, agent_id: str, message_id: int) -> str:
        return f"{self._agent_path(session_id, agent_id)}/messages/{_message_id(message_id)}"

    # -- SessionRepository ---------------------------------------------------------------------

    def create_session(self, session: Session, **kwargs: Any) -> Session:
        session_id = validate_id(session.session_id)
        data = session.to_dict()
        data["session_type"] = SessionType(data.get("session_type", SessionType.AGENT)).value
        data["updated_at"] = data.get("updated_at") or _now_iso()
        response = self._request(
            "POST", "/hub/sessions", json={"session_id": session_id, "data": _plain(data)}
        )
        if response.status == 409:
            raise SessionException(f"Session {session_id} already exists")
        if not response.ok:
            raise self._fail(response)
        return session

    def read_session(self, session_id: str, **kwargs: Any) -> Session | None:
        data = self._record(self._request("GET", self._session_path(session_id)))
        return Session.from_dict(data) if data is not None else None

    def create_agent(self, session_id: str, session_agent: SessionAgent, **kwargs: Any) -> None:
        path = self._session_path(session_id)
        agent_id = validate_id(session_agent.agent_id, what="agent")
        data = _plain(session_agent.to_dict())
        response = self._request(
            "POST", f"{path}/agents", json={"agent_id": agent_id, "data": data}
        )
        if self._missing(response):
            raise SessionException(f"Session {session_id} does not exist")
        if response.status == 409:
            # The file store writes the record whether or not it exists; so does this one.
            response = self._request("PUT", f"{path}/agents/{agent_id}", json={"data": data})
        if not response.ok:
            raise self._fail(response)
        with self._lock:
            self._agent_created[(session_id, agent_id)] = str(data.get("created_at", ""))

    def read_agent(self, session_id: str, agent_id: str, **kwargs: Any) -> SessionAgent | None:
        data = self._record(self._request("GET", self._agent_path(session_id, agent_id)))
        if data is None:
            return None
        with self._lock:
            self._agent_created[(session_id, agent_id)] = str(data.get("created_at", ""))
        return SessionAgent.from_dict(data)

    def update_agent(self, session_id: str, session_agent: SessionAgent, **kwargs: Any) -> None:
        agent_id = session_agent.agent_id
        path = self._agent_path(session_id, agent_id)
        missing = SessionException(f"Agent {agent_id} does not exist in session {session_id}")
        with self._lock:
            created_at = self._agent_created.get((session_id, agent_id))
        if not created_at:
            previous = self._record(self._request("GET", path))
            if previous is None:
                raise missing
            created_at = str(previous.get("created_at", ""))
        data = session_agent.to_dict()
        data["created_at"] = created_at or data.get("created_at")
        data["updated_at"] = _now_iso()
        response = self._request("PUT", path, json={"data": _plain(data)})
        if self._missing(response):
            raise missing
        if not response.ok:
            raise self._fail(response)
        with self._lock:
            self._agent_created[(session_id, agent_id)] = str(data["created_at"] or "")

    def create_message(
        self, session_id: str, agent_id: str, session_message: SessionMessage, **kwargs: Any
    ) -> None:
        message_id = _message_id(session_message.message_id)
        path = f"{self._agent_path(session_id, agent_id)}/messages"
        response = self._request(
            "POST",
            path,
            json={"message_id": message_id, "data": _plain(session_message.to_dict())},
        )
        if response.status == 409:
            # Two writers on one session; overwriting would lose a message.
            raise SessionException(f"Message {message_id} already exists in session {session_id}")
        if self._missing(response):
            raise SessionException(f"Agent {agent_id} does not exist in session {session_id}")
        if not response.ok:
            raise self._fail(response)

    def read_message(
        self, session_id: str, agent_id: str, message_id: int, **kwargs: Any
    ) -> SessionMessage | None:
        path = self._message_path(session_id, agent_id, message_id)
        data = self._record(self._request("GET", path))
        return SessionMessage.from_dict(data) if data is not None else None

    def update_message(
        self, session_id: str, agent_id: str, session_message: SessionMessage, **kwargs: Any
    ) -> None:
        """Strands calls this to redact a message; the original stays in ``message``."""
        message_id = session_message.message_id
        path = self._message_path(session_id, agent_id, message_id)
        previous = self._record(self._request("GET", path))
        if previous is None:
            raise SessionException(f"Message {message_id} does not exist")
        data = session_message.to_dict()
        data["created_at"] = previous.get("created_at", data.get("created_at"))
        data["updated_at"] = _now_iso()
        response = self._request("PUT", path, json={"data": _plain(data)})
        if self._missing(response):
            raise SessionException(f"Message {message_id} does not exist")
        if not response.ok:
            raise self._fail(response)

    def list_messages(
        self,
        session_id: str,
        agent_id: str,
        limit: int | None = None,
        offset: int = 0,
        **kwargs: Any,
    ) -> list[SessionMessage]:
        path = f"{self._agent_path(session_id, agent_id)}/messages"
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValueError(f"offset=<{offset}> | must be a non-negative integer")
        if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int)):
            raise ValueError(f"limit=<{limit}> | must be an integer or None")
        messages: list[SessionMessage] = []
        while True:
            wanted = MESSAGE_PAGE if limit is None else min(MESSAGE_PAGE, limit - len(messages))
            if wanted <= 0:
                return messages
            response = self._request(
                "GET", path, params={"offset": offset + len(messages), "limit": wanted}
            )
            if self._missing(response):
                raise SessionException(f"Agent {agent_id} does not exist in session {session_id}")
            page = self._data(response, "messages")
            if not isinstance(page, list):
                raise SpineStoreError(f"The spine at {self.spine.url} sent a bad message list.")
            messages.extend(SessionMessage.from_dict(item) for item in page)
            if len(page) < wanted:
                return messages

    # -- tau extras ----------------------------------------------------------------------------

    def list_sessions(self, limit: int = 20) -> list[SessionSummary]:
        """Most recently updated first; at most :data:`MAX_SESSIONS_LIMIT` in one listing."""
        if limit < 1:
            return []
        response = self._request(
            "GET", "/hub/sessions", params={"limit": min(limit, MAX_SESSIONS_LIMIT)}
        )
        rows = self._data(response, "sessions")
        if not isinstance(rows, list):
            raise SpineStoreError(f"The spine at {self.spine.url} sent a bad session list.")
        summaries = []
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("session_id"), str):
                logger.warning("skipping an unreadable session row from the spine")
                continue
            meta = row.get("meta") if isinstance(row.get("meta"), dict) else {}
            count = row.get("message_count")
            summaries.append(
                SessionSummary(
                    session_id=row["session_id"],
                    created_at=str(row.get("created_at") or ""),
                    updated_at=str(row.get("updated_at") or row.get("created_at") or ""),
                    channel=str(meta.get("channel", "")),
                    profile=str(meta.get("profile", "")),
                    title=str(meta.get("title", "")),
                    message_count=count if isinstance(count, int) else 0,
                )
            )
        return summaries[:limit]

    def append_event(self, session_id: str, event: AgentEvent) -> None:
        path = f"{self._session_path(session_id)}/events"
        response = self._request("POST", path, json={"data": _plain(event.to_dict())})
        if not response.ok:
            raise self._fail(response)

    def read_events(self, session_id: str) -> list[AgentEvent]:
        response = self._request("GET", f"{self._session_path(session_id)}/events")
        items = self._data(response, "events")
        if not isinstance(items, list):
            raise SpineStoreError(f"The spine at {self.spine.url} sent a bad event list.")
        events = []
        for number, item in enumerate(items, start=1):
            try:
                if not isinstance(item, dict):
                    raise ValueError("not a JSON object")
                events.append(AgentEvent.from_dict(item))
            except (ValueError, TypeError) as exc:
                logger.warning(
                    "skipping unreadable event %d of session %s: %s", number, session_id, exc
                )
        return events

    def write_meta(self, session_id: str, **meta: Any) -> None:
        path = f"{self._session_path(session_id)}/meta"
        response = self._request("PATCH", path, json={"meta": _plain(meta)})
        if not response.ok:
            raise self._fail(response)

    def read_meta(self, session_id: str) -> dict[str, Any]:
        meta = self._data(self._request("GET", f"{self._session_path(session_id)}/meta"), "meta")
        return meta if isinstance(meta, dict) else {}


def make_store(
    config: Config,
    *,
    env: Mapping[str, str] | None = None,
    transport: Transport | None = None,
) -> SpineSessionStore:
    """The ``tau.sessions`` factory for ``spine``: the spine from ``TAU_SPINE_URL`` and
    ``TAU_SPINE_TOKEN`` (the environment on top of ``<home>/.env``). Opening the store sends
    no request; a missing or unusable variable is a ``ConfigError``."""
    values = net_env(config, env)
    try:
        spine = spine_from_env(values, transport=transport)
    except NetConfigError as exc:
        raise ConfigError(str(exc)) from None
    if spine is None:
        raise ConfigError(
            f'Session backend "spine" needs {SPINE_URL_ENV} and {SPINE_TOKEN_ENV} (the spine\'s '
            "URL and its HUB_TOKEN) in the environment or in .env."
        )
    return SpineSessionStore(spine)
