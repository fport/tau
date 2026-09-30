"""Public test helpers: the session and brain routes of a cloud-mode spine, in memory.

:class:`tau_net.testing.FakeSpine` implements the network routes and the cloud-mode state and
file routes; its ``/hub/sessions`` and ``/hub/brain`` answer ``501`` until something adds
them. :func:`install_cloud_routes` adds them, with the semantics of ``cloud/spine/src/store.ts``
(status codes, error bodies, ordering, the meta merge, implicit session creation, the listing
order and message counts)::

    spine = FakeSpine("127.0.0.1:8787", mode="cloud")
    cloud = install_cloud_routes(spine)
    store = SpineSessionStore(SpineClient(spine.url, DEFAULT_HUB_TOKEN, transport=spine))
    cloud.brain = {"ok": True, "version": "0.1.0", "hub": None}   # GET /hub/brain answers it

Like the real spine, the routes answer ``404 cloud_mode_off`` while the fake spine's ``mode``
is not ``"cloud"``. Timestamps come from the fake spine's ``clock`` (ISO 8601 with
milliseconds and ``Z``, like ``Date.toISOString()``). Stored bodies are kept as JSON text and
parsed on every read, so tests see exactly what a round trip through D1 gives.
"""

from __future__ import annotations

import json
import re
import threading
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from tau_net.testing import FakeRequest, FakeSpine

__all__ = [
    "BrainAnswer",
    "FakeCloud",
    "StoredSession",
    "install_cloud_routes",
]

MAX_DOCUMENT_BYTES = 1_048_576
MAX_SESSIONS_LIMIT = 200
DEFAULT_SESSIONS_LIMIT = 20
MAX_MESSAGES = 10_000
MAX_SAFE_INTEGER = 2**53 - 1
ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
MESSAGE_ID = re.compile(r"[0-9]{1,15}")
INT_PARAM = re.compile(r"[0-9]{1,15}")
ID_RULE = "^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"

BrainAnswer = dict[str, Any] | Callable[[], dict[str, Any] | None] | None
"""What ``GET /hub/brain`` answers: a health object, a callable returning one (or ``None``),
or ``None`` for ``503 brain_unavailable``."""

Answer = tuple[int, Any]


def _json_response(status: int, payload: Any, headers: dict[str, str] | None = None) -> Answer:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return status, (status, {"content-type": "application/json", **(headers or {})}, body)


def _error(status: int, code: str, detail: str | None = None) -> Answer:
    payload: dict[str, Any] = {"error": code}
    if detail is not None:
        payload["detail"] = detail
    return _json_response(status, payload)


def _bad_request(detail: str) -> Answer:
    return _error(400, "bad_request", detail)


def _not_found() -> Answer:
    return _error(404, "not_found")


def _method_not_allowed(allow: list[str]) -> Answer:
    return _json_response(405, {"error": "method_not_allowed"}, {"allow": ", ".join(allow)})


def _ok(status: int = 200) -> Answer:
    return status, {"ok": True}


def _int_param(query: dict[str, str], name: str, default: int) -> int | None:
    raw = query.get(name)
    if raw is None or raw == "":
        return default
    if not INT_PARAM.fullmatch(raw):
        return None
    return int(raw)


@dataclass
class StoredSession:
    """One row of the ``sessions`` table; ``data`` and ``meta`` are JSON text."""

    data: str
    meta: str
    created_at: str
    updated_at: str
    rev: int


@dataclass
class FakeCloud:
    """The in-memory tables behind the routes, for inspection (see the module doc)."""

    spine: FakeSpine
    brain: BrainAnswer = None
    sessions: dict[str, StoredSession] = field(default_factory=dict)
    agents: dict[tuple[str, str], str] = field(default_factory=dict)
    messages: dict[tuple[str, str, int], str] = field(default_factory=dict)
    events: list[tuple[int, str, str]] = field(default_factory=list)
    _rev: int = 0
    _seq: int = 0
    _lock: threading.RLock = field(default_factory=threading.RLock)

    # -- inspection ----------------------------------------------------------------------------

    def session_data(self, session_id: str) -> dict[str, Any] | None:
        row = self.sessions.get(session_id)
        return json.loads(row.data) if row else None

    def message_data(self, session_id: str, agent_id: str) -> list[dict[str, Any]]:
        with self._lock:
            keys = sorted(k for k in self.messages if k[0] == session_id and k[1] == agent_id)
            return [json.loads(self.messages[key]) for key in keys]

    # -- helpers -------------------------------------------------------------------------------

    def now_iso(self) -> str:
        """``Date.toISOString()`` of the fake spine's clock."""
        moment = datetime.fromtimestamp(self.spine.clock(), UTC)
        return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"

    def _next_rev(self) -> int:
        self._rev += 1
        return self._rev

    def _touch(self, sid: str, now: str) -> None:
        row = self.sessions.get(sid)
        if row is not None:
            row.updated_at = now
            row.rev = self._next_rev()

    def _upsert(self, sid: str, now: str, meta: str | None = None) -> None:
        row = self.sessions.get(sid)
        if row is None:
            data = {
                "session_id": sid,
                "session_type": "AGENT",
                "created_at": now,
                "updated_at": now,
            }
            self.sessions[sid] = StoredSession(
                json.dumps(data), meta if meta is not None else "{}", now, now, self._next_rev()
            )
            return
        if meta is not None:
            row.meta = meta
        row.updated_at = now
        row.rev = self._next_rev()

    @staticmethod
    def _read_object(request: FakeRequest) -> tuple[dict[str, Any] | None, Answer | None]:
        if len(request.body) > MAX_DOCUMENT_BYTES:
            return None, _error(413, "too_large")
        try:
            text = request.body.decode("utf-8")
        except UnicodeDecodeError:
            return None, _bad_request("body is not valid UTF-8")
        try:
            value = json.loads(text)
        except ValueError:
            value = None
        if not isinstance(value, dict):
            return None, _bad_request("body must be a JSON object")
        return value, None

    def _read_data(self, request: FakeRequest) -> tuple[dict[str, Any] | None, str, Answer | None]:
        body, failed = self._read_object(request)
        if failed is not None or body is None:
            return None, "", failed
        if "data" not in body:
            return None, "", _bad_request("body must carry data")
        return body, json.dumps(body["data"], ensure_ascii=False), None

    # -- routes --------------------------------------------------------------------------------

    def handle_brain(self, request: FakeRequest) -> Answer:
        if self.spine.mode != "cloud":
            return _error(404, "cloud_mode_off")
        if request.method != "GET":
            return _method_not_allowed(["GET"])
        answer = self.brain() if callable(self.brain) else self.brain
        if not isinstance(answer, dict):
            return _error(503, "brain_unavailable")
        return 200, answer

    def handle_sessions(self, request: FakeRequest) -> Answer:
        if self.spine.mode != "cloud":
            return _error(404, "cloud_mode_off")
        raw = request.path[len("/hub/sessions") :].split("/")[1:]
        try:
            parts = [urllib.parse.unquote(part, errors="strict") for part in raw]
        except UnicodeDecodeError:
            return _bad_request("bad path encoding")
        padded = [*parts, *([None] * (5 - len(parts)))]
        sid, sub, aid, leaf, mid = padded[:5]
        rest = parts[5:]
        method = request.method
        with self._lock:
            if sid is None:
                if method == "GET":
                    return self._list_sessions(request)
                if method == "POST":
                    return self._create_session(request)
                return _method_not_allowed(["GET", "POST"])
            if not ID.fullmatch(sid):
                return _bad_request(f"session id must match {ID_RULE}")

            if sub is None:
                if method != "GET":
                    return _method_not_allowed(["GET"])
                row = self.sessions.get(sid)
                return (200, {"data": json.loads(row.data)}) if row else _not_found()

            if sub == "meta" and aid is None:
                if method == "GET":
                    row = self.sessions.get(sid)
                    return 200, {"meta": json.loads(row.meta) if row else {}}
                if method == "PATCH":
                    return self._patch_meta(request, sid)
                return _method_not_allowed(["GET", "PATCH"])

            if sub == "events" and aid is None:
                if method == "GET":
                    found = [json.loads(data) for _, s, data in self.events if s == sid]
                    return 200, {"events": found}
                if method == "POST":
                    return self._append_event(request, sid)
                return _method_not_allowed(["GET", "POST"])

            if sub != "agents":
                return _not_found()
            if aid is None:
                if method == "POST":
                    return self._create_agent(request, sid)
                return _method_not_allowed(["POST"])
            if not ID.fullmatch(aid):
                return _bad_request(f"agent id must match {ID_RULE}")

            if leaf is None:
                if method == "GET":
                    data = self.agents.get((sid, aid))
                    return (200, {"data": json.loads(data)}) if data is not None else _not_found()
                if method == "PUT":
                    return self._update_agent(request, sid, aid)
                return _method_not_allowed(["GET", "PUT"])

            if leaf != "messages" or rest:
                return _not_found()
            if mid is None:
                if method == "GET":
                    return self._list_messages(request, sid, aid)
                if method == "POST":
                    return self._create_message(request, sid, aid)
                return _method_not_allowed(["GET", "POST"])
            if not MESSAGE_ID.fullmatch(mid):
                return _bad_request("message id must be a non-negative integer")
            key = (sid, aid, int(mid))
            if method == "GET":
                data = self.messages.get(key)
                return (200, {"data": json.loads(data)}) if data is not None else _not_found()
            if method == "PUT":
                return self._update_message(request, key)
            return _method_not_allowed(["GET", "PUT"])

    def _list_sessions(self, request: FakeRequest) -> Answer:
        limit = _int_param(request.query, "limit", DEFAULT_SESSIONS_LIMIT)
        if limit is None or not 1 <= limit <= MAX_SESSIONS_LIMIT:
            return _bad_request(f"limit must be an integer from 1 to {MAX_SESSIONS_LIMIT}")
        rows = sorted(self.sessions.items(), key=lambda item: item[1].rev, reverse=True)[:limit]
        return 200, {
            "sessions": [
                {
                    "session_id": sid,
                    "created_at": row.created_at,
                    "updated_at": row.updated_at,
                    "meta": json.loads(row.meta),
                    "message_count": sum(1 for key in self.messages if key[0] == sid),
                }
                for sid, row in rows
            ]
        }

    def _create_session(self, request: FakeRequest) -> Answer:
        body, data, failed = self._read_data(request)
        if failed is not None or body is None:
            return failed  # type: ignore[return-value]
        sid = body.get("session_id")
        if not isinstance(sid, str) or not ID.fullmatch(sid):
            return _bad_request(f"session_id must match {ID_RULE}")
        if sid in self.sessions:
            return _error(409, "exists")
        now = self.now_iso()
        self.sessions[sid] = StoredSession(data, "{}", now, now, self._next_rev())
        return _ok(201)

    def _patch_meta(self, request: FakeRequest, sid: str) -> Answer:
        body, failed = self._read_object(request)
        if failed is not None or body is None:
            return failed  # type: ignore[return-value]
        patch = body.get("meta")
        if not isinstance(patch, dict):
            return _bad_request('body must be {"meta": {...}}')
        row = self.sessions.get(sid)
        current = json.loads(row.meta) if row else {}
        merged = {**(current if isinstance(current, dict) else {}), **patch}
        self._upsert(sid, self.now_iso(), json.dumps(merged, ensure_ascii=False))
        return 200, {"meta": merged}

    def _append_event(self, request: FakeRequest, sid: str) -> Answer:
        body, data, failed = self._read_data(request)
        if failed is not None or body is None:
            return failed  # type: ignore[return-value]
        self._upsert(sid, self.now_iso())
        self._seq += 1
        self.events.append((self._seq, sid, data))
        return _ok(201)

    def _create_agent(self, request: FakeRequest, sid: str) -> Answer:
        body, data, failed = self._read_data(request)
        if failed is not None or body is None:
            return failed  # type: ignore[return-value]
        aid = body.get("agent_id")
        if not isinstance(aid, str) or not ID.fullmatch(aid):
            return _bad_request(f"agent_id must match {ID_RULE}")
        if sid not in self.sessions:
            return _not_found()
        if (sid, aid) in self.agents:
            return _error(409, "exists")
        self.agents[(sid, aid)] = data
        self._touch(sid, self.now_iso())
        return _ok(201)

    def _update_agent(self, request: FakeRequest, sid: str, aid: str) -> Answer:
        body, data, failed = self._read_data(request)
        if failed is not None or body is None:
            return failed  # type: ignore[return-value]
        if (sid, aid) not in self.agents:
            return _not_found()
        self.agents[(sid, aid)] = data
        self._touch(sid, self.now_iso())
        return _ok()

    def _create_message(self, request: FakeRequest, sid: str, aid: str) -> Answer:
        body, data, failed = self._read_data(request)
        if failed is not None or body is None:
            return failed  # type: ignore[return-value]
        mid = body.get("message_id")
        if isinstance(mid, bool) or not isinstance(mid, int) or not 0 <= mid <= MAX_SAFE_INTEGER:
            return _bad_request("message_id must be a non-negative integer")
        if (sid, aid) not in self.agents:
            return _not_found()
        if (sid, aid, mid) in self.messages:
            return _error(409, "exists")
        self.messages[(sid, aid, mid)] = data
        self._touch(sid, self.now_iso())
        return _ok(201)

    def _update_message(self, request: FakeRequest, key: tuple[str, str, int]) -> Answer:
        body, data, failed = self._read_data(request)
        if failed is not None or body is None:
            return failed  # type: ignore[return-value]
        if key not in self.messages:
            return _not_found()
        self.messages[key] = data
        self._touch(key[0], self.now_iso())
        return _ok()

    def _list_messages(self, request: FakeRequest, sid: str, aid: str) -> Answer:
        offset = _int_param(request.query, "offset", 0)
        limit = _int_param(request.query, "limit", MAX_MESSAGES)
        if offset is None:
            return _bad_request("offset must be a non-negative integer")
        if limit is None:
            return _bad_request("limit must be a non-negative integer")
        if (sid, aid) not in self.agents:
            return _not_found()
        ids = sorted(key[2] for key in self.messages if key[0] == sid and key[1] == aid)
        page = ids[offset : offset + min(limit, MAX_MESSAGES)]
        return 200, {"messages": [json.loads(self.messages[(sid, aid, mid)]) for mid in page]}


def install_cloud_routes(spine: FakeSpine, *, brain: BrainAnswer = None) -> FakeCloud:
    """Add ``/hub/sessions/**`` and ``/hub/brain`` to ``spine`` (every method, behind the hub
    token) and return the tables they keep."""
    cloud = FakeCloud(spine=spine, brain=brain)
    for method in ("GET", "POST", "PUT", "PATCH", "DELETE"):
        spine.route(method, r"/hub/sessions(/.*)?", cloud.handle_sessions)
        spine.route(method, r"/hub/brain", cloud.handle_brain)
    return cloud
