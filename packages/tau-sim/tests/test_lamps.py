"""The lamps: ``[component.sim]``, the state file, the lock."""

from __future__ import annotations

import json
import stat
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from tau_core import Config, ConfigError
from tau_sim import (
    DEFAULT_LAMPS,
    Lamp,
    LampStore,
    SimConfigError,
    SimSettings,
    UnknownLamp,
    device_id,
    normalize_name,
)


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 1, 7, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def tick(self, minutes: int = 1) -> None:
        self.now += timedelta(minutes=minutes)


# -- config ------------------------------------------------------------------------------------


def test_the_desk_lamp_is_the_default(make_config) -> None:
    assert DEFAULT_LAMPS == ("desk",)
    assert SimSettings.from_config(make_config()).lamps == ("desk",)


def test_lamps_come_from_the_component_table(config: Config) -> None:
    assert SimSettings.from_config(config).lamps == ("desk", "living-room")
    assert LampStore.from_config(config).path == config.data_dir / "sim" / "lamps.json"


def test_no_lamps_is_allowed(make_config) -> None:
    assert SimSettings.from_config(make_config("[component.sim]\nlamps = []\n")).lamps == ()


@pytest.mark.parametrize(
    ("table", "message"),
    [
        ({"lamp": ["desk"]}, "unknown keys: lamp"),
        ({"lamps": "desk"}, "must be a list of names"),
        ({"lamps": ["desk", 3]}, "must be a list of names"),
        ({"lamps": ["Desk"]}, "is not valid"),
        ({"lamps": ["living room"]}, "is not valid"),
        ({"lamps": ["-desk"]}, "is not valid"),
        ({"lamps": ["x" * 41]}, "is not valid"),
        ({"lamps": ["desk", "desk"]}, "twice"),
    ],
)
def test_invalid_tables_are_config_errors(table: dict, message: str) -> None:
    with pytest.raises(SimConfigError, match=message) as info:
        SimSettings.from_mapping(table)
    assert isinstance(info.value, ConfigError)


@pytest.mark.parametrize(
    ("text", "slug"),
    [
        ("desk", "desk"),
        ("Desk", "desk"),
        (" desk lamp ", "desk"),
        ("Living room lamp", "living-room"),
        ("living_room", "living-room"),
        ("lamp", "lamp"),
    ],
)
def test_names_people_say(text: str, slug: str) -> None:
    assert normalize_name(text) == slug


# -- the state file ----------------------------------------------------------------------------


def store(tmp_path: Path, clock: Clock | None = None, lamps=("desk", "living-room")) -> LampStore:
    return LampStore(tmp_path / "sim", lamps, clock=clock or Clock())


def test_first_use_writes_every_lamp_off_privately(tmp_path: Path) -> None:
    clock = Clock()
    lamps = store(tmp_path, clock).lamps()
    assert lamps == [Lamp("desk", False, clock.now), Lamp("living-room", False, clock.now)]
    path = tmp_path / "sim" / "lamps.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE((tmp_path / "sim" / "lamps.lock").stat().st_mode) == 0o600
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data == {
        "version": 1,
        "lamps": {
            "desk": {"on": False, "updated": "2026-10-01T07:00:00+00:00"},
            "living-room": {"on": False, "updated": "2026-10-01T07:00:00+00:00"},
        },
    }
    # reading again keeps `updated` where it was and writes nothing
    signature = store(tmp_path).signature()
    clock.tick()
    assert store(tmp_path, clock).lamps()[0].updated == datetime(2026, 10, 1, 7, 0, tzinfo=UTC)
    assert store(tmp_path).signature() == signature


def test_set_switches_and_persists(tmp_path: Path) -> None:
    clock = Clock()
    lamps = store(tmp_path, clock)
    lamps.lamps()
    clock.tick(5)
    lamp, changed = lamps.set("desk", True)
    assert changed and lamp == Lamp("desk", True, clock.now)
    # another store (another process) sees it
    assert store(tmp_path).lamps()[0] == Lamp("desk", True, clock.now)
    assert store(tmp_path).lamps()[1].on is False


def test_set_to_the_same_state_writes_nothing(tmp_path: Path) -> None:
    lamps = store(tmp_path)
    lamps.set("desk", True)
    before = lamps.signature()
    lamp, changed = lamps.set("Desk lamp", True)
    assert not changed and lamp.on is True
    assert lamps.signature() == before


def test_an_unknown_lamp_changes_nothing(tmp_path: Path) -> None:
    lamps = store(tmp_path)
    with pytest.raises(UnknownLamp) as info:
        lamps.set("kitchen", True)
    assert info.value.known == ("desk", "living-room")
    assert not lamps.path.exists()


def test_a_broken_file_reads_as_all_off(tmp_path: Path) -> None:
    lamps = store(tmp_path)
    lamps.set("desk", True)
    lamps.path.write_text("{not json", encoding="utf-8")
    assert [lamp.on for lamp in lamps.lamps()] == [False, False]
    assert json.loads(lamps.path.read_text(encoding="utf-8"))["version"] == 1


def test_a_lamp_that_leaves_the_config_keeps_its_state(tmp_path: Path) -> None:
    store(tmp_path).set("living-room", True)
    assert [lamp.name for lamp in store(tmp_path, lamps=["desk"]).lamps()] == ["desk"]
    assert store(tmp_path).lamps()[1].on is True


def test_peek_neither_locks_nor_writes(tmp_path: Path) -> None:
    lamps = store(tmp_path)
    assert lamps.peek() == [] and not lamps.path.exists() and lamps.signature() is None
    lamps.set("desk", True)
    assert [(lamp.name, lamp.on) for lamp in lamps.peek()] == [
        ("desk", True),
        ("living-room", False),
    ]


def test_writers_never_lose_each_others_change(tmp_path: Path) -> None:
    names = [f"lamp-{i}" for i in range(12)]
    store(tmp_path, lamps=names).lamps()
    barrier = threading.Barrier(len(names))

    def switch(name: str) -> None:
        barrier.wait()
        # one store per thread: its own lock descriptor, like another process
        store(tmp_path, lamps=names).set(name, True)

    threads = [threading.Thread(target=switch, args=(name,)) for name in names]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert all(lamp.on for lamp in store(tmp_path, lamps=names).lamps())


def test_a_lamp_is_a_simulated_device() -> None:
    at = datetime(2026, 10, 1, 7, 0, tzinfo=UTC)
    device = Lamp("desk", True, at).device()
    assert device.id == device_id("desk") == "sim:lamp:desk"
    assert (device.name, device.kind, device.simulated) == ("desk", "lamp", True)
    assert device.state == {"on": True} and device.updated == at
