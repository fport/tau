"""The turn protocol (issue 177, ADR 0015 §1): event bodies, framing, history blocks, and the
vectors the TypeScript half checks (``cloud/shared/turn/vectors.json``)."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from strands.types.session import SessionMessage
from tau_core import (
    AgentEvent,
    ApprovalRequest,
    Config,
    Decision,
    EventBus,
    MemorySessionStore,
    Notice,
    ReasoningDelta,
    TextDelta,
    Throttled,
    Tier,
    ToolFinished,
    ToolInput,
    ToolProgress,
    ToolUseStarted,
    TurnEnd,
    build_agent,
    tau_tool,
    tool_inputs_of,
)
from tau_core.agent import AGENT_ID
from tau_core.channels.terminal import render_turn_event
from tau_core.testing import FakeModel, ScriptedApprover, ToolCall
from tau_core.turn_protocol import (
    BLOCK_TYPES,
    EVENT_TYPES,
    INPUT_LIMIT,
    PROTOCOL_VERSION,
    approval_body,
    approval_decided,
    encode,
    error_body,
    frame,
    guard_body,
    history_blocks,
    turn_event_body,
    turn_started,
    widget_body,
)

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "make_turn_vectors.py"


def _load_generator() -> ModuleType:
    spec = importlib.util.spec_from_file_location("make_turn_vectors", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@tau_tool(tier=Tier.READ)
def clock_tool(city: str) -> str:
    """Tells the time in a city."""
    return f"15:30 in {city}"


@tau_tool(tier=Tier.PHYSICAL, effect="physical")
def lamp_tool(on: bool) -> str:
    """Switches the test lamp."""
    return "on" if on else "off"


@tau_tool(tier=Tier.READ)
def render_ui(title: str, html: str) -> str:
    """Shows a widget (a stand-in for tau-web's tool)."""
    return "rendered"


# -- framing and bodies ------------------------------------------------------------------------


def test_frame_puts_version_and_seq_first_and_refuses_unknown_types() -> None:
    event = frame(turn_event_body(TextDelta(text="selam")), 3)
    assert list(event) == ["v", "seq", "type", "delta"]
    assert event == {"v": PROTOCOL_VERSION, "seq": 3, "type": "text", "delta": "selam"}
    with pytest.raises(ValueError, match="telepathy"):
        frame({"type": "telepathy"}, 0)


def test_encode_is_one_compact_utf8_line() -> None:
    line = encode(frame(turn_event_body(TextDelta(text="çay\nşeker")), 0))
    assert line.endswith("\n") and line.count("\n") == 1
    assert json.loads(line)["delta"] == "çay\nşeker"
    assert "ç" in line and ", " not in line


@pytest.mark.parametrize(
    ("event", "body"),
    [
        (TextDelta(text="a"), {"type": "text", "delta": "a"}),
        (ReasoningDelta(text="b"), {"type": "reasoning", "delta": "b"}),
        (
            ToolUseStarted(tool_use_id="u", tool="clock_tool", tier=0),
            {"type": "tool_use", "id": "u", "tool": "clock_tool", "tier": 0},
        ),
        (
            ToolInput(tool_use_id="u", tool="clock_tool", input={"city": "İzmir"}),
            {
                "type": "tool_input",
                "id": "u",
                "tool": "clock_tool",
                "input": {"city": "İzmir"},
                "truncated": False,
            },
        ),
        (
            ToolProgress(tool_use_id="u", tool="clock_tool", text="50%"),
            {"type": "tool_progress", "id": "u", "tool": "clock_tool", "message": "50%"},
        ),
        (
            ToolFinished(
                tool_use_id="u", tool="clock_tool", status="ok", summary="15:30", approval=None
            ),
            {
                "type": "tool_result",
                "id": "u",
                "tool": "clock_tool",
                "status": "ok",
                "summary": "15:30",
                "approval": None,
            },
        ),
        (Throttled(delay_seconds=1.5), {"type": "throttled", "delay_seconds": 1.5}),
        (Notice(text="n"), {"type": "notice", "text": "n"}),
        (TurnEnd(stop_reason="locked"), {"type": "end", "stop_reason": "locked"}),
    ],
)
def test_every_turn_event_has_a_body(event: Any, body: dict[str, Any]) -> None:
    assert turn_event_body(event) == body
    assert body["type"] in EVENT_TYPES


def test_a_non_turn_event_is_refused() -> None:
    with pytest.raises(TypeError):
        turn_event_body("text")  # type: ignore[arg-type]


def test_a_large_input_becomes_a_preview() -> None:
    body = turn_event_body(ToolInput(tool_use_id="u", tool="t", input={"html": "x" * INPUT_LIMIT}))
    assert body["input"] is None and body["truncated"] is True
    assert len(body["preview"]) == INPUT_LIMIT
    assert body["preview"].startswith('{"html":"xxx')


def test_approval_bodies() -> None:
    request = ApprovalRequest(
        request_id="r1",
        tool="lamp_tool",
        tier=Tier.PHYSICAL,
        arguments={"on": True},
        effect="physical",
        session_id="s",
        channel="web",
    )
    assert approval_body(request, expires_at=None) == {
        "type": "approval",
        "request": "r1",
        "tool": "lamp_tool",
        "tier": 2,
        "effect": "physical",
        "input": {"on": True},
        "truncated": False,
        "expires_at": None,
    }
    assert approval_decided("r1", Decision.TIMEOUT) == {
        "type": "approval_decided",
        "request": "r1",
        "decision": "timeout",
    }
    with pytest.raises(ValueError):
        approval_decided("r1", "maybe")


def test_the_other_bodies() -> None:
    assert turn_started("t", "s") == {"type": "turn", "turn": "t", "session": "s"}
    assert guard_body({"action": "refused", "type": "x", "reason": "locked"}) == {
        "type": "guard",
        "action": "refused",
        "reason": "locked",
    }
    assert widget_body("u", "T", "<p>") == {
        "type": "widget",
        "id": "u",
        "title": "T",
        "html": "<p>",
    }
    assert error_body("boom") == {"type": "error", "message": "boom"}


# -- ToolInput in a real stream ------------------------------------------------------------------


async def test_a_stream_announces_the_complete_input_before_the_tool_runs(config: Config) -> None:
    model = FakeModel([[ToolCall("clock_tool", {"city": "İzmir"})], "Saat 15:30."])
    agent = build_agent(config=config, model=model, tools=[clock_tool])

    turn = [event async for event in agent.stream("saat kaç")]

    kinds = [type(event).__name__ for event in turn if not isinstance(event, TextDelta)]
    assert kinds == ["ToolUseStarted", "ToolInput", "ToolFinished", "TurnEnd"]
    [started] = [e for e in turn if isinstance(e, ToolUseStarted)]
    [complete] = [e for e in turn if isinstance(e, ToolInput)]
    assert complete == ToolInput(
        tool_use_id=started.tool_use_id, tool="clock_tool", input={"city": "İzmir"}
    )
    assert render_turn_event(complete) is None  # the terminal shows nothing new


def test_tool_inputs_only_come_from_the_models_reply() -> None:
    use = {"toolUse": {"toolUseId": "u", "name": "t", "input": {"a": 1}}}
    assert tool_inputs_of({"message": {"role": "assistant", "content": [{"text": "x"}, use]}}) == [
        ToolInput(tool_use_id="u", tool="t", input={"a": 1})
    ]
    result = {"toolResult": {"toolUseId": "u", "status": "success", "content": []}}
    assert tool_inputs_of({"message": {"role": "user", "content": [result]}}) == []
    assert tool_inputs_of({"message": "not a message"}) == []
    assert tool_inputs_of({"data": "x"}) == []


# -- history -------------------------------------------------------------------------------------


async def test_history_of_a_recorded_session(config: Config) -> None:
    model = FakeModel(
        [
            [ToolCall("clock_tool", {"city": "Ankara"}), ToolCall("lamp_tool", {"on": True})],
            [ToolCall("render_ui", {"title": "Saat", "html": "<p>15:30</p>"})],
            "Tamam.",
            [ToolCall("lamp_tool", {"on": False})],
            "Lamba açık kaldı.",
        ]
    )
    store = MemorySessionStore()
    bus = EventBus()
    approver = ScriptedApprover([Decision.APPROVED, Decision.REJECTED])
    agent = build_agent(
        config=config,
        model=model,
        tools=[clock_tool, lamp_tool, render_ui],
        approver=approver,
        session_store=store,
        events=bus,
    )
    await agent.ask("saat ve lamba")
    await agent.ask("lambayı kapat")

    stored = store.list_messages(agent.session_id, AGENT_ID)
    blocks = history_blocks(stored, store.read_events(agent.session_id))

    assert [b["type"] for b in blocks] == [
        "user",
        "tool",
        "tool",
        "widget",
        "assistant",
        "user",
        "tool",
        "assistant",
    ]
    assert all(set(b) >= {"type", "at"} and b["type"] in BLOCK_TYPES for b in blocks)
    clock, lamp_on, widget, lamp_off = blocks[1], blocks[2], blocks[3], blocks[6]
    assert (clock["tool"], clock["tier"], clock["status"], clock["input"]) == (
        "clock_tool",
        0,
        "ok",
        {"city": "Ankara"},
    )
    assert clock["summary"] == "15:30 in Ankara"
    assert (lamp_on["status"], lamp_on["approval"], lamp_on["tier"]) == ("ok", "approved", 2)
    assert (lamp_off["status"], lamp_off["approval"]) == ("rejected", "rejected")
    assert widget == {
        "type": "widget",
        "id": widget["id"],
        "title": "Saat",
        "html": "<p>15:30</p>",
        "at": widget["at"],
    }
    assert blocks[0]["text"] == "saat ve lamba" and blocks[-1]["text"] == "Lamba açık kaldı."
    assert all(b["at"] is not None for b in blocks)


def test_history_without_timestamps_has_no_at_and_no_notices() -> None:
    messages = [
        {"role": "user", "content": [{"text": "hi"}]},
        {"role": "assistant", "content": [{"text": "a"}, {"text": "b"}]},
    ]
    notice = AgentEvent.create("notice", {"message": "n"}, session_id="s")
    assert history_blocks(messages, [notice]) == [
        {"type": "user", "text": "hi", "at": None},
        {"type": "assistant", "text": "a\n\nb", "at": None},
    ]


def test_notices_are_placed_by_time_and_unknown_results_are_kept() -> None:
    start = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)

    def stored(index: int, message: dict[str, Any]) -> SessionMessage:
        at = (start + timedelta(seconds=10 * index)).isoformat()
        return SessionMessage(message=message, message_id=index, created_at=at, updated_at=at)

    messages = [
        stored(0, {"role": "user", "content": [{"text": "q"}]}),
        stored(
            1,
            {
                "role": "user",
                "content": [
                    {"toolResult": {"toolUseId": "gone", "status": "error", "content": []}}
                ],
            },
        ),
        stored(2, {"role": "assistant", "content": [{"text": "a"}]}),
    ]
    notice = AgentEvent.create(
        "notice", {"message": "n"}, session_id="s", clock=lambda: start + timedelta(seconds=15)
    )
    blocks = history_blocks(messages, [notice])
    assert [b["type"] for b in blocks] == ["user", "tool", "notice", "assistant"]
    assert (blocks[1]["id"], blocks[1]["tool"], blocks[1]["status"]) == ("gone", "?", "error")


def test_a_render_ui_call_without_a_valid_input_stays_a_tool() -> None:
    messages = [
        {
            "role": "assistant",
            "content": [
                {"toolUse": {"toolUseId": "u", "name": "render_ui", "input": {"title": 3}}}
            ],
        }
    ]
    [block] = history_blocks(messages)
    assert block["type"] == "tool" and block["tool"] == "render_ui"


# -- the vectors the TypeScript half checks -------------------------------------------------------

generator = _load_generator()


def test_vectors_json_is_fresh() -> None:
    assert generator.main(["--check"]) == 0, (
        "cloud/shared/turn/vectors.json is stale: run "
        "`uv run python packages/tau-core/scripts/make_turn_vectors.py` and commit it"
    )


def test_the_vectors_cover_every_event_and_block_type() -> None:
    vectors = generator.make_vectors()
    assert {event["type"] for event in vectors["stream"]} == set(EVENT_TYPES)
    assert {block["type"] for block in vectors["history"]} == set(BLOCK_TYPES)
    assert [event["seq"] for event in vectors["stream"]] == list(range(len(vectors["stream"])))
    assert any(event.get("truncated") for event in vectors["stream"])
