"""``build_agent``: the one place a tau agent is assembled.

Config → model for a role → tools from entry points (tier-checked) → persona hook → tier gate →
optional session store. No hub assumptions: no network of its own, no launchd, no globals, so
it runs in a plain script with ``FakeModel``. :class:`TauAgent` turns the Strands stream into
channel-friendly :data:`TurnEvent` values.
"""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import AsyncIterator, Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime

from strands import Agent
from strands.hooks import MessageAddedEvent
from strands.models.model import Model
from strands.session import RepositorySessionManager
from strands.types.agent import Limits
from strands.types.content import Message
from strands.types.tools import AgentTool

from tau_core.approval import Approver, AutoRejectApprover, Exemption, TierGate, TierHook
from tau_core.config import Config
from tau_core.events import AgentEvent, EventBus
from tau_core.models import resolve_model
from tau_core.persona import ContextSource, PersonaHook, PersonaLoader, default_context_factory
from tau_core.plugins import discover_tools
from tau_core.sessions import SessionStore, new_session_id
from tau_core.tiers import ToolCatalog, UntieredToolError

logger = logging.getLogger(__name__)

AGENT_ID = "tau"
TITLE_LIMIT = 60


@dataclass
class TextDelta:
    text: str


@dataclass
class ToolUseStarted:
    tool_use_id: str
    tool: str
    tier: int | None


@dataclass
class ToolFinished:
    tool_use_id: str
    tool: str
    status: str
    summary: str
    approval: str | None


@dataclass
class Notice:
    text: str


@dataclass
class TurnEnd:
    stop_reason: str


TurnEvent = TextDelta | ToolUseStarted | ToolFinished | Notice | TurnEnd


def turn_limit_text(n: int) -> str:
    return (
        f"Bu turda araç çağrısı sınırına ulaştım ({n} tur). "
        "Durdum; devam etmemi isterseniz söyleyin."
    )


def model_error_text(exc: BaseException) -> str:
    detail = " ".join(str(exc).split())[:160].rstrip(". ") or type(exc).__name__
    return f"Model çağrısı başarısız oldu: {detail}. Ayrıntı günlükte."


@dataclass
class TauAgent:
    agent: Agent
    config: Config
    events: EventBus
    session_id: str
    catalog: ToolCatalog
    store: SessionStore | None
    gate: TierGate
    _unsubscribe_store: Callable[[], None] | None = field(default=None, repr=False)

    @property
    def messages(self) -> list[Message]:
        return self.agent.messages

    def close(self) -> None:
        """Stop recording this agent's events into its store (call before replacing it)."""
        if self._unsubscribe_store is not None:
            self._unsubscribe_store()
            self._unsubscribe_store = None

    def _emit(self, kind: str, data: dict) -> None:
        self.events.emit(AgentEvent.create(kind, data, session_id=self.session_id))

    def _write_title(self, prompt: str) -> None:
        if self.store is None:
            return
        try:
            if not self.store.read_meta(self.session_id).get("title"):
                title = " ".join(prompt.split())[:TITLE_LIMIT]
                if title:
                    self.store.write_meta(self.session_id, title=title)
        except Exception:
            logger.exception("could not write the session title for %s", self.session_id)

    async def _close_dangling_turn(self, text: str) -> None:
        """After a failed model call, end the history with an assistant message.

        Otherwise the next turn would send two user messages in a row, which some providers
        reject. The message goes through ``MessageAddedEvent`` so the session store sees it.
        """
        messages = self.agent.messages
        if not messages or messages[-1].get("role") != "user":
            return
        message: Message = {"role": "assistant", "content": [{"text": f"({text})"}]}
        try:
            messages.append(message)
            await self.agent.hooks.invoke_callbacks_async(
                MessageAddedEvent(agent=self.agent, message=message)
            )
        except Exception:
            logger.exception("could not close the failed turn in session %s", self.session_id)

    async def stream(self, prompt: str) -> AsyncIterator[TurnEvent]:
        """One user turn. Never raises for model/provider errors: they become a ``Notice``."""
        finished: deque[AgentEvent] = deque()

        def on_event(event: AgentEvent) -> None:
            if event.kind == "tool_call" and event.session_id == self.session_id:
                finished.append(event)

        def drain() -> list[ToolFinished]:
            out = []
            while finished:
                data = finished.popleft().data
                out.append(
                    ToolFinished(
                        tool_use_id=str(data.get("tool_use_id", "")),
                        tool=str(data.get("tool", "")),
                        status=str(data.get("status", "")),
                        summary=str(data.get("result_summary", "")),
                        approval=data.get("approval"),
                    )
                )
            return out

        unsubscribe = self.events.subscribe(on_event)
        started: set[str] = set()
        stop_reason = "end_turn"
        max_turns = self.config.agent.max_turns
        try:
            self._write_title(prompt)
            try:
                stream = self.agent.stream_async(prompt, limits=Limits(turns=max_turns))
                async for event in stream:
                    for item in drain():
                        yield item
                    if not isinstance(event, dict):
                        continue
                    if "current_tool_use" in event:
                        tool_use = event["current_tool_use"] or {}
                        tool_use_id = str(tool_use.get("toolUseId") or "")
                        name = str(tool_use.get("name") or "")
                        if tool_use_id and name and tool_use_id not in started:
                            started.add(tool_use_id)
                            tier = self.catalog.tier(name)
                            yield ToolUseStarted(
                                tool_use_id=tool_use_id,
                                tool=name,
                                tier=int(tier) if tier is not None else None,
                            )
                    elif "data" in event:
                        if event["data"]:
                            yield TextDelta(text=str(event["data"]))
                    elif "result" in event:
                        stop_reason = str(getattr(event["result"], "stop_reason", stop_reason))
                for item in drain():
                    yield item
            except Exception as exc:
                for item in drain():
                    yield item
                logger.exception("model call failed in session %s", self.session_id)
                self._emit("error", {"message": str(exc)[:500], "where": "model"})
                text = model_error_text(exc)
                await self._close_dangling_turn(text)
                yield Notice(text=text)
                stop_reason = "error"
            if stop_reason == "limit_turns":
                self._emit("turn_limit", {"max_turns": max_turns})
                yield Notice(text=turn_limit_text(max_turns))
            yield TurnEnd(stop_reason=stop_reason)
        finally:
            unsubscribe()

    async def ask(self, prompt: str) -> str:
        """Run one turn and return only the reply text."""
        parts: list[str] = []
        async for event in self.stream(prompt):
            if isinstance(event, TextDelta):
                parts.append(event.text)
        return "".join(parts)


def build_agent(
    profile: str | None = None,
    *,
    config: Config | None = None,
    role: str = "brain",
    model: Model | None = None,
    tools: Iterable[AgentTool] | None = None,
    approver: Approver | None = None,
    session_id: str | None = None,
    session_store: SessionStore | None = None,
    events: EventBus | None = None,
    persona: PersonaLoader | None = None,
    context_sources: Iterable[ContextSource] = (),
    channel: str = "terminal",
    clock: Callable[[], datetime] | None = None,
    exemptions: Iterable[Exemption] = (),
) -> TauAgent:
    """Assemble a tau agent. Raises ``ConfigError``/``MissingCredentials`` before any model call."""
    config = config or Config.load()
    if profile:
        config = config.with_overrides(profile=profile)
    model = model or resolve_model(role, config)

    catalog = ToolCatalog()
    if tools is not None:
        catalog.extend(tools)  # an untiered tool passed explicitly is a programming error
    else:
        for tool in discover_tools():
            try:
                catalog.add(tool)
            except UntieredToolError as exc:
                logger.warning(
                    "skipping tool from %s: %s", getattr(tool, "tau_distribution", "?"), exc
                )

    events = events or EventBus()
    session_id = session_id or new_session_id(clock)
    approver = approver or AutoRejectApprover()
    persona = persona or PersonaLoader(config.persona_dir)
    context_factory = default_context_factory(config, clock=clock, sources=context_sources)
    system_prompt = persona.build_system_prompt(context_factory())  # fails early without persona

    gate = TierGate(
        catalog, approver, events, session_id=session_id, channel=channel, exemptions=exemptions
    )
    session_manager = (
        RepositorySessionManager(session_id=session_id, session_repository=session_store)
        if session_store is not None
        else None
    )
    agent = Agent(
        model=model,
        tools=catalog.tools(),
        system_prompt=system_prompt,
        hooks=[PersonaHook(persona, context_factory), TierHook(gate)],
        session_manager=session_manager,
        callback_handler=None,
        agent_id=AGENT_ID,
        name="tau",
    )

    unsubscribe = None
    if session_store is not None:
        session_store.write_meta(session_id, channel=channel, profile=config.profile)
        unsubscribe = events.subscribe(session_store.event_sink(session_id))

    return TauAgent(
        agent=agent,
        config=config,
        events=events,
        session_id=session_id,
        catalog=catalog,
        store=session_store,
        gate=gate,
        _unsubscribe_store=unsubscribe,
    )
