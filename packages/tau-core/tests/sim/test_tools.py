"""The lamp tools: tiers, approval through the tier gate, and the simulated marking."""

from __future__ import annotations

import asyncio

import pytest
from tau_core import (
    Config,
    Decision,
    EventBus,
    Tier,
    TierGate,
    ToolCatalog,
    ToolFinished,
    build_agent,
    effect_of,
    tier_of,
)
from tau_core.sim import SET_EFFECT, TOOLS, LampStore, tools
from tau_core.sim.tools import lamp_list, lamp_set
from tau_core.testing import FakeGuard, FakeModel, ScriptedApprover, ToolCall

TURN_ON = [ToolCall("lamp_set", {"name": "desk", "on": True})]
LIST = [ToolCall("lamp_list", {})]


def run(agent, prompt: str) -> list:
    async def collect() -> list:
        return [event async for event in agent.stream(prompt)]

    return asyncio.run(collect())


def tool_result(model: FakeModel, call: int) -> str:
    """The text of the tool result the model saw on its ``call``-th request."""
    return model.calls[call].messages[-1]["content"][0]["toolResult"]["content"][0]["text"]


def desk(config: Config) -> bool:
    return LampStore.from_config(config).lamps()[0].on


def unlocked_guard() -> FakeGuard:
    """An owner guard that admits and passes one step-up (it never approves anything)."""
    return FakeGuard(state="unlocked", step_ups=[True])


def test_tiers_and_effects() -> None:
    assert [tool.tool_name for tool in TOOLS] == ["lamp_list", "lamp_set"]
    assert tier_of(lamp_list) is Tier.READ
    assert tier_of(lamp_set) is Tier.PHYSICAL
    assert effect_of(lamp_set) == SET_EFFECT
    assert "simulated" in SET_EFFECT and "no real device" in SET_EFFECT
    schema = lamp_set.tool_spec["inputSchema"]["json"]
    assert sorted(schema["properties"]) == ["name", "on"]
    assert schema["properties"]["on"]["type"] == "boolean"
    for tool in TOOLS:
        assert "simulated" in tool.tool_spec["description"]


def test_turn_on_the_desk_lamp_asks_then_switches_it(use_config: Config) -> None:
    """Acceptance: "turn on the desk lamp" asks for approval, then switches the simulated
    lamp; ``lamp_list`` shows it on."""
    approver = ScriptedApprover([Decision.APPROVED])
    model = FakeModel([TURN_ON, LIST, "The desk lamp is on. It is simulated."])
    agent = build_agent(
        config=use_config, model=model, tools=TOOLS, approver=approver, guard=unlocked_guard()
    )
    events = run(agent, "Turn on the desk lamp.")

    [request] = approver.requests
    assert request.tool == "lamp_set" and request.tier is Tier.PHYSICAL
    assert request.arguments == {"name": "desk", "on": True}
    assert request.effect == SET_EFFECT
    finished = [event for event in events if isinstance(event, ToolFinished)]
    assert [(e.tool, e.status, e.approval) for e in finished] == [
        ("lamp_set", "ok", "approved"),
        ("lamp_list", "ok", None),
    ]
    assert desk(use_config) is True
    assert tool_result(model, 1).startswith("The simulated lamp desk is now on.")
    listing = tool_result(model, 2)
    assert "- desk: on (simulated)" in listing
    assert "- living-room: off (simulated)" in listing


@pytest.mark.parametrize("decision", [Decision.REJECTED, Decision.TIMEOUT])
def test_without_approval_the_lamp_stays_off(use_config: Config, decision: Decision) -> None:
    approver = ScriptedApprover([decision])
    model = FakeModel([TURN_ON, "I did not switch it."])
    agent = build_agent(
        config=use_config, model=model, tools=TOOLS, approver=approver, guard=unlocked_guard()
    )
    events = run(agent, "Turn on the desk lamp.")
    assert len(approver.requests) == 1
    [finished] = [event for event in events if isinstance(event, ToolFinished)]
    assert finished.tool == "lamp_set" and finished.approval == decision.value
    assert desk(use_config) is False
    assert "lamp_set" in tool_result(model, 1)


async def test_the_tier_gate_asks_for_lamp_set_and_not_for_lamp_list() -> None:
    approver = ScriptedApprover([Decision.APPROVED])
    gate = TierGate(
        ToolCatalog(TOOLS),
        approver,
        EventBus(),
        session_id="s1",
        channel="tui",
        guard=unlocked_guard(),
    )
    assert await gate.check("lamp_list", {}, tool_use_id="t1") == (True, None, None)
    assert approver.requests == []
    allowed, refusal, approval = await gate.check(
        "lamp_set", {"name": "desk", "on": True}, tool_use_id="t2"
    )
    assert (allowed, refusal, approval) == (True, None, "approved")
    [request] = approver.requests
    assert request.tool == "lamp_set" and request.effect == SET_EFFECT
    # the scripted approver is exhausted: the next call is refused, never approved by default
    allowed, refusal, approval = await gate.check(
        "lamp_set", {"name": "desk", "on": False}, tool_use_id="t3"
    )
    assert not allowed and approval == "rejected" and refusal


def test_a_locked_guard_refuses_lamp_set_before_anyone_is_asked(use_config: Config) -> None:
    approver = ScriptedApprover([Decision.APPROVED])
    model = FakeModel([TURN_ON, "Locked."])
    agent = build_agent(
        config=use_config,
        model=model,
        tools=TOOLS,
        approver=approver,
        guard=FakeGuard(state="locked", admissions=[True, "locked"]),
    )
    run(agent, "Turn on the desk lamp.")
    assert approver.requests == []
    assert desk(use_config) is False


# -- every answer says it is simulated -------------------------------------------------------


def approved_set(config: Config, name: str, on: bool) -> str:
    """One ``lamp_set`` call through a turn whose approval is scripted as approved."""
    approver = ScriptedApprover([Decision.APPROVED])
    model = FakeModel([[ToolCall("lamp_set", {"name": name, "on": on})], "Done."])
    agent = build_agent(
        config=config, model=model, tools=TOOLS, approver=approver, guard=unlocked_guard()
    )
    run(agent, "Switch it.")
    assert len(approver.requests) == 1
    return tool_result(model, 1)


def answers(make_config) -> dict[str, str]:
    """Every answer the tools can give, one per path."""
    config = make_config('[component.sim]\nlamps = ["desk", "living-room"]\n')
    tools.config_factory = lambda: config
    out = {
        "list": lamp_list(),
        "set on": approved_set(config, "desk", True),
        "set again": approved_set(config, "Desk lamp", True),
        "set off": approved_set(config, "desk", False),
        "unknown": approved_set(config, "kitchen", True),
    }
    empty = make_config("[component.sim]\nlamps = []\n")
    tools.config_factory = lambda: empty
    out |= {"no lamps": lamp_list(), "no lamps set": approved_set(empty, "desk", True)}
    broken = make_config('[component.sim]\nlamps = ["Desk Lamp"]\n')
    tools.config_factory = lambda: broken
    out |= {"bad config list": lamp_list(), "bad config set": approved_set(broken, "desk", True)}
    return out


def test_every_answer_marks_the_lamp_simulated(make_config) -> None:
    results = answers(make_config)
    for path, answer in results.items():
        assert "simulated" in answer.lower(), path
    assert results["set on"].startswith("The simulated lamp desk is now on.")
    assert results["set again"].startswith("The simulated lamp desk was already on")
    assert results["set off"].startswith("The simulated lamp desk is now off.")
    assert results["unknown"] == (
        "No simulated lamp is called 'kitchen'; nothing changed. "
        "Simulated lamps: desk, living-room."
    )
    assert results["no lamps"].startswith("No simulated lamps are configured")
    assert "Simulated lamps: none" in results["no lamps set"]
    assert "is not valid" in results["bad config list"]
    assert "is not valid" in results["bad config set"]
