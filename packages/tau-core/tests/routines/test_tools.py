"""The routine tools in a real tau turn: the channel's approver asks once, in plain words."""

from __future__ import annotations

import pytest
from routine_helpers import CATALOG, Clock
from tau_core import Config, Decision, Tier, ToolFinished, build_agent, effect_of, tier_of
from tau_core.routines import (
    TOOLS,
    RoutineContext,
    RoutineStore,
    add_routine,
    list_routines,
    remove_routine,
    routine_hash,
    tools,
)
from tau_core.routines.tools import ADD_EFFECT, describe_call
from tau_core.testing import FakeGuard, FakeModel, ScriptedApprover, ToolCall

LAMP_CALL = {
    "trigger": "daily 07:00 weekdays",
    "tool": "hall_lamp",
    "arguments": {"on": True, "brightness": 40},
    "name": "Hall lamp",
}


@pytest.fixture(autouse=True)
def routine_context(config: Config, clock: Clock) -> None:
    tools.context_factory = lambda: RoutineContext.from_config(config, tools=CATALOG, clock=clock)


def agent(config: Config, model: FakeModel, approver, guard=None):
    return build_agent(
        config=config,
        model=model,
        tools=[*CATALOG, *TOOLS],
        approver=approver,
        guard=guard if guard is not None else FakeGuard(state="unlocked", step_ups=[True]),
    )


async def turn(tau, prompt: str = "go") -> list[ToolFinished]:
    finished = []
    async for event in tau.stream(prompt):
        if isinstance(event, ToolFinished):
            finished.append(event)
    return finished


def test_tiers_and_effects() -> None:
    assert [tool.tool_name for tool in TOOLS] == ["add_routine", "list_routines", "remove_routine"]
    assert tier_of(add_routine) is Tier.PHYSICAL and effect_of(add_routine) == ADD_EFFECT
    assert tier_of(list_routines) is Tier.READ
    assert tier_of(remove_routine) is Tier.DIGITAL_WRITE


async def test_add_routine_in_a_chat_asks_once_with_the_whole_definition(
    config: Config, store: RoutineStore
) -> None:
    model = FakeModel([[ToolCall("add_routine", LAMP_CALL)], "Done."])
    approver = ScriptedApprover([Decision.APPROVED])
    guard = FakeGuard(state="unlocked", step_ups=[True])
    [finished] = await turn(agent(config, model, approver, guard))
    assert finished.status == "ok"

    [request] = approver.requests
    assert request.tool == "add_routine" and request.arguments == LAMP_CALL
    for words in (
        'Registers the routine "Hall lamp"',
        "every weekday (Monday to Friday) at 07:00, Europe/Istanbul time",
        "hall_lamp (tier 2, a physical action: Switches the hall lamp",
        "with exactly these arguments: on=true, brightness=40",
    ):
        assert words in request.effect, (words, request.effect)
    assert ("step_up", request.request_id) in guard.calls  # the guard's step-up ran too

    [routine] = store.load()
    assert routine.approved_hash == routine_hash(routine.id, "hall_lamp", LAMP_CALL["arguments"])
    result = model.calls[-1].messages[-1]["content"][0]["toolResult"]["content"][0]["text"]
    assert result.startswith(f'Registered the routine {routine.id} "Hall lamp"')
    assert "next run Mon 05.10.2026 07:00" in result


async def test_a_rejected_add_routine_stores_nothing(config: Config, store: RoutineStore) -> None:
    model = FakeModel([[ToolCall("add_routine", LAMP_CALL)], "Okay."])
    [finished] = await turn(agent(config, model, ScriptedApprover([Decision.REJECTED])))
    assert finished.status == "rejected"
    assert store.load() == []


async def test_a_failed_step_up_stores_nothing(config: Config, store: RoutineStore) -> None:
    model = FakeModel([[ToolCall("add_routine", LAMP_CALL)], "Okay."])
    guard = FakeGuard(state="unlocked", step_ups=[False])
    [finished] = await turn(agent(config, model, ScriptedApprover([Decision.APPROVED]), guard))
    assert finished.status == "rejected"
    assert store.load() == []


async def test_add_routine_replaces_asks_again_and_keeps_the_id(
    config: Config, store: RoutineStore
) -> None:
    approver = ScriptedApprover([Decision.APPROVED, Decision.APPROVED])
    model = FakeModel([[ToolCall("add_routine", LAMP_CALL)], "Done."])
    await turn(agent(config, model, approver))
    [routine] = store.load()

    change = {**LAMP_CALL, "arguments": {"on": False}, "replaces": routine.id}
    model = FakeModel([[ToolCall("add_routine", change)], "Done."])
    await turn(agent(config, model, approver))
    assert len(approver.requests) == 2
    assert f'Changes the routine {routine.id} ("Hall lamp")' in approver.requests[1].effect
    [changed] = store.load()
    assert changed.id == routine.id and changed.arguments == {"on": False}
    assert changed.approved_hash == routine_hash(routine.id, "hall_lamp", {"on": False})


@pytest.mark.parametrize(
    ("call", "complaint"),
    [
        ({**LAMP_CALL, "tool": "add_routine"}, "routines do not manage routines"),
        ({**LAMP_CALL, "tool": "teleport"}, "no tool named 'teleport'"),
        ({**LAMP_CALL, "trigger": "every 2 minutes"}, "5 to 10080"),
        ({**LAMP_CALL, "arguments": {"brightness": 3}}, "needs the argument(s) on"),
        ({**LAMP_CALL, "arguments": {"on": True, "colour": "red"}}, "no argument(s) colour"),
        ({**LAMP_CALL, "arguments": {"on": "yes"}}, "on must be of type boolean"),
        ({**LAMP_CALL, "trigger": "once 2026-10-01 07:00"}, "in the past"),
        ({**LAMP_CALL, "replaces": "ffffffff"}, "No routine has the id"),
    ],
)
def test_an_invalid_definition_is_described_and_not_stored(
    store: RoutineStore, call: dict, complaint: str
) -> None:
    text = describe_call(call)
    assert text.startswith("Registers a routine, but its definition is not valid")
    assert complaint in text, text
    answer = add_routine(**call)
    assert answer.startswith("Not registered") and complaint in answer, answer
    assert store.load() == []


def test_list_and_remove(store: RoutineStore) -> None:
    assert list_routines() == "The owner has no routines yet; add_routine registers one."
    add_routine(**LAMP_CALL)
    add_routine(trigger="every 30 minutes", tool="write_note", arguments={"text": "hi"})
    [lamp, note] = store.load()
    listing = list_routines()
    assert f'- {lamp.id} "Hall lamp" (active): every weekday (Monday to Friday) at 07:00 runs ' in (
        listing
    )
    assert "hall_lamp(on=true, brightness=40); next run Mon 05.10.2026 07:00." in listing
    assert f'{note.id} "write_note, every 30 minutes" (active)' in listing

    assert remove_routine("Hall lamp") == (
        f'Removed the routine {lamp.id} "Hall lamp"; it will not run again.'
    )
    assert remove_routine("Hall lamp").startswith("Not removed: No routine")
    assert [r.id for r in store.load()] == [note.id]
