"""Turns inside the hub: open sessions, their agents, the event buffer and the web approver.

Every open session has one ``TauAgent`` built with ``channel="web"`` (ADR 0015 §2), the hub's
own guard and a :class:`WebApprover`. A turn runs as an asyncio task that belongs to the hub,
not to the browser: its events are framed by the turn protocol into a buffer, and any number
of readers stream from it (``after=<seq>`` re-attaches). A finished turn stays readable for
``turn_keep`` seconds; an idle session is closed after the same time, which releases its lock
so the TUI or Telegram can open it again.

Nothing here approves on its own. An approval waits for :meth:`Runtime.decide`, which the
HTTP layer calls only for a paired device; the gate's timeout rejects one nobody answers, and
a guard lock rejects every pending one and cancels the running turns (ADR 0008 decision 10).
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any

from tau_core import (
    AgentEvent,
    ApprovalRequest,
    Config,
    Decision,
    EventBus,
    Guard,
    SessionStore,
    TauAgent,
    build_agent,
    stored_role,
)
from tau_core.agent import AGENT_ID
from tau_core.sessions import new_session_id
from tau_core.turn_protocol import (
    approval_body,
    approval_decided,
    error_body,
    frame,
    guard_body,
    history_blocks,
    turn_event_body,
    turn_started,
)

logger = logging.getLogger(__name__)

CHANNEL = "web"

OWNER_CHANNELS = frozenset({"web", "tui", "terminal", "telegram", "ask"})
"""Sessions the web app may continue: the owner's own conversations. Network, visitor, sub-tau
and scheduled sessions hold text other people or other personas wrote; they are shown, never
continued here with the main tau's tools."""


class TurnError(Exception):
    """A request the runtime refuses; ``status`` is the HTTP status the API answers with."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


@dataclass
class Turn:
    """One turn's framed events, readable while it runs and for a while after."""

    id: str
    session_id: str
    events: list[dict[str, Any]] = field(default_factory=list)
    done: bool = False
    finished_at: float | None = None
    _changed: asyncio.Condition = field(default_factory=asyncio.Condition)

    async def add(self, body: dict[str, Any]) -> None:
        async with self._changed:
            self.events.append(frame(body, len(self.events)))
            self._changed.notify_all()

    async def finish(self, now: float) -> None:
        async with self._changed:
            self.done = True
            self.finished_at = now
            self._changed.notify_all()

    async def read(self, after: int = -1) -> AsyncIterator[dict[str, Any]]:
        """The events with ``seq > after``, then every new one until the turn is done."""
        position = max(after + 1, 0)
        while True:
            async with self._changed:
                while position >= len(self.events) and not self.done:
                    await self._changed.wait()
                pending = self.events[position:]
                finished = self.done
            for event in pending:
                yield event
            position += len(pending)
            if finished and position >= len(self.events):
                return


class WebApprover:
    """Approves tier-2 calls through the web app: an ``approval`` event, then the answer of a
    paired device through :meth:`Runtime.decide`. Never auto-approves."""

    name = CHANNEL
    refusal_note = "The owner can approve it in the web app."

    def __init__(self, runtime: Runtime, session_id: str, timeout_seconds: float) -> None:
        self.runtime = runtime
        self.session_id = session_id
        self.timeout_seconds = timeout_seconds

    async def decide(self, request: ApprovalRequest) -> Decision:
        return await self.runtime.ask(self.session_id, request, self.timeout_seconds)


@dataclass
class Pending:
    request: ApprovalRequest
    session_id: str
    future: asyncio.Future[Decision]


@dataclass
class OpenSession:
    session_id: str
    agent: TauAgent
    client_id: str
    events: EventBus
    turn: Turn | None = None
    task: asyncio.Task[None] | None = None
    last_active: float = 0.0
    unsubscribe: Callable[[], None] | None = None

    @property
    def running(self) -> bool:
        return self.task is not None and not self.task.done()


AgentFactory = Callable[..., TauAgent]


class Runtime:
    """The web channel's sessions and turns. One per web service, on the hub's event loop."""

    def __init__(
        self,
        config: Config,
        store: SessionStore,
        *,
        guard: Callable[[], Any],
        approval_timeout: float,
        turn_keep: float,
        agent_factory: AgentFactory = build_agent,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config
        self.store = store
        self._guard = guard
        """Returns the guard to build with: the hub's guard service, else ``DISCOVER``."""
        self.approval_timeout = approval_timeout
        self.turn_keep = turn_keep
        self._factory = agent_factory
        self._clock = clock
        self.sessions: dict[str, OpenSession] = {}
        self.turns: dict[str, Turn] = {}
        self.pending: dict[str, Pending] = {}
        self._loop: asyncio.AbstractEventLoop | None = None

    # -- sessions ------------------------------------------------------------------------------

    def _owner_session(self, session_id: str) -> None:
        meta = self.store.read_meta(session_id)
        channel = str(meta.get("channel") or "")
        if channel and channel not in OWNER_CHANNELS:
            raise TurnError(
                409,
                f"This is a {channel} session: it can be read here, but not continued.",
            )

    def _open(self, session_id: str | None, client_id: str) -> OpenSession:
        if session_id is not None:
            self._owner_session(session_id)
            current = self.sessions.get(session_id)
            if current is not None:
                if current.client_id == client_id or current.running:
                    return current
                self._close(current)  # another device takes over: rebuild with its client id
        events = EventBus()
        role = stored_role(self.store, session_id, self.config) if session_id else None
        session_id = session_id or new_session_id()
        approver = WebApprover(self, session_id, self.approval_timeout)
        try:
            agent = self._factory(
                config=self.config,
                approver=approver,
                session_store=self.store,
                session_id=session_id,
                channel=CHANNEL,
                events=events,
                guard=self._guard(),
                client_id=client_id,
                **({"role": role} if role else {}),
            )
        except Exception as exc:
            raise TurnError(409, str(exc)) from exc
        opened = OpenSession(
            session_id=agent.session_id,
            agent=agent,
            client_id=client_id,
            events=events,
            last_active=self._clock(),
        )
        opened.unsubscribe = events.subscribe(lambda event: self._on_agent_event(opened, event))
        self.sessions[agent.session_id] = opened
        return opened

    def _close(self, opened: OpenSession) -> None:
        if opened.unsubscribe is not None:
            opened.unsubscribe()
        opened.agent.close()
        self.sessions.pop(opened.session_id, None)

    def _on_agent_event(self, opened: OpenSession, event: AgentEvent) -> None:
        """Guard events of this session's gate become ``guard`` events of its turn (from any
        thread: the guard reports a step-up's progress from its own)."""
        turn, loop = opened.turn, self._loop
        if event.kind != "guard" or turn is None or turn.done or loop is None:
            return
        body = guard_body(event.data)
        loop.call_soon_threadsafe(lambda: loop.create_task(turn.add(body)))

    # -- turns ---------------------------------------------------------------------------------

    async def start(self, session_id: str | None, text: str, client_id: str) -> Turn:
        if not isinstance(text, str) or not text.strip():
            raise TurnError(400, "A turn needs some text.")
        self._loop = asyncio.get_running_loop()
        opened = self._open(session_id, client_id)
        if opened.running:
            raise TurnError(409, "A turn is already running in this session.")
        turn = Turn(id=f"t-{secrets.token_hex(8)}", session_id=opened.session_id)
        self.turns[turn.id] = turn
        opened.turn = turn
        opened.last_active = self._clock()
        await turn.add(turn_started(turn.id, opened.session_id))
        opened.task = asyncio.get_running_loop().create_task(
            self._run(opened, turn, text), name=f"tau-web-turn-{turn.id}"
        )
        return turn

    async def _run(self, opened: OpenSession, turn: Turn, text: str) -> None:
        try:
            async for event in opened.agent.stream(text):
                await turn.add(turn_event_body(event))
        except asyncio.CancelledError:
            await turn.add(error_body("The web service stopped."))
            await turn.add({"type": "end", "stop_reason": "cancelled"})
            raise
        except Exception as exc:
            logger.exception("web: turn %s failed", turn.id)
            await turn.add(error_body(f"The turn failed: {type(exc).__name__}"))
            await turn.add({"type": "end", "stop_reason": "error"})
        finally:
            opened.last_active = self._clock()
            await turn.finish(self._clock())

    def turn(self, turn_id: str) -> Turn:
        turn = self.turns.get(turn_id)
        if turn is None:
            raise TurnError(404, "No such turn (it may have ended a while ago).")
        return turn

    def cancel(self, turn_id: str) -> None:
        turn = self.turn(turn_id)
        opened = self.sessions.get(turn.session_id)
        if opened is not None and opened.turn is turn and opened.running:
            opened.agent.cancel()

    # -- approvals -----------------------------------------------------------------------------

    async def ask(self, session_id: str, request: ApprovalRequest, timeout: float) -> Decision:
        """What :class:`WebApprover` awaits: publish the request, wait for a device's answer."""
        future: asyncio.Future[Decision] = asyncio.get_running_loop().create_future()
        self.pending[request.request_id] = Pending(request, session_id, future)
        opened = self.sessions.get(session_id)
        turn = opened.turn if opened is not None else None
        if turn is not None:
            expires = time.time() + timeout
            await turn.add(approval_body(request, expires_at=round(expires, 3)))
        decision = Decision.TIMEOUT
        try:
            decision = await future
            return decision
        finally:
            self.pending.pop(request.request_id, None)
            if turn is not None and not turn.done:
                await turn.add(approval_decided(request.request_id, decision))

    def decide(self, request_id: str, decision: str) -> None:
        """A paired device's answer: ``approved`` or ``rejected``."""
        if decision not in (Decision.APPROVED.value, Decision.REJECTED.value):
            raise TurnError(400, "decision must be approved or rejected")
        pending = self.pending.get(request_id)
        if pending is None or pending.future.done():
            raise TurnError(409, "This approval was already decided or has expired.")
        pending.future.set_result(Decision(decision))

    def on_lock(self) -> None:
        """The guard locked: reject every pending approval and cancel the running turns."""
        for pending in list(self.pending.values()):
            if not pending.future.done():
                pending.future.set_result(Decision.REJECTED)
        for opened in list(self.sessions.values()):
            if opened.running:
                opened.agent.cancel()

    # -- reading -------------------------------------------------------------------------------

    def list_sessions(self, limit: int = 50) -> list[dict[str, Any]]:
        open_ids = set(self.sessions)
        return [
            {
                "id": summary.session_id,
                "title": summary.title,
                "channel": summary.channel,
                "created_at": summary.created_at,
                "updated_at": summary.updated_at,
                "message_count": summary.message_count,
                "open_here": summary.session_id in open_ids,
                "continuable": (summary.channel or CHANNEL) in OWNER_CHANNELS,
            }
            for summary in self.store.list_sessions(limit=limit)
        ]

    def history(self, session_id: str) -> dict[str, Any]:
        if self.store.read_session(session_id) is None:
            raise TurnError(404, "No such session.")
        meta = self.store.read_meta(session_id)
        messages = self.store.list_messages(session_id, AGENT_ID)
        blocks = history_blocks(messages, self.store.read_events(session_id))
        channel = str(meta.get("channel") or "")
        session = {
            "id": session_id,
            "title": meta.get("title") or "",
            "channel": channel,
            "continuable": (channel or CHANNEL) in OWNER_CHANNELS,
        }
        return {"session": session, "blocks": blocks}

    # -- housekeeping --------------------------------------------------------------------------

    def sweep(self) -> None:
        """Forget finished turns and close idle sessions after ``turn_keep`` seconds."""
        now = self._clock()
        for turn_id, turn in list(self.turns.items()):
            if (
                turn.done
                and turn.finished_at is not None
                and now - turn.finished_at > self.turn_keep
            ):
                del self.turns[turn_id]
        for opened in list(self.sessions.values()):
            waiting = any(p.session_id == opened.session_id for p in self.pending.values())
            if not opened.running and not waiting and now - opened.last_active > self.turn_keep:
                self._close(opened)

    async def close(self) -> None:
        """Stop every turn and release every session (the service stops)."""
        self.on_lock()
        tasks = [opened.task for opened in self.sessions.values() if opened.running]
        for task in tasks:
            if task is not None:
                task.cancel()
        for task in tasks:
            if task is not None:
                try:
                    await asyncio.wait_for(task, timeout=5)
                except (asyncio.CancelledError, TimeoutError, Exception):
                    pass
        for opened in list(self.sessions.values()):
            self._close(opened)

    def status(self) -> dict[str, Any]:
        return {
            "open_sessions": len(self.sessions),
            "turns": sum(1 for opened in self.sessions.values() if opened.running),
            "approvals_pending": len(self.pending),
        }


def is_guard(value: Any) -> bool:
    return isinstance(value, Guard)
