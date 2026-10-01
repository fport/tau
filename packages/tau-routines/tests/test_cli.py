"""``tau routine``: the approval and guard path, and the free commands."""

from __future__ import annotations

from pathlib import Path

import pytest
from routine_helpers import Clock, SideEffects, local, routine_config, run_cli
from tau_core import Config, Decision
from tau_core.testing import FakeGuard, ScriptedApprover
from tau_routines import RoutineStore


def add(config: Config, clock: Clock, *args: str, approver=None, **kwargs):
    approver = approver or ScriptedApprover([Decision.APPROVED])
    return run_cli(config, "add", *args, clock=clock, approver=approver, **kwargs), approver


def test_add_reads_values_by_the_tools_schema(
    config: Config, clock: Clock, store: RoutineStore
) -> None:
    result, _ = add(config, clock, "daily 07:00", "hall_lamp", "on=true", "brightness=40")
    assert result.exit_code == 0, result.output
    result, _ = add(config, clock, "daily 08:00", "write_note", "text=42")
    assert result.exit_code == 0, result.output
    result, _ = add(config, clock, "daily 09:00", "hall_lamp", "--args", '{"on": false}')
    assert result.exit_code == 0, result.output
    lamp, note, off = store.load()
    assert lamp.arguments == {"on": True, "brightness": 40}
    assert note.arguments == {"text": "42"}  # a text argument stays text
    assert off.arguments == {"on": False}
    assert lamp.name == "hall_lamp, daily 07:00"


@pytest.mark.parametrize(
    ("args", "complaint"),
    [
        (("daily 7am", "hall_lamp", "on=true"), "HH:MM"),
        (("daily 07:00", "teleport"), "no tool named 'teleport'"),
        (("daily 07:00", "hall_lamp", "on"), "'on' is not NAME=VALUE"),
        (("daily 07:00", "hall_lamp", "--args", "{"), "--args is not valid JSON"),
        (("daily 07:00", "hall_lamp", "--args", "[1]"), "--args must be a JSON object"),
        (("daily 07:00", "hall_lamp"), "needs the argument(s) on"),
        (("daily 07:00", "remove_routine", "routine=x"), "routines do not manage routines"),
    ],
)
def test_add_refuses_a_bad_definition_before_asking(
    config: Config, clock: Clock, store: RoutineStore, args: tuple, complaint: str
) -> None:
    result, approver = add(config, clock, *args)
    assert result.exit_code == 1
    assert complaint in result.output, result.output
    assert approver.requests == [] and store.load() == []


def test_a_rejected_add_stores_nothing(config: Config, clock: Clock, store: RoutineStore) -> None:
    approver = ScriptedApprover([Decision.REJECTED])
    result, _ = add(config, clock, "daily 07:00", "hall_lamp", "on=true", approver=approver)
    assert result.exit_code == 1
    assert "Nothing was added: the routine was not approved." in result.output
    assert len(approver.requests) == 1 and store.load() == []


def test_without_a_terminal_nobody_can_approve(
    config: Config, clock: Clock, store: RoutineStore
) -> None:
    result = run_cli(config, "add", "daily 07:00", "hall_lamp", "on=true", clock=clock, input="y\n")
    assert result.exit_code == 1  # CliRunner's stdin is not a terminal: "y" approves nothing
    assert store.load() == []


def test_the_owner_guard_steps_up_after_the_approval(
    config: Config, clock: Clock, store: RoutineStore
) -> None:
    guard = FakeGuard(state="unlocked", step_ups=[True])
    result, approver = add(config, clock, "daily 07:00", "hall_lamp", "on=true", guard=guard)
    assert result.exit_code == 0, result.output
    assert ("step_up", approver.requests[0].request_id) in guard.calls
    assert len(store.load()) == 1


def test_a_failed_step_up_stores_nothing(config: Config, clock: Clock, store: RoutineStore) -> None:
    guard = FakeGuard(state="unlocked", step_ups=[False])
    result, approver = add(config, clock, "daily 07:00", "hall_lamp", "on=true", guard=guard)
    assert result.exit_code == 1 and len(approver.requests) == 1
    assert store.load() == []


def test_a_locked_guard_refuses_without_asking(
    config: Config, clock: Clock, store: RoutineStore
) -> None:
    guard = FakeGuard(state="locked")
    result, approver = add(config, clock, "daily 07:00", "hall_lamp", "on=true", guard=guard)
    assert result.exit_code == 1
    assert approver.requests == [] and store.load() == []


def test_list_pause_resume_and_log(config: Config, clock: Clock, store: RoutineStore) -> None:
    result = run_cli(config, "list", clock=clock)
    assert result.exit_code == 0 and "No routines yet" in result.output
    add(config, clock, "daily 07:00 weekdays", "hall_lamp", "on=true", "--name", "Hall")
    [routine] = store.load()

    result = run_cli(config, "list", clock=clock)
    assert result.exit_code == 0, result.output
    assert result.output.splitlines() == [
        f'{routine.id}  "Hall"  [active]',
        "    daily 07:00 weekdays  →  hall_lamp on=true",
        "    next run: 05.10.2026 07:00   failures in a row: 0",
        "Times are Europe/Istanbul time.",
    ]

    result = run_cli(config, "pause", "hall", clock=clock)
    assert result.exit_code == 0 and f"Paused the routine {routine.id}" in result.output
    assert "[paused]" in run_cli(config, "list", clock=clock).output
    assert "next run: none" in run_cli(config, "list", clock=clock).output

    clock.set(local(2026, 10, 5, 9, 0))  # resumed after Monday's slot: it was skipped
    result = run_cli(config, "resume", routine.id, clock=clock)
    assert result.exit_code == 0 and "Next run: 06.10.2026 07:00." in result.output
    [resumed] = store.load()
    assert resumed.last_slot == local(2026, 10, 5, 9, 0)

    result = run_cli(config, "log", "Hall", clock=clock)
    assert result.exit_code == 0, result.output
    statuses = [line.split("  ")[3] for line in result.output.splitlines()]
    assert statuses == ["registered", "paused", "resumed"]
    assert "02.10.2026 08:00" in result.output.splitlines()[0]


def test_a_removed_routine_is_still_in_the_log_by_its_id(
    config: Config, clock: Clock, store: RoutineStore
) -> None:
    add(config, clock, "daily 07:00", "hall_lamp", "on=true")
    [routine] = store.load()
    result = run_cli(config, "remove", routine.id, clock=clock, input="n\n")
    assert "Nothing was removed." in result.output and len(store.load()) == 1
    result = run_cli(config, "remove", routine.id, clock=clock, input="y\n")
    assert result.exit_code == 0 and "Removed the routine" in result.output
    assert store.load() == []
    result = run_cli(config, "log", routine.id, clock=clock)
    assert result.exit_code == 0 and "removed" in result.output.splitlines()[-1]
    assert run_cli(config, "log", "nothing-like-this", clock=clock).exit_code == 1


def test_edit_with_nothing_to_change(config: Config, clock: Clock, store: RoutineStore) -> None:
    add(config, clock, "daily 07:00", "hall_lamp", "on=true")
    [routine] = store.load()
    approver = ScriptedApprover()
    result = run_cli(config, "edit", routine.id, clock=clock, approver=approver)
    assert result.exit_code == 1 and "Nothing to change" in result.output
    assert approver.requests == []


def test_edit_offers_an_unapproved_routine_for_approval_again(
    config: Config, clock: Clock, store: RoutineStore
) -> None:
    add(config, clock, "daily 07:00", "hall_lamp", "on=true")
    with store.edit() as routines:
        routines[0] = routines[0].with_changes(approved_hash=None)
    [routine] = store.load()
    assert "[not approved]" in run_cli(config, "list", clock=clock).output
    approver = ScriptedApprover([Decision.APPROVED])
    result = run_cli(config, "edit", routine.id, clock=clock, approver=approver)
    assert result.exit_code == 0, result.output
    assert len(approver.requests) == 1
    [approved] = store.load()
    assert approved.approved


def test_a_finished_once_routine_can_still_be_renamed(
    config: Config, clock: Clock, store: RoutineStore
) -> None:
    add(config, clock, "once 2026-10-02 09:00", "hall_lamp", "on=true")
    clock.set(local(2026, 10, 3, 9, 0))
    [routine] = store.load()
    result = run_cli(config, "edit", routine.id, "--name", "Done lamp", clock=clock)
    assert result.exit_code == 0, result.output
    assert store.load()[0].name == "Done lamp"
    result = run_cli(config, "edit", routine.id, "on=false", clock=clock)
    assert result.exit_code == 1 and "in the past" in result.output


def test_the_ui_language_applies(config: Config, clock: Clock, store: RoutineStore) -> None:
    toml = config.home / "tau.toml"
    toml.write_text(toml.read_text().replace('language = "en"', 'language = "tr"'))
    result = run_cli(config, "list", clock=clock)
    assert result.exit_code == 0 and "Henüz rutin yok" in result.output


def test_a_bad_table_is_a_configuration_error(tmp_path: Path, clock: Clock) -> None:
    config = routine_config(tmp_path, table='timezone = "Mars/Olympus"\n')
    result = run_cli(config, "list", clock=clock)
    assert result.exit_code == 2 and "not a known time zone" in result.output


def test_nothing_ran_while_registering(config: Config, clock: Clock) -> None:
    add(config, clock, "daily 07:00", "hall_lamp", "on=true")
    assert SideEffects.lamp == []
