"""The routines file (private, atomic, locked), the log and the settings table."""

from __future__ import annotations

import json
import os
import stat
import threading
import time
from datetime import time as clock_time
from pathlib import Path

import pytest
from routine_helpers import ZONE_NAME, local, routine_config
from tau_core import Config
from tau_routines import (
    Daily,
    Routine,
    RoutineConfigError,
    RoutineNotFound,
    RoutineSettings,
    RoutineStore,
    RoutineStoreError,
    routine_hash,
)
from tau_routines.store import LOG_BACKUPS, LOG_MAX_BYTES


def lamp(routine_id: str = "0a1b2c3d", **changes) -> Routine:
    arguments = changes.pop("arguments", {"on": True})
    fields = {
        "id": routine_id,
        "name": "Lamps on",
        "trigger": Daily(clock_time(7, 0)),
        "tool": "hall_lamp",
        "arguments": arguments,
        "enabled": True,
        "created": local(2026, 10, 1, 9, 0),
        "approved_hash": routine_hash(routine_id, "hall_lamp", arguments),
    }
    fields.update(changes)
    return Routine(**fields)


def mode(path: Path) -> int:
    return stat.S_IMODE(os.stat(path).st_mode)


def test_the_file_is_private_and_written_atomically(store: RoutineStore) -> None:
    assert store.load() == [] and store.stamp() is None
    with store.edit() as routines:
        routines.append(lamp())
    assert mode(store.root) == 0o700 and mode(store.path) == 0o600
    assert mode(store.lock_path) == 0o600
    assert [p.name for p in store.root.iterdir() if p.name.endswith(".tmp")] == []
    data = json.loads(store.path.read_text(encoding="utf-8"))
    assert data["version"] == 1
    [entry] = data["routines"]
    assert entry == {
        "id": "0a1b2c3d",
        "name": "Lamps on",
        "trigger": "daily 07:00",
        "tool": "hall_lamp",
        "arguments": {"on": True},
        "enabled": True,
        "created": "2026-10-01T06:00:00+00:00",
        "approved_hash": routine_hash("0a1b2c3d", "hall_lamp", {"on": True}),
        "last_slot": None,
        "failures": 0,
    }
    assert store.load() == [lamp()]


def test_an_unchanged_edit_writes_nothing_and_a_failing_one_nothing_at_all(
    store: RoutineStore,
) -> None:
    with store.edit() as routines:
        routines.append(lamp())
    before = store.stamp()
    with store.edit():
        pass
    assert store.stamp() == before
    with pytest.raises(RuntimeError), store.edit() as routines:
        routines.clear()
        raise RuntimeError("halfway")
    assert store.load() == [lamp()]


def test_every_write_changes_the_stamp(store: RoutineStore) -> None:
    with store.edit() as routines:
        routines.append(lamp())
    first = store.stamp()
    with store.edit() as routines:
        routines[0] = routines[0].with_changes(name="Hall")
    assert store.stamp() != first


def test_the_lock_serialises_writers(store: RoutineStore) -> None:
    order: list[str] = []
    inside = threading.Event()

    def slow_writer() -> None:
        with store.edit() as routines:
            inside.set()
            time.sleep(0.2)
            routines.append(lamp("11111111"))
            order.append("slow")

    thread = threading.Thread(target=slow_writer)
    thread.start()
    inside.wait(5)
    with store.edit() as routines:  # a second store object: another process, in effect
        order.append("second")
        routines.append(lamp("22222222"))
    thread.join()
    assert order == ["slow", "second"]
    assert [r.id for r in RoutineStore(store.root).load()] == ["11111111", "22222222"]


def test_the_lock_is_reentrant_in_one_thread(store: RoutineStore) -> None:
    with store.edit() as routines:
        routines.append(lamp())
        store.log("registered", routines[0])  # takes the same lock
    assert store.read_log()[-1]["status"] == "registered"


def test_an_unreadable_entry_is_skipped_and_kept(store: RoutineStore) -> None:
    with store.edit() as routines:
        routines.append(lamp())
    data = json.loads(store.path.read_text(encoding="utf-8"))
    broken = {"id": "deadbeef", "trigger": "hourly", "tool": "x"}
    data["routines"].append(broken)
    store.path.write_text(json.dumps(data), encoding="utf-8")

    assert store.load() == [lamp()]
    with store.edit() as routines:
        routines[0] = routines[0].with_changes(name="Hall")
        assert store.new_id(routines) not in ("0a1b2c3d", "deadbeef")
    data = json.loads(store.path.read_text(encoding="utf-8"))
    assert data["routines"][1] == broken


def test_unknown_keys_survive_a_rewrite(store: RoutineStore) -> None:
    with store.edit() as routines:
        routines.append(lamp())
    data = json.loads(store.path.read_text(encoding="utf-8"))
    data["routines"][0]["color"] = "warm"
    store.path.write_text(json.dumps(data), encoding="utf-8")
    with store.edit() as routines:
        routines[0] = routines[0].with_changes(name="Hall")
    assert json.loads(store.path.read_text(encoding="utf-8"))["routines"][0]["color"] == "warm"


@pytest.mark.parametrize(
    "text",
    ["not json", "[]", '{"routines": {}}', '{"version": 2, "routines": []}'],
)
def test_a_broken_file_is_an_error(store: RoutineStore, text: str) -> None:
    store.root.mkdir(parents=True)
    store.path.write_text(text, encoding="utf-8")
    with pytest.raises(RoutineStoreError):
        store.load()
    with pytest.raises(RoutineStoreError), store.edit():
        pass
    assert store.path.read_text(encoding="utf-8") == text


def test_find_by_id_or_name(store: RoutineStore) -> None:
    with store.edit() as routines:
        routines += [lamp("0a1b2c3d"), lamp("11111111", name="Coffee"), lamp("22222222")]
    assert store.get("11111111").name == "Coffee"
    assert store.get("coffee").id == "11111111"
    with pytest.raises(RoutineNotFound, match="Several routines"):
        store.get("Lamps on")
    with pytest.raises(RoutineNotFound, match="No routine"):
        store.get("tea")


def test_the_log_is_private_and_rotates(store: RoutineStore) -> None:
    routine = lamp()
    store.log("ok", routine, detail="x" * 1000)
    assert mode(store.log_path) == 0o600
    for _ in range(LOG_MAX_BYTES // 1000 * (LOG_BACKUPS + 2)):
        store.log("ok", routine, detail="x" * 1000)
    rotated = sorted(p.name for p in store.root.glob("log.jsonl*"))
    assert rotated == ["log.jsonl", "log.jsonl.1", "log.jsonl.2", "log.jsonl.3"]
    assert all(p.stat().st_size <= LOG_MAX_BYTES + 2000 for p in store.root.glob("log.jsonl*"))
    entries = store.read_log(limit=5, routine_id=routine.id)
    assert len(entries) == 5 and entries[-1]["status"] == "ok"
    assert store.read_log(routine_id="ffffffff") == []


def test_changing_the_call_clears_the_approval() -> None:
    routine = lamp()
    assert routine.approved
    assert routine.with_call(arguments={"on": True}) == routine  # the same call keeps it
    assert routine.with_changes(name="Hall").approved  # a new name changes no call
    for changed in (
        routine.with_call(arguments={"on": False}),
        routine.with_call(tool="write_note"),
        routine.with_call(trigger=Daily(clock_time(7, 30))),
    ):
        assert changed.approved_hash is None and not changed.approved
    # a call changed without with_call no longer matches its hash either
    assert not routine.with_changes(arguments={"on": False}).approved


# -- [component.routines] ------------------------------------------------------------------


def test_settings_default_to_the_local_zone_and_ten_minutes(tmp_path: Path) -> None:
    config = routine_config(tmp_path, table="")
    settings = RoutineSettings.from_config(config)
    assert settings.grace_minutes == 10 and settings.zone_name


def test_settings_read_the_table(config: Config) -> None:
    settings = RoutineSettings.from_config(config)
    assert settings.zone_name == ZONE_NAME and settings.grace_minutes == 10
    custom = RoutineSettings.from_mapping({"timezone": "UTC", "grace_minutes": 0})
    assert custom.zone_name == "UTC" and custom.grace_minutes == 0


@pytest.mark.parametrize(
    ("table", "complaint"),
    [
        ({"timezone": "Mars/Olympus"}, "not a known time zone"),
        ({"timezone": 3}, "zone name"),
        ({"grace_minutes": -1}, "grace_minutes"),
        ({"grace_minutes": True}, "grace_minutes"),
        ({"grace_minutes": 1441}, "grace_minutes"),
        ({"grace_minuts": 5}, "unknown keys: grace_minuts"),
    ],
)
def test_bad_settings_are_errors(table: dict, complaint: str) -> None:
    with pytest.raises(RoutineConfigError, match=complaint):
        RoutineSettings.from_mapping(table)
