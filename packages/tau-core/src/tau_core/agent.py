"""``build_agent``: the one place a tau agent is assembled.

Config → model for a role → tools from entry points (tier-checked) → persona hook → tier gate →
optional session store. No hub assumptions: no network of its own, no launchd, no globals, so
it runs in a plain script with ``FakeModel``. :class:`TauAgent` turns the Strands stream into
channel-friendly :data:`TurnEvent` values.

Stream contract (one ``stream(prompt)`` call is one user turn):

- Events come from the SDK's plain-dict stream through :func:`to_turn_event`, plus the
  ``ToolFinished`` events the tier gate records. A turn always ends with ``TurnEnd``.
- tau never appends to ``agent.messages`` by hand. When a turn cannot finish (a model error,
  the loop guard, a cancel, a context overflow, a refused interrupt, a crash before the reply
  or a tool result was stored) the history ends on a *dangling* message: a ``user`` message,
  or an ``assistant`` message with a ``toolUse`` and no result. The *next* ``stream()`` sends
  a two-message prompt (an ``assistant`` repair notice, then the new ``user`` message) so the
  SDK appends both through its own chokepoint (tracking ids, ``MessageAddedEvent``, session
  store); for a dangling ``toolUse`` the SDK first inserts its own "Tool was interrupted."
  result, so roles keep alternating.
- Calls are serialized per event loop with an ``asyncio.Lock``; a second caller from another
  loop that hits the SDK's own concurrency guard gets a ``busy`` turn and no history change.
- A turn never leaves the SDK in interrupt state, and a session restored in that state is
  cleared before its first turn.
- With an owner guard (ADR 0008) a turn is admitted inside the lock before any history, prompt
  or SDK work; a refused turn yields a ``Notice`` and ``TurnEnd("locked")`` and changes nothing.
"""

from __future__ import annotations

import asyncio
import copy
import logging
import secrets
from collections import deque
from collections.abc import AsyncIterator, Callable, Iterable
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any

from strands import Agent
from strands.agent.conversation_manager import (
    ConversationManager,
    SlidingWindowConversationManager,
    SummarizingConversationManager,
)
from strands.hooks import BeforeToolCallEvent, HookOrder, HookProvider
from strands.models.model import Model
from strands.session import RepositorySessionManager
from strands.tools.executors import SequentialToolExecutor
from strands.types.agent import Limits
from strands.types.content import Message
from strands.types.exceptions import (
    ConcurrencyException,
    ContextWindowOverflowException,
    MaxTokensReachedException,
)
from strands.types.tools import AgentTool

from tau_core import registry
from tau_core.approval import Approver, AutoRejectApprover, Exemption, TierGate, TierHook
from tau_core.config import AgentConfig, Config, ConfigError
from tau_core.events import AgentEvent, EventBus
from tau_core.guard import (
    DISCOVER,
    Guard,
    GuardLocked,
    GuardTurn,
    admission_reason,
    admit_turn,
    process_client_id,
    resolve_guard,
)
from tau_core.i18n import DEFAULT_LANGUAGE, t
from tau_core.models import ModelNotice, resolve_model
from tau_core.persona import ContextSource, PersonaHook, PersonaLoader, default_context_factory
from tau_core.plugins import discover_tools
from tau_core.sessions import SessionStore, new_session_id
from tau_core.tiers import Tier, ToolCatalog, UntieredToolError, tier_of

logger = logging.getLogger(__name__)

AGENT_ID = "tau"
TITLE_LIMIT = 60

STOP_REASONS = (
    "end_turn",
    "limit_turns",
    "limit_total_tokens",
    "max_tokens",
    "cancelled",
    "interrupt",
    "error",
    "busy",
    "locked",
)
"""Every value ``TurnEnd.stop_reason`` can carry; see :class:`TurnEnd`."""


@dataclass
class TextDelta:
    text: str


@dataclass
class ReasoningDelta:
    """A piece of the model's extended thinking (SDK key ``reasoningText``)."""

    text: str


@dataclass
class ToolUseStarted:
    tool_use_id: str
    tool: str
    tier: int | None


@dataclass
class ToolInput:
    """The complete input of a tool call, once the model has finished writing it.

    It comes from the SDK's ``message`` event for the model's reply, after the call's
    :class:`ToolUseStarted` (which arrives while the input still streams) and before the tool
    runs or asks for approval. ``input`` is what the SDK parsed, normally a ``dict``.
    """

    tool_use_id: str
    tool: str
    input: Any


@dataclass
class ToolProgress:
    """Progress a streaming tool reports while it runs (SDK key ``tool_stream_event``)."""

    tool_use_id: str
    tool: str
    text: str


@dataclass
class ToolFinished:
    tool_use_id: str
    tool: str
    status: str
    summary: str
    approval: str | None


@dataclass
class Throttled:
    """The provider throttled the call; the SDK retries after ``delay_seconds``."""

    delay_seconds: float


@dataclass
class Notice:
    text: str


@dataclass
class TurnEnd:
    """The last event of every turn. ``stop_reason`` is one of :data:`STOP_REASONS`:

    - ``end_turn``: the model finished its reply.
    - ``limit_turns``: ``[agent] max_turns`` model calls were used (notice, repaired next turn).
    - ``limit_total_tokens``: ``[agent] max_total_tokens`` was reached (same handling).
    - ``max_tokens``: the reply hit the provider's output limit; the partial reply is kept.
    - ``cancelled``: :meth:`TauAgent.cancel` stopped the turn (notice, repaired next turn).
    - ``interrupt``: a hook kept interrupting after ``[agent] max_turns`` refusals; the SDK's
      interrupt state is cleared and the turn is repaired next time.
    - ``error``: the model call, the context window or an interrupt failed (notice, repaired
      next turn when the history was left dangling).
    - ``busy``: another invocation held the SDK's concurrency guard; nothing ran.
    - ``locked``: the owner guard refused the turn (notice ``guard.refused.<reason>``, a
      ``guard`` event); nothing was appended and no model was called.

    ``[agent] max_turns`` and ``max_total_tokens`` bound the whole turn: the SDK's ``Limits``
    are per invocation, so the continuation that answers an interrupt gets what is left.
    """

    stop_reason: str


TurnEvent = (
    TextDelta
    | ReasoningDelta
    | ToolUseStarted
    | ToolInput
    | ToolProgress
    | ToolFinished
    | Throttled
    | Notice
    | TurnEnd
)


def turn_limit_text(n: int, language: str = DEFAULT_LANGUAGE) -> str:
    """The notice shown (and kept in the history) when the loop guard trips."""
    return t("notice.turn_limit", language, n=n)


def model_notice_of(exc: BaseException) -> ModelNotice | None:
    """The :class:`ModelNotice` behind a failed turn, if there is one: the SDK wraps a model's
    exception in ``EventLoopException`` (``original_exception``, ``__cause__``)."""
    current: BaseException | None = exc
    for _ in range(8):
        if current is None:
            return None
        if isinstance(current, ModelNotice):
            return current
        current = getattr(current, "original_exception", None) or current.__cause__
    return None


def model_error_text(exc: BaseException, language: str = DEFAULT_LANGUAGE) -> str:
    """The notice for a failed model call: a :class:`ModelNotice`'s own sentence (a spent
    budget), else a short detail with the rest in the log."""
    notice = model_notice_of(exc)
    if notice is not None:
        return notice.notice(language)
    detail = " ".join(str(exc).split())[:160].rstrip(". ") or type(exc).__name__
    return t("notice.model_error", language, detail=detail)


def to_turn_event(event: dict[str, Any]) -> TurnEvent | None:
    """Map one plain-dict event of ``Agent.stream_async`` to a turn event, or ``None``.

    Pure: it never looks at the agent. ``current_tool_use`` events repeat for every delta
    of a tool call, so de-duplicating them by ``tool_use_id`` (and filling ``tier``) is the
    caller's job. ``force_stop`` is logged at warning level and yields nothing; the exception
    that follows it carries the failure.
    """
    if "current_tool_use" in event:
        tool_use = event["current_tool_use"] or {}
        tool_use_id = str(tool_use.get("toolUseId") or "")
        name = str(tool_use.get("name") or "")
        if not tool_use_id or not name:
            return None
        return ToolUseStarted(tool_use_id=tool_use_id, tool=name, tier=None)
    if "data" in event:
        text = event["data"]
        return TextDelta(text=str(text)) if text else None
    if "reasoningText" in event:
        text = event["reasoningText"]
        return ReasoningDelta(text=str(text)) if text else None
    if "tool_stream_event" in event:
        payload = event["tool_stream_event"] or {}
        tool_use = payload.get("tool_use") or {}
        return ToolProgress(
            tool_use_id=str(tool_use.get("toolUseId") or ""),
            tool=str(tool_use.get("name") or ""),
            text=str(payload.get("data", "")),
        )
    if "event_loop_throttled_delay" in event:
        try:
            delay = float(event["event_loop_throttled_delay"])
        except (TypeError, ValueError):
            delay = 0.0
        return Throttled(delay_seconds=delay)
    if event.get("force_stop"):
        logger.warning("agent loop force-stopped: %s", event.get("force_stop_reason", "?"))
        return None
    return None


def tool_inputs_of(event: dict[str, Any]) -> list[ToolInput]:
    """The :class:`ToolInput` of every tool use in a ``message`` event of ``stream_async``.

    Pure, like :func:`to_turn_event`. Only the model's own reply counts (role ``assistant``);
    the tool-result message the SDK also announces as ``message`` yields nothing.
    """
    message = event.get("message")
    if not isinstance(message, dict) or message.get("role") != "assistant":
        return []
    found = []
    for block in message.get("content") or []:
        use = block.get("toolUse") if isinstance(block, dict) else None
        if not isinstance(use, dict):
            continue
        tool_use_id = str(use.get("toolUseId") or "")
        name = str(use.get("name") or "")
        if tool_use_id and name:
            found.append(ToolInput(tool_use_id=tool_use_id, tool=name, input=use.get("input")))
    return found


def _repair_message(text: str) -> Message:
    return {"role": "assistant", "content": [{"text": f"({text})"}]}


def dangling(message: Message) -> bool:
    """A history ending on this message needs a repair before the next user prompt.

    Either a ``user`` message (no reply was stored: failed, cancelled, limited or crash-cut
    turn) or an ``assistant`` message with a ``toolUse`` block (the tool result was never
    stored, e.g. the hub died while an approval was pending, or an interrupt was given up).
    Shared with :mod:`tau_core.compaction`, whose summarizer sends the same repair pair.
    """
    role = message.get("role")
    if role == "user":
        return True
    return role == "assistant" and any("toolUse" in block for block in message.get("content", []))


CONTEXT_MANAGERS = {
    "SlidingWindowConversationManager": "sliding",
    "SummarizingConversationManager": "summarize",
}
"""Strands conversation manager class → the ``[agent] context`` value that picks it."""


class SessionContextMismatch(ConfigError):
    """The session was recorded under another ``[agent] context`` value.

    Strands stores the conversation manager's class with the session and refuses to restore
    it under a different one (``ValueError("Invalid conversation manager state.")``), so the
    session can only be resumed with the setting it was recorded with, or left as it is.
    """

    def __init__(self, session_id: str, previous: str | None) -> None:
        self.session_id = session_id
        self.previous = CONTEXT_MANAGERS.get(previous or "", previous)
        back_to = f"set it back to {self.previous}" if self.previous else "set it back"
        super().__init__(
            f"Session {session_id} was recorded with a different [agent] context setting; "
            f"{back_to} or start a new session."
        )


def _usage_of(result: Any) -> tuple[int, int]:
    """``(cycles, total tokens)`` one SDK invocation used, read from its result metrics."""
    metrics = getattr(result, "metrics", None)
    invocation = getattr(metrics, "latest_agent_invocation", None)
    if invocation is None:
        return 0, 0
    try:
        return len(invocation.cycles), int(invocation.usage.get("totalTokens", 0))
    except (AttributeError, TypeError, ValueError):
        return 0, 0


def _interrupt_responses(interrupts: Iterable[Any]) -> list[dict[str, Any]]:
    """The resume prompt that refuses every pending interrupt (see ``strands.types.interrupt``)."""
    return [
        {"interruptResponse": {"interruptId": interrupt.id, "response": {"tau": "rejected"}}}
        for interrupt in interrupts
    ]


@dataclass
class TauAgent:
    agent: Agent
    config: Config
    events: EventBus
    session_id: str
    catalog: ToolCatalog
    store: SessionStore | None
    gate: TierGate
    role: str = "brain"
    """The model role this agent was built for (``/status``, ``/model``); a label when the
    caller passed its own ``model``."""
    channel: str = "terminal"
    """The channel label ``build_agent`` got (admission, session metadata, traces)."""
    guard: Guard | None = None
    """The owner guard that admits every turn (ADR 0008); ``None`` for no guard."""
    client_id: str = field(default_factory=lambda: secrets.token_hex(8))
    """This client's id for the guard: random per process, an audit label, never a claim."""
    _unsubscribe_store: Callable[[], None] | None = field(default=None, repr=False)
    _pending_repair: str | None = field(default=None, repr=False)
    """The notice the next turn prepends as an assistant message when the history ends
    dangling; ``None`` falls back to ``notice.previous_turn_unfinished``. Kept until the SDK
    has appended the repair (a ``busy`` turn appends nothing and leaves it alone); a rebuilt
    agent on the same session takes it over with :meth:`carry_over`."""
    _lock: asyncio.Lock | None = field(default=None, repr=False)
    _lock_loop: asyncio.AbstractEventLoop | None = field(default=None, repr=False)
    _running: bool = field(default=False, repr=False)
    """True while a turn is inside :meth:`_stream_locked`; :meth:`cancel` is a no-op otherwise."""
    _refused: str | None = field(default=None, repr=False)
    """The admission reason of the last refused turn (for :meth:`ask`)."""

    @property
    def messages(self) -> list[Message]:
        return self.agent.messages

    def close(self) -> None:
        """Stop recording this agent's events into its store (call before replacing it)."""
        if self._unsubscribe_store is not None:
            self._unsubscribe_store()
            self._unsubscribe_store = None

    def cancel(self) -> None:
        """Stop the turn in flight at the SDK's next safe point (thread-safe, idempotent).

        The turn ends with ``TurnEnd(stop_reason="cancelled")`` and a notice; the partial reply
        is discarded by the SDK, so the next turn starts with the repair message. A cancel
        while no turn is running is ignored: the SDK only clears its cancel signal when an
        invocation ends, so a stray Esc while idle would otherwise kill the *next* turn.
        """
        if not self._running:
            logger.debug("cancel ignored: no turn is running in session %s", self.session_id)
            return
        self.agent.cancel()

    def _emit(self, kind: str, data: dict) -> None:
        self.events.emit(AgentEvent.create(kind, data, session_id=self.session_id))

    def _stream_lock(self) -> asyncio.Lock:
        # One lock per event loop: ``tau chat`` runs each turn on a fresh loop.
        loop = asyncio.get_running_loop()
        if self._lock is None or self._lock_loop is not loop:
            self._lock = asyncio.Lock()
            self._lock_loop = loop
        return self._lock

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

    def _build_prompt(self, prompt: str, language: str) -> str | list[Message]:
        """The prompt for the SDK: the text, or ``[assistant repair, user text]`` when the
        history ends dangling (see :func:`_dangling`). ``_pending_repair`` is not cleared
        here: it is consumed once the SDK has actually appended the messages."""
        messages = self.agent.messages
        if not messages or not dangling(messages[-1]):
            return prompt
        text = self._pending_repair or t("notice.previous_turn_unfinished", language)
        logger.info("repairing an unfinished turn in session %s", self.session_id)
        return [_repair_message(text), {"role": "user", "content": [{"text": prompt}]}]

    def _limits(self, turns_used: int = 0, tokens_used: int = 0, *, replay: bool = False) -> Limits:
        """The SDK ``Limits`` for one invocation, minus what this turn already used.

        ``replay`` is set for a continuation that answers a tool interrupt: its first cycle
        replays the stored tool uses without a model call, so it gets one extra turn.
        """
        agent_cfg: AgentConfig = self.config.agent
        limits = Limits(turns=max(agent_cfg.max_turns - turns_used, 1) + int(replay))
        if agent_cfg.max_total_tokens is not None:
            limits["total_tokens"] = max(agent_cfg.max_total_tokens - tokens_used, 1)
        return limits

    def _exhausted(self, turns_used: int, tokens_used: int) -> str | None:
        """The stop reason to report when the turn's budget is spent, else ``None``."""
        agent_cfg: AgentConfig = self.config.agent
        if turns_used >= agent_cfg.max_turns:
            return "limit_turns"
        if agent_cfg.max_total_tokens is not None and tokens_used >= agent_cfg.max_total_tokens:
            return "limit_total_tokens"
        return None

    def _clear_interrupt(self, why: str) -> None:
        """Leave the SDK's interrupt state (the only way out short of answering it).

        The history then ends on the assistant ``toolUse`` message the interrupt stopped at,
        which the next turn repairs; the SDK supplies the missing "Tool was interrupted."
        result itself. The version bump makes the session store record the cleared state.
        """
        state = self.agent._interrupt_state
        names = [str(i.name) for i in state.interrupts.values()]
        logger.warning("clearing interrupt state %s in session %s: %s", names, self.session_id, why)
        state.deactivate()

    def _appended_since(self, last_before: Message | None) -> bool:
        """Did the SDK append anything this turn? Decided by identity of the last message,
        not by length: the conversation window may trim older messages in the same run."""
        messages = self.agent.messages
        return bool(messages) and messages[-1] is not last_before

    async def stream(self, prompt: str) -> AsyncIterator[TurnEvent]:
        """One user turn. Never raises for model/provider errors: they become a ``Notice``."""
        async with self._stream_lock():
            self._refused = None
            if self.guard is not None:
                turn = GuardTurn(self.channel, self.session_id, self.client_id)
                admission = await admit_turn(self.guard, turn)
                if not admission.allowed:
                    for event in self._refuse(admission.reason):
                        yield event
                    return
            async for event in self._stream_locked(prompt):
                yield event

    def _refuse(self, reason: str) -> list[TurnEvent]:
        """A turn the guard refused: one ``guard`` event, a notice and ``TurnEnd("locked")``.
        Nothing reaches the history, the session store's messages or the model."""
        reason = admission_reason(reason)
        self._refused = reason
        logger.info("guard refused a turn in session %s: %s", self.session_id, reason)
        self._emit("guard", {"action": "refused", "channel": self.channel, "reason": reason})
        text = t(f"guard.refused.{reason}", self.config.ui.language)
        return [Notice(text=text), TurnEnd(stop_reason="locked")]

    async def _stream_locked(self, prompt: str) -> AsyncIterator[TurnEvent]:
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
        language = self.config.ui.language
        agent_cfg: AgentConfig = self.config.agent
        stop_reason = "end_turn"
        result: Any = None
        repair: str | None = None  # the notice the next turn prepends, if this one dangles
        messages = self.agent.messages
        last_before: Message | None = messages[-1] if messages else None
        self._running = True
        try:
            if self.agent._interrupt_state.activated:
                # A session restored (or left by an older tau) in interrupt state: no channel
                # can answer it, and the SDK refuses every plain prompt until it is cleared.
                self._clear_interrupt("restored in interrupt state")
                text = t("notice.interrupt_refused", language)
                self._emit("error", {"message": "stale interrupt cleared", "where": "interrupt"})
                self._pending_repair = self._pending_repair or text
                yield Notice(text=text)
            sdk_prompt: Any = self._build_prompt(prompt, language)
            limits = self._limits()
            turns_used = 0
            tokens_used = 0
            resumes = 0
            try:
                while True:
                    replay = self.agent._interrupt_state.pending_tool_execution is not None
                    async for event in self.agent.stream_async(sdk_prompt, limits=limits):
                        for item in drain():
                            yield item
                        if not isinstance(event, dict):
                            continue
                        if "result" in event:
                            result = event["result"]
                            stop_reason = str(getattr(result, "stop_reason", stop_reason))
                            continue
                        if isinstance(event.get("message"), dict):
                            for item in tool_inputs_of(event):
                                yield item
                            continue
                        mapped = to_turn_event(event)
                        if mapped is None:
                            continue
                        if isinstance(mapped, ToolUseStarted):
                            if mapped.tool_use_id in started:
                                continue
                            started.add(mapped.tool_use_id)
                            tier = self.catalog.tier(mapped.tool)
                            mapped = replace(mapped, tier=int(tier) if tier is not None else None)
                        yield mapped
                    for item in drain():
                        yield item
                    turns, tokens = _usage_of(result)
                    turns_used += max(turns - int(replay), 0)
                    tokens_used += tokens
                    if stop_reason != "interrupt":
                        break
                    # A hook asked for an answer this channel cannot give: refuse it and let
                    # the loop finish, so the agent never stays in interrupt state.
                    interrupts = list(getattr(result, "interrupts", None) or [])
                    names = [str(getattr(i, "name", "?")) for i in interrupts]
                    self._emit(
                        "error", {"message": f"interrupt refused: {names}", "where": "interrupt"}
                    )
                    yield Notice(text=t("notice.interrupt_refused", language))
                    resumes += 1
                    exhausted = self._exhausted(turns_used, tokens_used)
                    if exhausted or not interrupts or resumes > agent_cfg.max_turns:
                        # Give up (a hook that re-interrupts, or no budget left to answer):
                        # leave the interrupt state so the next turn is a plain one.
                        self._clear_interrupt(exhausted or f"{resumes} refusals did not clear it")
                        stop_reason = exhausted or "interrupt"
                        repair = t("notice.interrupt_refused", language)
                        break
                    sdk_prompt = _interrupt_responses(interrupts)
                    limits = self._limits(turns_used, tokens_used, replay=True)
            except ConcurrencyException:
                for item in drain():
                    yield item
                logger.warning("turn refused: agent busy (session %s)", self.session_id)
                yield Notice(text=t("notice.busy", language))
                stop_reason = "busy"
            except MaxTokensReachedException:
                # The SDK kept the partial reply, so the history ends with the assistant.
                for item in drain():
                    yield item
                logger.warning("reply hit the max_tokens limit in session %s", self.session_id)
                text = t("notice.max_tokens", language)
                self._emit("notice", {"message": text, "reason": "max_tokens"})
                yield Notice(text=text)
                stop_reason = "max_tokens"
            except ContextWindowOverflowException as exc:
                for item in drain():
                    yield item
                logger.exception("context window overflow in session %s", self.session_id)
                self._emit("error", {"message": str(exc)[:500], "where": "context"})
                repair = text = t("notice.overflow", language)
                yield Notice(text=text)
                stop_reason = "error"
            except Exception as exc:
                for item in drain():
                    yield item
                if model_notice_of(exc) is not None:
                    # A spent budget: the notice says it all, no trace.
                    logger.warning("model call refused in session %s: %s", self.session_id, exc)
                else:
                    logger.exception("model call failed in session %s", self.session_id)
                self._emit("error", {"message": str(exc)[:500], "where": "model"})
                repair = text = model_error_text(exc, language)
                yield Notice(text=text)
                stop_reason = "error"
            for text, reason in self._model_notices(language):
                self._emit("notice", {"message": text, "reason": reason})
                yield Notice(text=text)
            if stop_reason == "limit_turns":
                self._emit("turn_limit", {"max_turns": agent_cfg.max_turns})
                repair = text = turn_limit_text(agent_cfg.max_turns, language)
                yield Notice(text=text)
            elif stop_reason == "limit_total_tokens":
                self._emit("turn_limit", {"max_total_tokens": agent_cfg.max_total_tokens})
                repair = text = t("notice.total_tokens", language)
                yield Notice(text=text)
            elif stop_reason == "cancelled":
                repair = text = t("notice.cancelled", language)
                self._emit("notice", {"message": text, "reason": "cancelled"})
                yield Notice(text=text)
            if self._appended_since(last_before):
                # The prompt (and any pending repair) is in the history now.
                self._pending_repair = None
                self._write_title(prompt)
            if repair is not None:
                self._schedule_repair(repair, last_before)
            yield TurnEnd(stop_reason=stop_reason)
        finally:
            self._running = False
            if self.agent.cancel_signal.is_set():
                # A cancel that landed after the SDK cleared its signal for this invocation
                # (between its last checkpoint and here) must not poison the next turn.
                logger.debug("clearing a late cancel signal in session %s", self.session_id)
                self.agent.cancel_signal.clear()
            unsubscribe()

    def _model_notices(self, language: str) -> list[tuple[str, str]]:
        """``[(text, reason)]`` the model asks the channel to show about this turn (a spent
        role that handed the call to ``degrade_to``, an unreachable one that failed over),
        each distinct sentence once."""
        take = getattr(self.agent.model, "take_notices", None)
        if not callable(take):
            return []
        found: list[tuple[str, str]] = []
        for notice in take():
            item = (notice.notice(language), str(getattr(notice, "reason", "model")))
            if item not in found:
                found.append(item)
        return found

    def _schedule_repair(self, text: str, last_before: Message | None) -> None:
        """Remember ``text`` for the next turn when this turn left the history dangling.

        ``last_before`` is the last message before the SDK ran: a failure that appended
        nothing (nothing new to repair) leaves the pending notice alone.
        """
        messages = self.agent.messages
        if self._appended_since(last_before) and dangling(messages[-1]):
            self._pending_repair = text

    def carry_over(self, previous: TauAgent) -> None:
        """Take over the pending repair notice of the agent this one replaces on the same
        session (``/model``): a rebuilt agent restores the same dangling history, and the
        notice the next turn prepends should stay the specific one, not the generic text."""
        if previous is not self and previous.session_id == self.session_id:
            self._pending_repair = previous._pending_repair

    async def ask(self, prompt: str) -> str:
        """Run one turn and return only the reply text; raises :class:`GuardLocked` when the
        owner guard refused the turn."""
        parts: list[str] = []
        locked = False
        async for event in self.stream(prompt):
            if isinstance(event, TextDelta):
                parts.append(event.text)
            elif isinstance(event, TurnEnd) and event.stop_reason == "locked":
                locked = True
        if locked:
            raise GuardLocked(self._refused or "error")
        return "".join(parts)


def hooks_behind_gate(agent: Agent, tier_hook: TierHook) -> list[str]:
    """Names of the ``BeforeToolCallEvent`` callbacks the SDK would run after the tier gate.

    Strands runs a tool with the ``tool_use`` (and ``cancel_tool``) left by the *last*
    callback, so anything after ``TierHook`` could change what runs after the gate approved
    it. ``HookRegistry`` accepts any order, so this is checked instead of assumed.
    """
    probe = BeforeToolCallEvent(
        agent=agent,
        selected_tool=None,
        tool_use={"toolUseId": "", "name": "", "input": {}},
        invocation_state={},
    )
    callbacks = list(agent.hooks.get_callbacks_for(probe))
    gate = tier_hook._before_tool_call
    if gate not in callbacks:
        return ["<tier gate not registered>"]
    after = callbacks[callbacks.index(gate) + 1 :]
    return [getattr(cb, "__qualname__", None) or repr(cb) for cb in after]


def discovered_tools(config: Config) -> list[AgentTool]:
    """Every ``tau.tools`` tool minus ``[components] tools.disabled`` (by name or ``dist:``)."""
    kept: list[AgentTool] = []
    for tool in discover_tools():
        distribution = getattr(tool, "tau_distribution", None)
        if config.components.tool_disabled(tool.tool_name, distribution):
            logger.info("tool %s from %s is disabled in [components]", tool.tool_name, distribution)
            continue
        kept.append(tool)
    return kept


def _check_context_state(
    store: SessionStore, session_id: str, manager: ConversationManager
) -> None:
    """Raise :class:`SessionContextMismatch` when the stored agent record of ``session_id``
    names another conversation manager class than ``manager`` (the SDK would refuse the
    restore with a bare ``ValueError``). Store problems are left to the SDK to report."""
    try:
        record = store.read_agent(session_id, AGENT_ID)
    except Exception:
        return
    if record is None:
        return
    stored = (getattr(record, "conversation_manager_state", None) or {}).get("__name__")
    if stored and stored != type(manager).__name__:
        raise SessionContextMismatch(session_id, str(stored))


def conversation_manager_for(agent_cfg: AgentConfig) -> ConversationManager:
    """The Strands conversation manager ``[agent] context`` asks for.

    ``sliding`` keeps the last ``window_size`` messages; ``summarize`` summarizes older
    messages and always keeps the last ``window_size``. The store still records every message
    (ADR 0003). The SDK's ``context_manager="auto"``/``"agentic"`` presets are never used: they
    register untiered SDK tools that the tier gate would refuse.
    """
    if agent_cfg.context == "summarize":
        return SummarizingConversationManager(preserve_recent_messages=agent_cfg.window_size)
    return SlidingWindowConversationManager(window_size=agent_cfg.window_size)


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
    context_sources: Iterable[ContextSource] | None = None,
    channel: str = "terminal",
    clock: Callable[[], datetime] | None = None,
    exemptions: Iterable[Exemption] = (),
    hooks: Iterable[HookProvider] = (),
    plugins: Iterable[Any] = (),
    seed_messages: Iterable[Message] | None = None,
    guard: Guard | None | Any = DISCOVER,
    client_id: str | None = None,
) -> TauAgent:
    """Assemble a tau agent. Raises ``ConfigError``/``MissingCredentials`` before any model call.

    Components come from the registries unless the caller passes its own: ``tools=None`` means
    every ``tau.tools`` entry point minus ``[components] tools.disabled`` (an explicit ``tools``
    list bypasses the switch), ``context_sources=None`` means the enabled ``tau.context``
    components (``[components] context``; an explicit list, even empty, replaces them).

    ``seed_messages`` is the initial history of a *new* session (``/compact`` seeds the summary
    this way). They go in as ``Agent(messages=...)``, and the SDK's ``RepositorySessionManager``
    writes them to the store when it creates the agent record, so they survive ``--resume``. For
    a session that already exists in the store the SDK restores the stored history instead and
    the seed is ignored; callers pass ``session_id=None`` with a seed.

    With a store, the session's metadata records ``channel``, ``profile`` and ``role`` every
    time it is opened, so a resumed session comes back on the role it last ran on. A session
    recorded under another ``[agent] context`` value raises :class:`SessionContextMismatch`
    (a ``ConfigError``) before anything is built.

    ``hooks`` and ``plugins`` are passed to the Strands ``Agent`` as extra components. The tier
    gate keeps the last word: ``TierHook`` runs at ``HookOrder.SDK_LAST``, no component may
    register a ``BeforeToolCallEvent`` callback that would run after it (``ConfigError``, fail
    closed at build time), and a tool a plugin registers behind the catalog's back is refused
    as unknown.

    ``guard`` is the owner guard (ADR 0008) that admits every turn and steps up tier-2 calls.
    The default ``DISCOVER`` resolves it from the configuration (``resolve_guard``), so a
    caller that passes nothing is guarded whenever a guard is active; channels that own a guard
    pass the same object on every build, and only identified in-hub channels (Telegram,
    network turns) pass ``None``. ``client_id`` defaults to this process's id.
    """
    config = config or Config.load()
    if profile:
        config = config.with_overrides(profile=profile)
    model = model or resolve_model(role, config)

    catalog = ToolCatalog()
    if tools is not None:
        catalog.extend(tools)  # an untiered tool passed explicitly is a programming error
    else:
        for tool in discovered_tools(config):
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
    if context_sources is None:
        context_sources = list(registry.context_sources(config).values())
    context_factory = default_context_factory(config, clock=clock, sources=context_sources)
    system_prompt = persona.build_system_content(context_factory())  # fails early without persona

    if guard is DISCOVER:
        guard = resolve_guard(config)
    if guard is not None and not isinstance(guard, Guard):
        raise ConfigError(f"guard must implement tau_core.Guard, not {type(guard).__name__}")
    client_id = client_id or process_client_id()
    gate = TierGate(
        catalog,
        approver,
        events,
        session_id=session_id,
        channel=channel,
        exemptions=exemptions,
        guard=guard,
        client_id=client_id,
    )
    session_manager = (
        RepositorySessionManager(session_id=session_id, session_repository=session_store)
        if session_store is not None
        else None
    )
    # Physical tools never run concurrently: two approved tier-2 calls in one model turn
    # would otherwise execute at the same time in different threads.
    sequential = any(tier_of(tool) is Tier.PHYSICAL for tool in catalog.tools())
    tier_hook = TierHook(gate)
    seed = copy.deepcopy(list(seed_messages)) if seed_messages is not None else None
    conversation_manager = conversation_manager_for(config.agent)
    if session_store is not None:
        _check_context_state(session_store, session_id, conversation_manager)
    try:
        agent = Agent(
            model=model,
            messages=seed or None,
            tools=catalog.tools(),
            system_prompt=system_prompt,
            hooks=[PersonaHook(persona, context_factory), *hooks, tier_hook],
            plugins=list(plugins) or None,
            conversation_manager=conversation_manager,
            session_manager=session_manager,
            tool_executor=SequentialToolExecutor() if sequential else None,
            trace_attributes={
                "tau.session_id": session_id,
                "tau.channel": channel,
                "tau.profile": config.profile,
            },
            callback_handler=None,
            agent_id=AGENT_ID,
            name="tau",
        )
    except ValueError as exc:
        # The SDK's own refusal, in case a stored state slipped past the check above.
        if "conversation manager state" in str(exc).lower():
            raise SessionContextMismatch(session_id, None) from exc
        raise
    behind = hooks_behind_gate(agent, tier_hook)
    if behind:
        raise ConfigError(
            "these hooks would run after the tier gate on BeforeToolCallEvent and could rewrite "
            f"or un-cancel an approved call: {', '.join(behind)}. Register them below "
            f"HookOrder.SDK_LAST ({HookOrder.SDK_LAST})."
        )

    unsubscribe = None
    if session_store is not None:
        session_store.write_meta(session_id, channel=channel, profile=config.profile, role=role)
        unsubscribe = events.subscribe(session_store.event_sink(session_id))

    return TauAgent(
        agent=agent,
        config=config,
        events=events,
        session_id=session_id,
        catalog=catalog,
        store=session_store,
        gate=gate,
        role=role,
        channel=channel,
        guard=guard,
        client_id=client_id,
        _unsubscribe_store=unsubscribe,
    )
