"""The acceptance criteria of issue 181, end to end: CLI registration, the engine, the gate."""

from __future__ import annotations

import asyncio
import json
import socket

import pytest
from routine_helpers import CATALOG, Clock, SideEffects, local, run_cli
from tau_core import Config, Decision
from tau_core.routines import RoutineEngine, RoutineSettings, RoutineStore, routine_hash
from tau_core.testing import ScriptedApprover, record_events


def test_one_approval_then_it_fires_on_the_next_weekday_without_asking(
    config: Config, clock: Clock, store: RoutineStore
) -> None:
    approver = ScriptedApprover([Decision.APPROVED])
    result = run_cli(
        config,
        "add",
        "daily 07:00 weekdays",
        "demo_physical_action",
        "action=turn on the desk lamp",
        "--name",
        "Lamps on",
        clock=clock,
        approver=approver,
    )
    assert result.exit_code == 0, result.output
    [routine] = store.load()
    assert f"Added the routine {routine.id}" in result.output
    assert "Next run: 05.10.2026 07:00" in result.output  # Friday 08:00 → Monday 07:00

    # One approval, of the whole definition in plain words.
    [request] = approver.requests
    assert request.tool == "add_routine" and int(request.tier) == 2
    assert request.arguments == {
        "trigger": "daily 07:00 weekdays",
        "tool": "demo_physical_action",
        "arguments": {"action": "turn on the desk lamp"},
        "name": "Lamps on",
    }
    for words in (
        'Registers the routine "Lamps on"',
        "every weekday (Monday to Friday) at 07:00, Europe/Istanbul time",
        "demo_physical_action (tier 2, a physical action",
        'action="turn on the desk lamp"',
    ):
        assert words in request.effect, (words, request.effect)
    assert routine.approved_hash == routine_hash(
        routine.id, "demo_physical_action", {"action": "turn on the desk lamp"}
    )

    engine = RoutineEngine(store, RoutineSettings.from_config(config), tools=CATALOG, clock=clock)
    events = record_events(engine.events)
    for day in (2, 3, 4):  # Friday after 07:00, Saturday, Sunday: nothing
        clock.set(local(2026, 10, day, 7, 0, 30))
        assert _tick(engine) == [], day
    clock.set(local(2026, 10, 5, 7, 0, 5))  # Monday
    [firing] = _tick(engine)
    assert (firing.status, firing.slot) == ("ok", local(2026, 10, 5, 7, 0))
    assert "Demo action simulated: turn on the desk lamp" in firing.detail

    assert len(approver.requests) == 1  # nobody was asked again
    kinds = [event.kind for event in events]
    assert "approval" not in kinds  # an exempt call never reaches an approver
    [call] = [event for event in events if event.kind == "tool_call"]
    assert call.data["approval"] == "exempt" and call.data["status"] == "ok"
    [fired_event] = [event for event in events if event.kind == "routine"]
    assert fired_event.data["id"] == routine.id and fired_event.data["status"] == "ok"
    assert store.read_log(routine_id=routine.id)[-1]["status"] == "ok"

    clock.set(local(2026, 10, 5, 7, 1))  # the same slot never fires twice
    assert _tick(engine) == []


def _tick(engine: RoutineEngine) -> list:
    return asyncio.run(engine.tick())


def _add_lamp(config: Config, clock: Clock, **kwargs) -> tuple:
    approver = ScriptedApprover([Decision.APPROVED])
    result = run_cli(
        config,
        "add",
        "daily 07:00",
        "hall_lamp",
        "on=true",
        "brightness=40",
        clock=clock,
        approver=approver,
        **kwargs,
    )
    assert result.exit_code == 0, result.output
    [routine] = RoutineStore.for_config(config).load()
    return routine, approver


def test_a_changed_argument_asks_again(config: Config, clock: Clock, store: RoutineStore) -> None:
    routine, _ = _add_lamp(config, clock)

    rejecting = ScriptedApprover([Decision.REJECTED])
    result = run_cli(config, "edit", routine.id, "brightness=80", clock=clock, approver=rejecting)
    assert result.exit_code == 1
    assert "not approved" in result.output
    [request] = rejecting.requests
    assert request.arguments["arguments"] == {"on": True, "brightness": 80}
    assert f"Changes the routine {routine.id}" in request.effect
    assert store.load() == [routine]  # a rejected change leaves the routine as it was

    approving = ScriptedApprover([Decision.APPROVED])
    result = run_cli(config, "edit", routine.id, "brightness=80", clock=clock, approver=approving)
    assert result.exit_code == 0, result.output
    assert len(approving.requests) == 1
    [changed] = store.load()
    assert changed.id == routine.id and changed.arguments == {"on": True, "brightness": 80}
    assert changed.approved_hash == routine_hash(routine.id, "hall_lamp", changed.arguments)
    assert changed.approved_hash != routine.approved_hash

    for change in (("--trigger", "daily 07:30"), ("--tool", "write_note", "text=hi")):
        asked = ScriptedApprover([Decision.APPROVED])
        result = run_cli(config, "edit", routine.id, *change, clock=clock, approver=asked)
        assert result.exit_code == 0, result.output
        assert len(asked.requests) == 1, change

    # Renaming, pausing, resuming and removing ask nothing.
    silent = ScriptedApprover()
    for args in (
        ("edit", routine.id, "--name", "Hall"),
        ("pause", routine.id),
        ("resume", "Hall"),
        ("remove", routine.id, "--yes"),
    ):
        result = run_cli(config, *args, clock=clock, approver=silent)
        assert result.exit_code == 0, (args, result.output)
    assert silent.requests == [] and store.load() == []


def test_a_routine_whose_hash_does_not_match_its_call_is_refused_by_the_gate(
    config: Config, clock: Clock, store: RoutineStore, engine: RoutineEngine
) -> None:
    routine, approver = _add_lamp(config, clock)
    # The file changes behind the registration: the stored hash no longer covers the call.
    data = json.loads(store.path.read_text(encoding="utf-8"))
    data["routines"][0]["arguments"]["brightness"] = 100
    store.path.write_text(json.dumps(data), encoding="utf-8")

    events = record_events(engine.events)
    clock.set(local(2026, 10, 3, 7, 0, 1))
    [firing] = _tick(engine)
    assert firing.status == "refused"
    assert SideEffects.lamp == []  # not run
    [decision] = [e for e in events if e.kind == "approval"]
    assert decision.data["decision"] == "rejected" and decision.data["channel"] == "routine"
    [call] = [e for e in events if e.kind == "tool_call"]
    assert call.data["status"] == "rejected" and call.data["approval"] == "rejected"
    assert len(approver.requests) == 1  # the registration's, and no other


def test_it_fires_with_no_network_and_no_model(
    config: Config, clock: Clock, store: RoutineStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    routine, _ = _add_lamp(config, clock)

    def no_network(*args, **kwargs):
        raise AssertionError("a routine firing must not touch the network")

    def no_model(*args, **kwargs):
        raise AssertionError("a routine firing must not build a model")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    monkeypatch.setattr(socket, "getaddrinfo", no_network)
    import tau_core.agent
    import tau_core.models

    monkeypatch.setattr(tau_core.models, "resolve_model", no_model)
    monkeypatch.setattr(tau_core.agent, "resolve_model", no_model)
    # No model is configured at all: the roles name a provider without credentials.
    toml = config.home / "tau.toml"
    toml.write_text(toml.read_text().replace('provider = "fake"', 'provider = "anthropic"'))
    bare = Config.load(config.home, env={"TAU_DATA_DIR": str(config.data_dir)})

    engine = RoutineEngine(
        RoutineStore.for_config(bare),
        RoutineSettings.from_config(bare),
        tools=CATALOG,
        clock=clock,
    )
    clock.set(local(2026, 10, 3, 7, 0, 2))
    [firing] = _tick(engine)
    assert firing.status == "ok"
    assert SideEffects.lamp == [{"on": True, "brightness": 40}]


def test_missed_firings_within_the_grace_run_once_and_older_ones_are_logged(
    config: Config, clock: Clock, store: RoutineStore, engine: RoutineEngine
) -> None:
    approver = ScriptedApprover([Decision.APPROVED])
    clock.set(local(2026, 10, 2, 6, 0))
    result = run_cli(
        config, "add", "every 5 minutes", "write_note", "text=tick", clock=clock, approver=approver
    )
    assert result.exit_code == 0, result.output
    [routine] = store.load()

    # The hub was off from 06:00 to 06:32: slots 06:05 ... 06:30. Grace is 10 minutes.
    clock.set(local(2026, 10, 2, 6, 32))
    missed, ran = _tick(engine)
    assert (missed.status, missed.count, missed.slot) == ("missed", 4, local(2026, 10, 2, 6, 20))
    assert (ran.status, ran.count, ran.slot) == ("ok", 2, local(2026, 10, 2, 6, 30))
    assert SideEffects.notes == ["tick"]  # once, not once per slot
    assert [e["status"] for e in store.read_log(routine_id=routine.id)] == [
        "registered",
        "missed",
        "ok",
    ]


def test_a_firing_older_than_the_grace_is_only_logged(
    config: Config, clock: Clock, store: RoutineStore, engine: RoutineEngine
) -> None:
    _add_lamp(config, clock)
    clock.set(local(2026, 10, 3, 7, 10, 1))  # 10 minutes and a second late
    [firing] = _tick(engine)
    assert (firing.status, firing.count) == ("missed", 1)
    assert SideEffects.lamp == []
    [routine] = store.load()
    assert routine.enabled and routine.last_slot == local(2026, 10, 3, 7, 0)

    clock.set(local(2026, 10, 4, 7, 9, 59))  # within the grace: it runs
    [firing] = _tick(engine)
    assert firing.status == "ok" and len(SideEffects.lamp) == 1


def test_three_failures_in_a_row_pause_the_routine(
    config: Config, clock: Clock, store: RoutineStore, engine: RoutineEngine
) -> None:
    approver = ScriptedApprover([Decision.APPROVED])
    clock.set(local(2026, 10, 2, 9, 0))
    result = run_cli(
        config, "add", "every 5 minutes", "broken_door", clock=clock, approver=approver
    )
    assert result.exit_code == 0, result.output
    events = record_events(engine.events, "routine")

    statuses = []
    for minute in (5, 10, 15, 20):
        clock.set(local(2026, 10, 2, 9, minute, 1))
        statuses += [f.status for f in _tick(engine)]
    assert statuses == ["failed", "failed", "failed", "paused"]
    assert SideEffects.broken_calls == 3  # paused: the fourth slot did not run
    [routine] = store.load()
    assert not routine.enabled and routine.failures == 3
    assert store.read_log(routine_id=routine.id)[-1]["status"] == "paused"
    assert "paused after 3 failed firings in a row" in store.read_log()[-1]["detail"]
    assert [e.data["status"] for e in events] == ["failed", "failed", "failed", "paused"]


def test_a_success_clears_the_failure_count(
    config: Config, clock: Clock, store: RoutineStore, engine: RoutineEngine
) -> None:
    clock.set(local(2026, 10, 2, 9, 0))
    approver = ScriptedApprover([Decision.APPROVED])
    assert (
        run_cli(
            config, "add", "every 5 minutes", "flaky_feeder", clock=clock, approver=approver
        ).exit_code
        == 0
    )
    SideEffects.flaky_script = [False, False, True, False, False]
    statuses = []
    for minute in (5, 10, 15, 20, 25):
        clock.set(local(2026, 10, 2, 9, minute, 1))
        statuses += [f.status for f in _tick(engine)]
    assert statuses == ["failed", "failed", "ok", "failed", "failed"]
    [routine] = store.load()
    assert routine.enabled and routine.failures == 2
