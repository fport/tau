"""A tau agent on the spine store: a turn, then a "container restart" (a new store on the same
spine) that resumes the session with its history, tool calls and approvals intact."""

from __future__ import annotations

from pathlib import Path

from tau_cloud.sessions import SpineSessionStore
from tau_cloud.testing import FakeCloud
from tau_core import Decision, Tier, build_agent, tau_tool
from tau_core.sessions import new_session_id
from tau_core.testing import FakeModel, ScriptedApprover, ToolCall, test_config
from tau_net.spine import SpineClient
from tau_net.testing import DEFAULT_HUB_TOKEN, FakeSpine


@tau_tool(tier=Tier.READ)
def clock_tool() -> str:
    """Tell the time."""
    return "15:30"


@tau_tool(tier=Tier.PHYSICAL, effect="Turns the desk lamp on or off.")
def lamp(state: str) -> str:
    """Turn the desk lamp on or off.

    Args:
        state: "on" or "off".
    """
    return f"lamp {state}"


def restarted_store(spine: FakeSpine) -> SpineSessionStore:
    """What a new container builds: a new client and store on the same spine."""
    return SpineSessionStore(SpineClient(spine.url, DEFAULT_HUB_TOKEN, transport=spine))


async def test_a_restart_resumes_the_session(
    tmp_path: Path, spine: FakeSpine, cloud: FakeCloud, spine_store: SpineSessionStore
) -> None:
    config = test_config(tmp_path)
    session_id = new_session_id()
    approver = ScriptedApprover([Decision.REJECTED])
    first = build_agent(
        config=config,
        model=FakeModel(
            [
                [ToolCall("clock_tool", {})],
                [ToolCall("lamp", {"state": "on"})],
                "It is 15:30. I did not turn the lamp on.",
            ]
        ),
        tools=[clock_tool, lamp],
        approver=approver,
        session_id=session_id,
        session_store=spine_store,
        channel="telegram",
    )
    reply = await first.ask("What time is it? And turn the lamp on.")
    assert reply == "It is 15:30. I did not turn the lamp on."
    assert len(approver.requests) == 1  # the tier-2 call asked, and was refused
    first.close()

    store = restarted_store(spine)
    model = FakeModel(["You asked for the time and the lamp."])
    second = build_agent(
        config=config,
        model=model,
        tools=[clock_tool, lamp],
        approver=ScriptedApprover(),
        session_id=session_id,
        session_store=store,
        channel="telegram",
    )
    assert second.messages == first.messages
    assert await second.ask("What did I ask?") == "You asked for the time and the lamp."
    sent = model.calls[0].messages
    assert sent[0]["content"][0]["text"] == "What time is it? And turn the lamp on."
    assert len(sent) == 7  # user, tool use, result, tool use, refusal, reply, new question

    meta = store.read_meta(session_id)
    assert meta["title"] == "What time is it? And turn the lamp on."
    assert meta["channel"] == "telegram" and meta["profile"] == "home"
    kinds = [event.kind for event in store.read_events(session_id)]
    assert kinds == ["tool_call", "approval", "tool_call"]
    summary = store.list_sessions()[0]
    assert summary.session_id == session_id and summary.message_count == 8
    assert summary.channel == "telegram"
    assert [m["message"]["role"] for m in cloud.message_data(session_id, "tau")][-2:] == [
        "user",
        "assistant",
    ]
