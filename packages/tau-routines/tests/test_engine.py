"""The engine beyond the acceptance criteria: once, lower tiers, timeouts, file changes."""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta

import pytest
from routine_helpers import CATALOG, Clock, SideEffects, local
from tau_core import Decision, EventBus, Tier, tau_tool
from tau_core.testing import record_events
from tau_routines import (
    RefusingApprover,
    RoutineContext,
    RoutineEngine,
    approved_call,
    commit,
    run_tool,
)
from tau_routines.engine import MIN_SLEEP, POLL_SECONDS


def register(context: RoutineContext, **fields) -> object:
    """Store a routine as an approved registration would (the approval is tested elsewhere)."""
    return commit(context.store, context.draft(**fields), context.now())


def engine_for(context: RoutineContext, clock: Clock, **kwargs) -> RoutineEngine:
    return RoutineEngine(context.store, context.settings, tools=CATALOG, clock=clock, **kwargs)


async def test_the_refusing_approver_refuses_everything() -> None:
    approver = RefusingApprover()
    assert await approver.decide(None) is Decision.REJECTED  # type: ignore[arg-type]
    assert "approved when registering" in approver.refusal_note


def test_the_exemption_covers_only_the_approved_call(context: RoutineContext) -> None:
    routine = register(context, trigger="daily 07:00", tool="hall_lamp", arguments={"on": True})
    exempt = approved_call(routine)
    assert exempt("hall_lamp", {"on": True}) is True
    assert exempt("hall_lamp", {"on": False}) is False
    assert exempt("write_note", {"on": True}) is False
    unapproved = approved_call(routine.with_changes(approved_hash=None))
    assert unapproved("hall_lamp", {"on": True}) is False


async def test_a_once_routine_fires_once_and_switches_off(
    context: RoutineContext, clock: Clock
) -> None:
    routine = register(
        context, trigger="once 2026-10-02 09:30", tool="hall_lamp", arguments={"on": True}
    )
    engine = engine_for(context, clock)
    clock.set(local(2026, 10, 2, 9, 30, 1))
    [firing] = await engine.tick()
    assert firing.status == "ok"
    clock.advance(days=3)
    assert await engine.tick() == []
    [stored] = context.store.load()
    assert stored.id == routine.id and not stored.enabled
    assert context.next_run(stored) is None


async def test_a_lower_tier_call_that_does_not_match_is_refused_by_the_engine(
    context: RoutineContext, clock: Clock
) -> None:
    register(context, trigger="daily 07:00", tool="write_note", arguments={"text": "hi"})
    data = json.loads(context.store.path.read_text(encoding="utf-8"))
    data["routines"][0]["arguments"]["text"] = "changed"
    context.store.path.write_text(json.dumps(data), encoding="utf-8")
    engine = engine_for(context, clock)
    clock.set(local(2026, 10, 3, 7, 0, 1))
    [firing] = await engine.tick()
    assert firing.status == "refused" and "does not match" in firing.detail
    assert SideEffects.notes == []


async def test_an_unknown_tool_is_refused(context: RoutineContext, clock: Clock) -> None:
    register(context, trigger="daily 07:00", tool="hall_lamp", arguments={"on": True})
    engine = RoutineEngine(
        context.store, context.settings, tools=[], clock=clock
    )  # the tool is gone, for example its package was removed
    clock.set(local(2026, 10, 3, 7, 0, 1))
    [firing] = await engine.tick()
    assert firing.status == "refused" and "not registered" in firing.detail


async def test_a_tool_that_hangs_fails_after_the_timeout(
    context: RoutineContext, clock: Clock
) -> None:
    @tau_tool(tier=Tier.DIGITAL_WRITE)
    async def stuck() -> str:
        """Never finishes (test tool)."""
        await asyncio.Event().wait()
        return "never"

    context = RoutineContext(context.settings, {"stuck": stuck}, context.store, clock)
    register(context, trigger="daily 07:00", tool="stuck", arguments={})
    engine = RoutineEngine(
        context.store, context.settings, tools=[stuck], clock=clock, run_timeout=0.01
    )
    clock.set(local(2026, 10, 3, 7, 0, 1))
    [firing] = await engine.tick()
    assert firing.status == "failed" and "did not finish" in firing.detail


async def test_run_tool_reports_the_result_and_errors() -> None:
    from tau_core.builtin_tools import demo_physical_action

    ok, summary = await run_tool(demo_physical_action, {"action": "wave"}, "t1")
    assert ok and summary.startswith("Demo action simulated: wave")
    ok, summary = await run_tool(demo_physical_action, {}, "t2")
    assert not ok and "Error" in summary


async def test_a_change_between_reading_and_firing_waits_for_the_next_tick(
    context: RoutineContext, clock: Clock
) -> None:
    routine = register(context, trigger="daily 07:00", tool="hall_lamp", arguments={"on": True})
    engine = engine_for(context, clock)
    engine.refresh()
    with context.store.edit() as routines:  # tau routine edit, between the engine's read and tick
        routines[0] = routines[0].with_changes(arguments={"on": False})
    engine._stamp = context.store.stamp()  # the engine has not noticed yet
    clock.set(local(2026, 10, 3, 7, 0, 1))
    assert await engine.tick() == []
    assert SideEffects.lamp == []
    [stored] = context.store.load()
    assert stored.last_slot is None and stored.id == routine.id


async def test_the_engine_picks_up_file_changes_and_sleeps_until_the_next_slot(
    context: RoutineContext, clock: Clock
) -> None:
    engine = engine_for(context, clock)
    assert engine.refresh() == [] and engine.delay() == POLL_SECONDS
    # written by another process
    register(context, trigger="daily 08:00", tool="hall_lamp", arguments={"on": True})
    clock.set(local(2026, 10, 3, 7, 59, 50))
    assert len(engine.refresh()) == 1
    assert engine.delay() == pytest.approx(10.0)
    clock.set(local(2026, 10, 3, 8, 0, 5))
    assert engine.delay() == MIN_SLEEP  # due: tick right away


async def test_a_broken_file_keeps_the_routines_and_slows_down(
    context: RoutineContext, clock: Clock
) -> None:
    register(context, trigger="daily 07:00", tool="hall_lamp", arguments={"on": True})
    engine = engine_for(context, clock)
    engine.refresh()
    context.store.path.write_text("{ not json", encoding="utf-8")
    clock.set(local(2026, 10, 3, 7, 0, 1))
    assert await engine.tick() == []  # cannot record the slot, so nothing runs
    assert len(engine.routines) == 1 and SideEffects.lamp == []
    assert engine.delay() == POLL_SECONDS


async def test_run_ticks_and_sleeps_with_the_injected_sleep(
    context: RoutineContext, clock: Clock
) -> None:
    register(context, trigger="every 5 minutes", tool="write_note", arguments={"text": "tick"})
    sleeps: list[float] = []

    async def sleep(seconds: float) -> None:
        if len(sleeps) >= 40:
            raise asyncio.CancelledError
        sleeps.append(seconds)
        clock.advance(seconds=seconds)

    events = EventBus()
    seen = record_events(events, "routine")
    engine = RoutineEngine(
        context.store, context.settings, tools=CATALOG, clock=clock, sleep=sleep, events=events
    )
    with pytest.raises(asyncio.CancelledError):
        await engine.run()
    elapsed = timedelta(seconds=sum(sleeps))
    assert elapsed >= timedelta(minutes=10)
    assert [e.data["status"] for e in seen] == ["ok"] * len(SideEffects.notes)
    assert len(SideEffects.notes) == elapsed // timedelta(minutes=5)
    assert all(MIN_SLEEP <= s <= POLL_SECONDS for s in sleeps)
