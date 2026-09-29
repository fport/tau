"""In-memory session store: the full interface, nothing survives the process."""

from __future__ import annotations

import copy
import threading
from typing import Any

from strands.types.exceptions import SessionException
from strands.types.session import Session, SessionAgent, SessionMessage, SessionType

from tau_core.events import AgentEvent
from tau_core.sessions.base import SessionStore, SessionSummary, utc_now_iso


class MemorySessionStore(SessionStore):
    """Dict-backed store. Records are stored as dicts so callers never share objects."""

    def __init__(self) -> None:
        self._sessions: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()

    # -- helpers -----------------------------------------------------------------------------

    def _record(self, session_id: str) -> dict[str, Any]:
        record = self._sessions.get(session_id)
        if record is None:
            raise SessionException(f"Session {session_id} does not exist")
        return record

    def _agent(self, session_id: str, agent_id: str) -> dict[str, Any]:
        agent = self._record(session_id)["agents"].get(agent_id)
        if agent is None:
            raise SessionException(f"Agent {agent_id} does not exist in session {session_id}")
        return agent

    def _touch(self, session_id: str) -> None:
        self._record(session_id)["updated_at"] = utc_now_iso()

    def _new_record(self, session: Session) -> dict[str, Any]:
        data = session.to_dict()
        data["session_type"] = SessionType(data.get("session_type", SessionType.AGENT)).value
        return {
            "session": data,
            "agents": {},
            "meta": {},
            "events": [],
            "updated_at": data.get("updated_at") or utc_now_iso(),
        }

    # -- SessionRepository -------------------------------------------------------------------

    def create_session(self, session: Session, **kwargs: Any) -> Session:
        with self._lock:
            if session.session_id in self._sessions:
                raise SessionException(f"Session {session.session_id} already exists")
            self._sessions[session.session_id] = self._new_record(session)
            return session

    def read_session(self, session_id: str, **kwargs: Any) -> Session | None:
        with self._lock:
            record = self._sessions.get(session_id)
            if record is None:
                return None
            return Session.from_dict(copy.deepcopy(record["session"]))

    def create_agent(self, session_id: str, session_agent: SessionAgent, **kwargs: Any) -> None:
        with self._lock:
            record = self._record(session_id)
            record["agents"][session_agent.agent_id] = {
                "agent": session_agent.to_dict(),
                "messages": {},
            }
            self._touch(session_id)

    def read_agent(self, session_id: str, agent_id: str, **kwargs: Any) -> SessionAgent | None:
        with self._lock:
            record = self._sessions.get(session_id)
            if record is None or agent_id not in record["agents"]:
                return None
            return SessionAgent.from_dict(copy.deepcopy(record["agents"][agent_id]["agent"]))

    def update_agent(self, session_id: str, session_agent: SessionAgent, **kwargs: Any) -> None:
        with self._lock:
            agent = self._agent(session_id, session_agent.agent_id)
            data = session_agent.to_dict()
            data["created_at"] = agent["agent"].get("created_at", data.get("created_at"))
            data["updated_at"] = utc_now_iso()
            agent["agent"] = data
            self._touch(session_id)

    def create_message(
        self, session_id: str, agent_id: str, session_message: SessionMessage, **kwargs: Any
    ) -> None:
        with self._lock:
            agent = self._agent(session_id, agent_id)
            agent["messages"][session_message.message_id] = session_message.to_dict()
            self._touch(session_id)

    def read_message(
        self, session_id: str, agent_id: str, message_id: int, **kwargs: Any
    ) -> SessionMessage | None:
        with self._lock:
            record = self._sessions.get(session_id)
            if record is None or agent_id not in record["agents"]:
                return None
            data = record["agents"][agent_id]["messages"].get(message_id)
            return SessionMessage.from_dict(copy.deepcopy(data)) if data is not None else None

    def update_message(
        self, session_id: str, agent_id: str, session_message: SessionMessage, **kwargs: Any
    ) -> None:
        with self._lock:
            agent = self._agent(session_id, agent_id)
            if session_message.message_id not in agent["messages"]:
                raise SessionException(f"Message {session_message.message_id} does not exist")
            data = session_message.to_dict()
            data["updated_at"] = utc_now_iso()
            agent["messages"][session_message.message_id] = data
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
            agent = self._agent(session_id, agent_id)
            ids = sorted(agent["messages"])[offset:]
            if limit is not None:
                ids = ids[:limit]
            return [SessionMessage.from_dict(copy.deepcopy(agent["messages"][i])) for i in ids]

    # -- tau extras --------------------------------------------------------------------------

    def list_sessions(self, limit: int = 20) -> list[SessionSummary]:
        with self._lock:
            summaries = [
                SessionSummary(
                    session_id=session_id,
                    created_at=str(record["session"].get("created_at", "")),
                    updated_at=str(record["updated_at"]),
                    channel=str(record["meta"].get("channel", "")),
                    profile=str(record["meta"].get("profile", "")),
                    title=str(record["meta"].get("title", "")),
                    message_count=sum(len(a["messages"]) for a in record["agents"].values()),
                )
                for session_id, record in self._sessions.items()
            ]
        summaries.sort(key=lambda s: (s.updated_at, s.session_id), reverse=True)
        return summaries[:limit]

    def append_event(self, session_id: str, event: AgentEvent) -> None:
        with self._lock:
            if session_id not in self._sessions:
                self.create_session(Session(session_id=session_id, session_type=SessionType.AGENT))
            self._record(session_id)["events"].append(copy.deepcopy(event.to_dict()))
            self._touch(session_id)

    def read_events(self, session_id: str) -> list[AgentEvent]:
        with self._lock:
            record = self._sessions.get(session_id)
            if record is None:
                return []
            return [AgentEvent.from_dict(copy.deepcopy(e)) for e in record["events"]]

    def write_meta(self, session_id: str, **meta: Any) -> None:
        with self._lock:
            if session_id not in self._sessions:
                self.create_session(Session(session_id=session_id, session_type=SessionType.AGENT))
            self._record(session_id)["meta"].update(copy.deepcopy(meta))
            self._touch(session_id)

    def read_meta(self, session_id: str) -> dict[str, Any]:
        with self._lock:
            record = self._sessions.get(session_id)
            return copy.deepcopy(record["meta"]) if record is not None else {}
