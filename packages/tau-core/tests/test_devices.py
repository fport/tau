"""Device sources in the public API: ``DeviceState``, ``DeviceSource`` and ``to_json``."""

from __future__ import annotations

import dataclasses
import json
from datetime import UTC, datetime, timedelta, timezone

import pytest
import tau_core
from tau_core import DeviceSource, DeviceState, device_to_json
from tau_core.devices import to_json

AT = datetime(2026, 10, 1, 7, 0, tzinfo=UTC)


def lamp(**overrides) -> DeviceState:
    values = {
        "id": "sim:lamp:desk",
        "name": "desk",
        "kind": "lamp",
        "simulated": True,
        "state": {"on": True},
        "updated": AT,
    }
    values.update(overrides)
    return DeviceState(**values)


def test_the_names_are_public() -> None:
    for name in ("DeviceSource", "DeviceState", "device_to_json"):
        assert name in tau_core.__all__ and hasattr(tau_core, name), name
    assert device_to_json is to_json


def test_device_state_is_frozen() -> None:
    device = lamp()
    with pytest.raises(dataclasses.FrozenInstanceError):
        device.name = "kitchen"  # type: ignore[misc]


def test_updated_is_normalized_to_utc() -> None:
    istanbul = timezone(timedelta(hours=3))
    device = lamp(updated=datetime(2026, 10, 1, 10, 0, tzinfo=istanbul))
    assert device.updated == AT and device.updated.tzinfo is UTC


@pytest.mark.parametrize(
    "overrides",
    [
        {"updated": datetime(2026, 10, 1, 7, 0)},  # naive
        {"updated": 1759302000.0},
        {"id": ""},
        {"name": None},
        {"kind": ""},
        {"simulated": "yes"},
        {"state": [("on", True)]},
    ],
)
def test_invalid_fields_are_refused(overrides: dict) -> None:
    with pytest.raises(ValueError):
        lamp(**overrides)


def test_to_json_is_json_safe_and_a_copy() -> None:
    device = lamp(state={"on": True, "color": {"h": 30}})
    payload = to_json(device)
    assert payload == {
        "id": "sim:lamp:desk",
        "name": "desk",
        "kind": "lamp",
        "simulated": True,
        "state": {"on": True, "color": {"h": 30}},
        "updated": "2026-10-01T07:00:00+00:00",
    }
    assert json.loads(json.dumps(payload)) == payload
    payload["state"]["color"]["h"] = 200
    assert device.state["color"]["h"] == 30


class ListSource:
    """A source with no base class: the protocol is structural."""

    def __init__(self) -> None:
        self.callbacks: list = []

    def devices(self) -> list[DeviceState]:
        return [lamp()]

    def subscribe(self, callback):
        self.callbacks.append(callback)
        return lambda: self.callbacks.remove(callback)


class NotASource:
    def devices(self) -> list[DeviceState]:
        return []


def test_device_source_is_structural() -> None:
    source = ListSource()
    assert isinstance(source, DeviceSource)
    assert not isinstance(NotASource(), DeviceSource)
    seen: list[DeviceState] = []
    unsubscribe = source.subscribe(seen.append)
    for callback in source.callbacks:
        callback(lamp(state={"on": False}))
    unsubscribe()
    assert [device.state for device in seen] == [{"on": False}]
    assert source.callbacks == []
