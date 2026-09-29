"""Approval of tier-2 calls, and the gate every tool call passes through.

:class:`TierGate` is the policy and works outside the Strands loop too (reflex engine,
MCP server). :class:`TierHook` adapts it to Strands: ``BeforeToolCallEvent`` asks the gate and
cancels refused calls with a refusal text the model reads as the tool result;
``AfterToolCallEvent`` records the call. Channels plug in their own :class:`Approver`.
Nothing here approves on its own: without an approver the default rejects.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from strands.hooks import AfterToolCallEvent, BeforeToolCallEvent, HookProvider, HookRegistry

from tau_core.events import AgentEvent, EventBus
from tau_core.tiers import Tier, ToolCatalog, effect_of

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
    """Asks the user about one tier-2 call. ``name`` is the approval channel."""

    name: str

    async def decide(self, request: ApprovalRequest) -> Decision: ...


class AutoRejectApprover:
    """Rejects every request. The default when a channel supplies no approver."""

    name = "auto-reject"

    async def decide(self, request: ApprovalRequest) -> Decision:
        return Decision.REJECTED


def format_approval_prompt(request: ApprovalRequest) -> str:
    """The Turkish terminal prompt for one request (no jokes, no decoration beyond the header)."""
    arguments = json.dumps(request.arguments, ensure_ascii=False, sort_keys=True)
    return (
        f"⚠️  Onay gerekiyor (tier {int(request.tier)})\n"
        f"  Araç: {request.tool}\n"
        f"  Argümanlar: {arguments}\n"
        f"  Etki: {request.effect}\n"
        "  Onaylıyor musunuz? [e/H] "
    )


class TerminalApprover:
    """Asks on stdin. ``e``/``evet`` approves; anything else, EOF included, rejects."""

    name = "terminal"

    def __init__(self, input_func: Callable[[str], str] = input):
        self._input = input_func
        self.pending = False

    async def decide(self, request: ApprovalRequest) -> Decision:
        self.pending = True
        try:
            answer = await asyncio.to_thread(self._input, format_approval_prompt(request))
        except (EOFError, KeyboardInterrupt):
            return Decision.REJECTED
        finally:
            self.pending = False
        return Decision.APPROVED if answer.strip().lower() in ("e", "evet") else Decision.REJECTED


Exemption = Callable[[str, dict[str, Any]], bool]
"""``(tool_name, arguments) → True`` exempts a tier-2 call from per-call approval.

Registered routines (issue 037) use this; their registration is approved once instead.
"""


def refusal_text(tool: str) -> str:
    return f"Kullanıcı bu eylemi onaylamadı: {tool}. Eylemi yapma, kullanıcıya kısaca bildir."


def unknown_tool_text(tool: str) -> str:
    return f"'{tool}' aracı kayıtlı değil; çalıştırılmadı."


class TierGate:
    """Tier policy for one session and channel."""

    def __init__(
        self,
        catalog: ToolCatalog,
        approver: Approver,
        events: EventBus,
        *,
        session_id: str | None,
        channel: str,
        exemptions: Iterable[Exemption] = (),
    ):
        self.catalog = catalog
        self.approver = approver
        self.events = events
        self.session_id = session_id
        self.channel = channel
        self.exemptions = list(exemptions)
        self._approval_lock: asyncio.Lock | None = None

    def _emit(self, kind: str, data: dict[str, Any]) -> None:
        self.events.emit(AgentEvent.create(kind, data, session_id=self.session_id))

    def _is_exempt(self, tool_name: str, arguments: dict[str, Any]) -> bool:
        for exemption in self.exemptions:
            try:
                if exemption(tool_name, arguments):
                    return True
            except Exception:
                logger.exception(
                    "exemption %r failed for %s; treating as not exempt", exemption, tool_name
                )
        return False

    async def check(
        self, tool_name: str, arguments: dict[str, Any], *, tool_use_id: str
    ) -> tuple[bool, str | None, str | None]:
        """Return ``(allowed, refusal_text, approval)``.

        ``approval`` is ``"approved"``, ``"rejected"``, ``"timeout"``, ``"exempt"`` or ``None``
        (tier 0/1, or an unknown tool, which fails closed).
        """
        tier = self.catalog.tier(tool_name)
        if tier is None:
            text = unknown_tool_text(tool_name)
            self._emit("error", {"message": text, "where": "tier_gate", "tool": tool_name})
            logger.warning("refused unknown tool %s (tool_use_id=%s)", tool_name, tool_use_id)
            return False, text, None
        if tier < Tier.PHYSICAL:
            return True, None, None
        if self._is_exempt(tool_name, arguments):
            logger.info("tier-2 tool %s exempt from approval", tool_name)
            return True, None, "exempt"

        tool = self.catalog.get(tool_name)
        request = ApprovalRequest(
            request_id=uuid.uuid4().hex[:12],
            tool=tool_name,
            tier=tier,
            arguments=dict(arguments),
            effect=effect_of(tool) if tool is not None else "",
            session_id=self.session_id,
            channel=self.channel,
        )
        if self._approval_lock is None:
            self._approval_lock = asyncio.Lock()
        async with self._approval_lock:  # one prompt at a time, even for parallel tool calls
            try:
                decision = Decision(await self.approver.decide(request))
            except Exception:
                logger.exception("approver %s failed; rejecting %s", self.approver.name, tool_name)
                decision = Decision.REJECTED
        self._emit(
            "approval",
            {
                "tool": tool_name,
                "tier": int(tier),
                "arguments": dict(arguments),
                "effect": request.effect,
                "decision": decision.value,
                "channel": getattr(self.approver, "name", self.channel),
                "request_id": request.request_id,
            },
        )
        logger.info("approval %s for %s via %s", decision.value, tool_name, self.approver.name)
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
        """Emit a ``tool_call`` event (every tier) and log it (tier 0 debug, tier ≥ 1 info)."""
        tier = self.catalog.tier(tool_name)
        summary = summary[:SUMMARY_LIMIT]
        self._emit(
            "tool_call",
            {
                "tool": tool_name,
                "tier": int(tier) if tier is not None else None,
                "arguments": dict(arguments),
                "status": status,
                "result_summary": summary,
                "approval": approval,
                "duration_ms": duration_ms,
                "tool_use_id": tool_use_id,
            },
        )
        level = logging.DEBUG if tier == Tier.READ else logging.INFO
        if tier is None:
            level = logging.WARNING
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


class TierHook(HookProvider):
    """Strands adapter for :class:`TierGate`."""

    def __init__(self, gate: TierGate):
        self.gate = gate
        self._approvals: dict[str, str | None] = {}

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(BeforeToolCallEvent, self._before_tool_call)
        registry.add_callback(AfterToolCallEvent, self._after_tool_call)

    async def _before_tool_call(self, event: BeforeToolCallEvent) -> None:
        tool_use = event.tool_use
        tool_use_id = str(tool_use.get("toolUseId", ""))
        allowed, refusal, approval = await self.gate.check(
            str(tool_use.get("name", "")), _arguments(tool_use), tool_use_id=tool_use_id
        )
        self._approvals[tool_use_id] = approval
        if not allowed:
            event.cancel_tool = refusal or True

    def _after_tool_call(self, event: AfterToolCallEvent) -> None:
        tool_use = event.tool_use
        tool_use_id = str(tool_use.get("toolUseId", ""))
        result = event.result or {}
        if event.cancel_message:
            status = "rejected"
        elif result.get("status") == "success" and event.exception is None:
            status = "ok"
        else:
            status = "error"
        duration = getattr(event, "duration", None)
        self.gate.record(
            tool_name=str(tool_use.get("name", "")),
            arguments=_arguments(tool_use),
            status=status,
            summary=event.cancel_message or _summary(result),
            approval=self._approvals.pop(tool_use_id, None),
            duration_ms=int(duration * 1000) if duration is not None else None,
            tool_use_id=tool_use_id,
        )
