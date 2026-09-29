"""Approval of tier-2 calls, and the gate every tool call passes through.

:class:`TierGate` is the policy and works outside the Strands loop too (reflex engine,
MCP server). :class:`TierHook` adapts it to Strands: ``BeforeToolCallEvent`` asks the gate and
cancels refused calls with a refusal text the model reads as the tool result;
``AfterToolCallEvent`` records the call. Channels plug in their own :class:`Approver`.
Nothing here approves on its own: without an approver the default rejects, and every doubt
(unknown tool, failing approver, invalid answer, timeout, internal error) refuses the call.
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from strands.hooks import (
    AfterToolCallEvent,
    BeforeToolCallEvent,
    HookOrder,
    HookProvider,
    HookRegistry,
)

from tau_core.events import AgentEvent, EventBus
from tau_core.i18n import DEFAULT_LANGUAGE, t
from tau_core.tiers import Tier, ToolCatalog, UntieredToolError, effect_of

logger = logging.getLogger(__name__)

SUMMARY_LIMIT = 200


class Decision(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"
    TIMEOUT = "timeout"


@dataclass(frozen=True)
class ApprovalRequest:
    request_id: str
    tool: str
    tier: Tier
    arguments: dict[str, Any]
    effect: str
    session_id: str | None
    channel: str


@runtime_checkable
class Approver(Protocol):
    """Asks the user about one tier-2 call. ``name`` is the approval channel.

    An approver may also define ``timeout_seconds`` (``float | None``): the gate then stops
    waiting after that long and records ``Decision.TIMEOUT``, unless the gate has its own
    ``timeout_seconds``. ``decide`` must be cancellable for that to work.
    """

    name: str

    async def decide(self, request: ApprovalRequest) -> Decision: ...


class AutoRejectApprover:
    """Rejects every request. The default when a channel supplies no approver."""

    name = "auto-reject"

    async def decide(self, request: ApprovalRequest) -> Decision:
        return Decision.REJECTED


def _printable(text: str) -> str:
    """Escape characters that could rewrite or hide what the terminal shows.

    Control characters, C1 escapes (``\\x9b`` is a CSI) and bidi/format characters
    (``\\u202e``) come from the model's arguments and must not reach the terminal raw.
    """
    return "".join(
        ch if ch.isprintable() else ch.encode("unicode_escape").decode("ascii") for ch in text
    )


def format_approval_prompt(request: ApprovalRequest, language: str = DEFAULT_LANGUAGE) -> str:
    """The terminal prompt for one request in the UI language (no jokes, no decoration)."""
    arguments = json.dumps(request.arguments, ensure_ascii=False, sort_keys=True, default=str)
    effect = " ".join(str(request.effect).split())
    return (
        f"⚠️  {t('approval.title', language, tier=int(request.tier))}\n"
        f"  {t('approval.tool', language)}: {_printable(request.tool)}\n"
        f"  {t('approval.arguments', language)}: {_printable(arguments)}\n"
        f"  {t('approval.effect', language)}: {_printable(effect)}\n"
        f"  {t('approval.question', language)}"
    )


APPROVE_ANSWERS = frozenset({"y", "yes", "e", "evet"})
"""Answers that approve on the terminal, in both languages whatever the UI setting."""


class TerminalApprover:
    """Asks on stdin. ``y``/``yes``/``e``/``evet`` approves; anything else, EOF included, rejects.

    No timeout: ``input()`` blocks a worker thread that cannot be cancelled, so a gate timeout
    would leave the thread reading the next line the user types. Do not give a gate that uses
    this approver a ``timeout_seconds``. ``language`` picks the wording of the prompt.
    """

    name = "terminal"
    timeout_seconds: float | None = None

    def __init__(
        self, input_func: Callable[[str], str] = input, *, language: str = DEFAULT_LANGUAGE
    ):
        self._input = input_func
        self.language = language
        self.pending = False

    async def decide(self, request: ApprovalRequest) -> Decision:
        self.pending = True
        try:
            prompt = format_approval_prompt(request, self.language)
            answer = await asyncio.to_thread(self._input, prompt)
        except (EOFError, KeyboardInterrupt):
            return Decision.REJECTED
        finally:
            self.pending = False
        if not isinstance(answer, str):
            return Decision.REJECTED
        if answer.strip().casefold() in APPROVE_ANSWERS:
            return Decision.APPROVED
        return Decision.REJECTED


Exemption = Callable[[str, dict[str, Any]], bool]
"""``(tool_name, arguments) → True`` exempts a tier-2 call from per-call approval.

Registered routines (issue 037) use this; their registration is approved once instead.
Only tier-2 calls to known tools consult exemptions. An exemption gets a copy of the
arguments and must return ``True`` itself (a merely truthy value does not exempt); one that
raises counts as "not exempt".
"""


def refusal_text(tool: str) -> str:
    """What the model reads as the tool result of a refused call (fixed English)."""
    return (
        f"The user did not approve this action: {tool}. Do not perform it; tell the user briefly."
    )


def unknown_tool_text(tool: str) -> str:
    """Tool result for a call to a tool the catalog does not know (fixed English)."""
    return f"Tool '{tool}' is not registered; it was not run."


def _copy_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    """A deep copy, so nobody who only looks at a call can change what runs."""
    try:
        return copy.deepcopy(dict(arguments))
    except Exception:
        return dict(arguments)


def _validate_timeout(value: float | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
        raise ValueError(f"timeout_seconds must be a positive number or None, not {value!r}")
    return float(value)


class TierGate:
    """Tier policy for one session and channel.

    ``timeout_seconds`` bounds how long a tier-2 call waits for the approver; when it is
    ``None`` the approver's own ``timeout_seconds`` attribute applies, if it has one.
    """

    def __init__(
        self,
        catalog: ToolCatalog,
        approver: Approver,
        events: EventBus,
        *,
        session_id: str | None,
        channel: str,
        exemptions: Iterable[Exemption] = (),
        timeout_seconds: float | None = None,
    ):
        self.catalog = catalog
        self.approver = approver
        self.events = events
        self.session_id = session_id
        self.channel = channel
        self.exemptions: list[Exemption] = list(exemptions)
        self.timeout_seconds = _validate_timeout(timeout_seconds)
        self._approval_lock: asyncio.Lock | None = None
        self._lock_loop: asyncio.AbstractEventLoop | None = None

    def add_exemption(self, exemption: Exemption) -> Callable[[], None]:
        """Exempt matching tier-2 calls from now on; returns a function that undoes it."""
        self.exemptions.append(exemption)

        def remove() -> None:
            if exemption in self.exemptions:
                self.exemptions.remove(exemption)

        return remove

    def effective_timeout(self) -> float | None:
        """The gate's timeout, else the approver's ``timeout_seconds``, else none."""
        if self.timeout_seconds is not None:
            return self.timeout_seconds
        try:
            return _validate_timeout(getattr(self.approver, "timeout_seconds", None))
        except ValueError:
            logger.warning(
                "approver %s has an invalid timeout_seconds; waiting without a timeout",
                getattr(self.approver, "name", "?"),
            )
            return None

    def _emit(self, kind: str, data: dict[str, Any]) -> None:
        self.events.emit(AgentEvent.create(kind, data, session_id=self.session_id))

    def _tier(self, tool_name: str) -> Tier | None:
        """The registered tier, or ``None`` for an unknown (or since broken) tool."""
        try:
            return self.catalog.tier(tool_name)
        except UntieredToolError:
            logger.error("tool %s lost its tier after registration", tool_name)
            return None

    def _lock(self) -> asyncio.Lock:
        # One lock per event loop: a gate may outlive the loop it was first used in.
        loop = asyncio.get_running_loop()
        if self._approval_lock is None or self._lock_loop is not loop:
            self._approval_lock = asyncio.Lock()
            self._lock_loop = loop
        return self._approval_lock

    def _is_exempt(self, tool_name: str, arguments: dict[str, Any]) -> bool:
        for exemption in list(self.exemptions):
            try:
                if exemption(tool_name, _copy_arguments(arguments)) is True:
                    return True
            except Exception:
                logger.exception(
                    "exemption %r failed for %s; treating as not exempt", exemption, tool_name
                )
        return False

    async def _ask(self, request: ApprovalRequest) -> Decision:
        timeout = self.effective_timeout()
        name = getattr(self.approver, "name", "?")
        try:
            if timeout is None:
                answer = await self.approver.decide(request)
            else:
                answer = await asyncio.wait_for(self.approver.decide(request), timeout)
        except TimeoutError:
            logger.warning(
                "approval for %s via %s timed out after %ss", request.tool, name, timeout
            )
            return Decision.TIMEOUT
        except Exception:
            logger.exception("approver %s failed; rejecting %s", name, request.tool)
            return Decision.REJECTED
        if isinstance(answer, Decision):
            return answer
        try:
            return Decision(answer)
        except ValueError:
            logger.error("approver %s answered %r for %s; rejecting", name, answer, request.tool)
            return Decision.REJECTED

    async def check(
        self, tool_name: str, arguments: dict[str, Any], *, tool_use_id: str
    ) -> tuple[bool, str | None, str | None]:
        """Return ``(allowed, refusal_text, approval)``.

        ``approval`` is ``"approved"``, ``"rejected"``, ``"timeout"``, ``"exempt"`` or ``None``
        (tier 0/1, or an unknown tool, which fails closed).
        """
        tier = self._tier(tool_name)
        if tier is None:
            text = unknown_tool_text(tool_name)
            self._emit("error", {"message": text, "where": "tier_gate", "tool": tool_name})
            logger.warning("refused unknown tool %s (tool_use_id=%s)", tool_name, tool_use_id)
            return False, text, None
        if tier < Tier.PHYSICAL:
            return True, None, None
        if self._is_exempt(tool_name, arguments):
            logger.info(
                "tier-2 tool %s exempt from approval (tool_use_id=%s)", tool_name, tool_use_id
            )
            return True, None, "exempt"

        tool = self.catalog.get(tool_name)
        request = ApprovalRequest(
            request_id=uuid.uuid4().hex[:12],
            tool=tool_name,
            tier=tier,
            arguments=_copy_arguments(arguments),
            effect=effect_of(tool) if tool is not None else "",
            session_id=self.session_id,
            channel=self.channel,
        )
        async with self._lock():  # one prompt at a time, even for parallel tool calls
            decision = await self._ask(request)
        self._emit(
            "approval",
            {
                "tool": tool_name,
                "tier": int(tier),
                "arguments": _copy_arguments(arguments),
                "effect": request.effect,
                "decision": decision.value,
                "channel": getattr(self.approver, "name", self.channel),
                "request_id": request.request_id,
            },
        )
        logger.info(
            "approval %s for %s via %s (request_id=%s)",
            decision.value,
            tool_name,
            getattr(self.approver, "name", "?"),
            request.request_id,
        )
        if decision is Decision.APPROVED:
            return True, None, decision.value
        return False, refusal_text(tool_name), decision.value

    def record(
        self,
        *,
        tool_name: str,
        arguments: dict[str, Any],
        status: str,
        summary: str,
        approval: str | None,
        duration_ms: int | None,
        tool_use_id: str,
    ) -> None:
        """Emit a ``tool_call`` event (every tier) and log it.

        Log levels: tier 0 ``DEBUG``, tier 1 and 2 ``INFO`` (the file log keeps them), unknown
        tools ``WARNING``. The line carries arguments, status, result summary and approval.
        """
        tier = self._tier(tool_name)
        summary = summary[:SUMMARY_LIMIT]
        self._emit(
            "tool_call",
            {
                "tool": tool_name,
                "tier": int(tier) if tier is not None else None,
                "arguments": _copy_arguments(arguments),
                "status": status,
                "result_summary": summary,
                "approval": approval,
                "duration_ms": duration_ms,
                "tool_use_id": tool_use_id,
            },
        )
        if tier is None:
            level = logging.WARNING
        elif tier == Tier.READ:
            level = logging.DEBUG
        else:
            level = logging.INFO
        logger.log(
            level,
            "tool_call %s tier=%s status=%s approval=%s args=%s summary=%s",
            tool_name,
            None if tier is None else int(tier),
            status,
            approval,
            json.dumps(arguments, ensure_ascii=False, default=str),
            summary,
        )


def _arguments(tool_use: dict[str, Any]) -> dict[str, Any]:
    raw = tool_use.get("input")
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except ValueError:
            return {"input": raw}
        return parsed if isinstance(parsed, dict) else {"input": parsed}
    return {} if raw is None else {"input": raw}


def _summary(result: dict[str, Any] | None) -> str:
    if not result:
        return ""
    parts = [block["text"] for block in result.get("content", []) if "text" in block]
    if not parts:
        parts = [json.dumps(block, default=str) for block in result.get("content", [])]
    return " ".join(" ".join(parts).split())[:SUMMARY_LIMIT]


@dataclass(frozen=True)
class _Checked:
    """What the gate decided for one ``tool_use_id``, kept until the call is recorded."""

    approval: str | None
    refusal: str | None
    arguments: dict[str, Any]


def overridden_text(tool: str, *, refused: bool) -> str:
    """The error recorded when a hook behind the gate changed what the gate decided."""
    if refused:
        return f"The tier gate refused {tool} but a later hook let it run."
    return f"{tool} ran with arguments the tier gate did not approve."


class TierHook(HookProvider):
    """Strands adapter for :class:`TierGate`.

    Both callbacks register at ``HookOrder.SDK_LAST``: Strands runs the tool with the
    ``tool_use`` and ``cancel_tool`` left by the last ``BeforeToolCallEvent`` callback, and the
    gate must have the last word, whatever hooks, interventions (order 90) or plugins rewrite
    before it. Registration order plays no part; ``build_agent`` refuses a component whose
    callback would still run after the gate (``HookRegistry`` accepts any order). Should one
    get behind it anyway (a hook added to the SDK agent after build), the ``After`` callback
    notices that a refused call ran or an approved call ran with other arguments and records
    it as an ``error`` with an ``error`` event; the call itself cannot be undone by then.
    """

    def __init__(self, gate: TierGate):
        self.gate = gate
        self._checked: dict[str, _Checked] = {}

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(BeforeToolCallEvent, self._before_tool_call, order=HookOrder.SDK_LAST)
        registry.add_callback(AfterToolCallEvent, self._after_tool_call, order=HookOrder.SDK_LAST)

    async def _before_tool_call(self, event: BeforeToolCallEvent) -> None:
        tool_use = event.tool_use
        tool_use_id = str(tool_use.get("toolUseId", ""))
        tool_name = str(tool_use.get("name", ""))
        arguments = _arguments(tool_use)
        try:
            allowed, refusal, approval = await self.gate.check(
                tool_name, arguments, tool_use_id=tool_use_id
            )
        except Exception:
            # A bug in the gate must never let a call through.
            logger.exception("tier gate failed for %s; refusing the call", tool_name)
            allowed, refusal, approval = False, refusal_text(tool_name), None
        if allowed:
            refusal = None
        else:
            refusal = refusal or refusal_text(tool_name)
            event.cancel_tool = refusal
        self._checked[tool_use_id] = _Checked(approval, refusal, _copy_arguments(arguments))

    def _overridden(self, checked: _Checked | None, event: AfterToolCallEvent) -> str | None:
        """The error text when what ran is not what the gate decided, else ``None``."""
        if checked is None:
            return None
        tool_name = str(event.tool_use.get("name", ""))
        if checked.refusal is not None:
            if event.cancel_message != checked.refusal:
                return overridden_text(tool_name, refused=True)
            return None
        if checked.approval in ("approved", "exempt"):
            if _arguments(event.tool_use) != checked.arguments:
                return overridden_text(tool_name, refused=False)
        return None

    def _after_tool_call(self, event: AfterToolCallEvent) -> None:
        tool_use = event.tool_use
        tool_use_id = str(tool_use.get("toolUseId", ""))
        tool_name = str(tool_use.get("name", ""))
        checked = self._checked.pop(tool_use_id, None)
        result = event.result or {}
        if event.cancel_message:
            status = "rejected"
        elif result.get("status") == "success" and event.exception is None:
            status = "ok"
        else:
            status = "error"
        summary = event.cancel_message or _summary(result)
        overridden = self._overridden(checked, event)
        if overridden is not None:
            logger.error("%s (tool_use_id=%s)", overridden, tool_use_id)
            self.gate._emit(
                "error", {"message": overridden, "where": "tier_gate", "tool": tool_name}
            )
            status, summary = "error", overridden
        duration = getattr(event, "duration", None)
        self.gate.record(
            tool_name=tool_name,
            arguments=_arguments(tool_use),
            status=status,
            summary=summary,
            approval=checked.approval if checked is not None else None,
            duration_ms=int(duration * 1000) if duration is not None else None,
            tool_use_id=tool_use_id,
        )
