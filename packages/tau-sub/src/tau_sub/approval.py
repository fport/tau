"""Approvers for sub-tau turns. None of them approves anything on its own.

- :func:`turn_gate` / :func:`turn_approver` find the tier gate, and so the approver, of the
  tau turn that is running a tool. A ``@tau_tool(context=True)`` receives the Strands agent
  that called it in its ``ToolContext``; ``build_agent`` registers tau-core's ``TierHook`` on
  that agent, and the hook holds the gate (``TierHook.gate``, ``TierGate.approver``). The hook
  is found through the public ``HookRegistry.get_callbacks_for``, the same way
  ``tau_core.agent.hooks_behind_gate`` inspects it.
- :class:`DelegatedApprover` asks that approver, with the request's effect marked as coming
  from the sub-tau, so the owner sees who wants to act.
- :class:`RefusingApprover` rejects every request and says where it could be approved.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from strands.hooks import BeforeToolCallEvent
from tau_core import ApprovalRequest, Approver, Decision, TierGate, TierHook

__all__ = ["DelegatedApprover", "RefusingApprover", "turn_approver", "turn_gate"]


def turn_gate(agent: Any) -> TierGate | None:
    """The tier gate ``build_agent`` put on this Strands agent, or ``None`` (not a tau agent)."""
    hooks = getattr(agent, "hooks", None)
    callbacks_for = getattr(hooks, "get_callbacks_for", None)
    if not callable(callbacks_for):
        return None
    probe = BeforeToolCallEvent(
        agent=agent,
        selected_tool=None,
        tool_use={"toolUseId": "", "name": "", "input": {}},
        invocation_state={},
    )
    try:
        callbacks = list(callbacks_for(probe))
    except Exception:
        return None
    for callback in callbacks:
        owner = getattr(callback, "__self__", None)
        if isinstance(owner, TierHook) and isinstance(owner.gate, TierGate):
            return owner.gate
    return None


def turn_approver(agent: Any) -> Approver | None:
    """The approver of the turn running on ``agent``, or ``None`` when there is none."""
    gate = turn_gate(agent)
    approver = getattr(gate, "approver", None)
    return approver if isinstance(approver, Approver) else None


class DelegatedApprover:
    """Asks ``inner`` about a sub-tau's tier-2 call; the decision is ``inner``'s, unchanged.

    The request's effect is prefixed with the sub-tau's name. ``timeout_seconds`` and
    ``refusal_note`` are ``inner``'s, so the gate waits and refuses the way the channel does.
    """

    def __init__(self, inner: Approver, sub_name: str):
        self.inner = inner
        self.sub_name = sub_name
        self.name = str(getattr(inner, "name", "delegated"))

    @property
    def timeout_seconds(self) -> float | None:
        return getattr(self.inner, "timeout_seconds", None)

    @property
    def refusal_note(self) -> str | None:
        note = getattr(self.inner, "refusal_note", None)
        return note if isinstance(note, str) else None

    async def decide(self, request: ApprovalRequest) -> Decision:
        effect = f"/{self.sub_name}, a sub-tau your tau asked, wants to: {request.effect}"
        return await self.inner.decide(dataclasses.replace(request, effect=effect))


class RefusingApprover:
    """Rejects every request; ``refusal_note`` (fixed English) tells the model where the owner
    could approve it instead."""

    name = "sub-refuse"

    def __init__(self, refusal_note: str):
        self.refusal_note = refusal_note

    async def decide(self, request: ApprovalRequest) -> Decision:
        return Decision.REJECTED
