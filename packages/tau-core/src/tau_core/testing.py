"""Public test helpers: a scripted model, scripted approvers and a throwaway config.

Everything here runs offline. Other tau packages (tau-tui, plugins) use these in their tests.
There is deliberately no approver that approves everything: an approved path is scripted with
``ScriptedApprover([Decision.APPROVED])`` so every approval is visible in the test.
"""

from __future__ import annotations

import copy
import json
from collections.abc import AsyncGenerator, Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from strands.models.model import Model
from strands.types.content import Message, SystemContentBlock
from strands.types.tools import ToolSpec

from tau_core.approval import ApprovalRequest, AutoRejectApprover, Decision
from tau_core.config import Config

__all__ = [
    "AutoRejectApprover",
    "FakeCall",
    "FakeModel",
    "Reply",
    "ScriptedApprover",
    "ToolCall",
    "Truncated",
    "test_config",
]


@dataclass
class ToolCall:
    """One tool use the fake model asks for."""

    name: str
    input: dict[str, Any] = field(default_factory=dict)
    tool_use_id: str | None = None


@dataclass
class Truncated:
    """A text reply cut by the provider's output limit (``stopReason: max_tokens``)."""

    text: str


Reply = str | Truncated | list[ToolCall] | Callable[[list[Message], str | None], "Reply"]


@dataclass
class FakeCall:
    """What the agent sent on one model call.

    ``system_prompt`` is the string form the SDK derives (text blocks joined with a newline);
    ``system_prompt_content`` is the block list with cache points, when the agent used one.
    """

    messages: list[Message]
    system_prompt: str | None
    tool_specs: list[ToolSpec] | None
    system_prompt_content: list[SystemContentBlock] | None = None


class FakeModel(Model):
    """A Strands model that replays scripted replies.

    Replies are used in order; when they run out, ``default`` is returned. A ``str`` streams
    as two text deltas, a ``Truncated`` streams its text and stops with ``max_tokens``, a
    ``list[ToolCall]`` streams tool uses (``stopReason: tool_use``), a callable receives
    ``(messages, system_prompt)`` and returns one of those (or raises, to fail the call).
    """

    def __init__(self, replies: Sequence[Reply] | None = None, *, default: str = "Okay."):
        self.replies: list[Reply] = list(replies or [])
        self.default = default
        self.calls: list[FakeCall] = []
        self.config: dict[str, Any] = {"model_id": "fake"}
        self._tool_counter = 0

    def update_config(self, **model_config: Any) -> None:
        self.config.update(model_config)

    def get_config(self) -> dict[str, Any]:
        return dict(self.config)

    def _next_reply(self, messages: list[Message], system_prompt: str | None) -> str | list:
        reply: Reply = self.replies.pop(0) if self.replies else self.default
        while callable(reply):
            reply = reply(messages, system_prompt)
        return reply

    async def stream(
        self,
        messages: list[Message],
        tool_specs: list[ToolSpec] | None = None,
        system_prompt: str | None = None,
        **kwargs: Any,
    ) -> AsyncGenerator[dict[str, Any], None]:
        self.calls.append(
            FakeCall(
                messages=copy.deepcopy(messages),
                system_prompt=system_prompt,
                tool_specs=tool_specs,
                system_prompt_content=copy.deepcopy(kwargs.get("system_prompt_content")),
            )
        )
        reply = self._next_reply(messages, system_prompt)
        yield {"messageStart": {"role": "assistant"}}
        if isinstance(reply, str | Truncated):
            text = reply if isinstance(reply, str) else reply.text
            half = len(text) // 2
            yield {"contentBlockStart": {"start": {}}}
            for part in (text[:half], text[half:]):
                yield {"contentBlockDelta": {"delta": {"text": part}}}
            yield {"contentBlockStop": {}}
            stop = "end_turn" if isinstance(reply, str) else "max_tokens"
            yield {"messageStop": {"stopReason": stop}}
        else:
            for call in reply:
                self._tool_counter += 1
                tool_use_id = call.tool_use_id or f"t{self._tool_counter}"
                start = {"toolUse": {"toolUseId": tool_use_id, "name": call.name}}
                yield {"contentBlockStart": {"start": start}}
                delta = {"toolUse": {"input": json.dumps(call.input, ensure_ascii=False)}}
                yield {"contentBlockDelta": {"delta": delta}}
                yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "tool_use"}}
        yield {
            "metadata": {
                "usage": {"inputTokens": 1, "outputTokens": 1, "totalTokens": 2},
                "metrics": {"latencyMs": 1},
            }
        }

    async def structured_output(
        self, output_model: Any, prompt: Any, system_prompt: str | None = None, **kwargs: Any
    ) -> AsyncGenerator[dict[str, Any], None]:
        try:
            output = output_model()
        except Exception:
            output = output_model.model_construct()
        yield {"output": output}


class ScriptedApprover:
    """Returns scripted decisions in order and records every request; exhausted → REJECTED."""

    name = "scripted"

    def __init__(self, decisions: Iterable[Decision] = ()):
        self.decisions: list[Decision] = list(decisions)
        self.requests: list[ApprovalRequest] = []

    async def decide(self, request: ApprovalRequest) -> Decision:
        self.requests.append(request)
        return self.decisions.pop(0) if self.decisions else Decision.REJECTED


_TEST_TOML = """\
[models.roles.brain]
provider = "fake"
model_id = "fake-brain"

[models.roles.fast]
provider = "fake"
model_id = "fake-fast"

[models.roles.local]
provider = "fake"
model_id = "fake-local"

[agent]
max_turns = 12

[sessions]
backend = "memory"

[hub]
control_port = 7877
heartbeat_seconds = 5

[ui]
language = "en"
"""

_TEST_PERSONA = "You are tau: a polite assistant who keeps replies short.\n"
_TEST_USER = "Address the user formally.\n"


def test_config(tmp_path: Path, **overrides: Any) -> Config:
    """A ``Config`` under ``tmp_path``: fake roles, memory sessions, a minimal persona.

    ``tmp_path/home`` holds ``tau.toml`` and ``persona/``; ``tmp_path/data`` is the data dir.
    ``overrides`` are applied with :meth:`Config.with_overrides`.
    """
    home = Path(tmp_path) / "home"
    persona_dir = home / "persona"
    persona_dir.mkdir(parents=True, exist_ok=True)
    (home / "tau.toml").write_text(_TEST_TOML, encoding="utf-8")
    (persona_dir / "persona.md").write_text(_TEST_PERSONA, encoding="utf-8")
    (persona_dir / "user.md").write_text(_TEST_USER, encoding="utf-8")
    data_dir = Path(tmp_path) / "data"
    config = Config.load(home, env={"TAU_DATA_DIR": str(data_dir)})
    return config.with_overrides(**overrides) if overrides else config


# Not a test, despite the name; keep pytest from collecting it when imported into a test module.
test_config.__test__ = False  # type: ignore[attr-defined]


# Approval and event helpers (issue 006). Appended here so the section above stays untouched.

import asyncio  # noqa: E402

from tau_core.events import AgentEvent, EventBus  # noqa: E402

__all__ += ["UnansweredApprover", "record_events"]


class UnansweredApprover:
    """Never answers, like a user who walked away. For approval-timeout tests.

    ``decide`` waits until it is cancelled (by the gate's ``timeout_seconds`` or the
    approver's own), records every request and counts the cancellations. It never approves.
    """

    name = "unanswered"

    def __init__(self, *, timeout_seconds: float | None = None):
        self.timeout_seconds = timeout_seconds
        self.requests: list[ApprovalRequest] = []
        self.cancelled = 0

    async def decide(self, request: ApprovalRequest) -> Decision:
        self.requests.append(request)
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled += 1
            raise
        return Decision.REJECTED  # pragma: no cover  (the wait above never ends on its own)


def record_events(bus: EventBus, *kinds: str) -> list[AgentEvent]:
    """Subscribe to ``bus``; the returned list fills with its events (only ``kinds`` if given)."""
    seen: list[AgentEvent] = []

    def sink(event: AgentEvent) -> None:
        if not kinds or event.kind in kinds:
            seen.append(event)

    bus.subscribe(sink)
    return seen
