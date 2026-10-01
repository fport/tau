"""The ``sim`` hub service: a ``DeviceSource`` whose changes reach subscribers."""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
from datetime import UTC, datetime

import pytest
from tau_core import Config, DeviceSource, DeviceState, HubService, device_to_json
from tau_core.hub.daemon import Hub
from tau_core.sim import LampStore, SimConfigError, SimService, make_service


def test_the_service_is_a_device_source_and_a_hub_service(config: Config) -> None:
    service = make_service(config)
    assert isinstance(service, SimService)
    assert isinstance(service, DeviceSource)
    assert isinstance(service, HubService) and service.name == "sim"


def test_devices_are_the_simulated_lamps(config: Config) -> None:
    devices = make_service(config).devices()
    assert [device.id for device in devices] == ["sim:lamp:desk", "sim:lamp:living-room"]
    assert all(isinstance(device, DeviceState) for device in devices)
    assert all(device.simulated and device.kind == "lamp" for device in devices)
    assert [device.state for device in devices] == [{"on": False}, {"on": False}]
    payload = device_to_json(devices[0])
    assert payload["simulated"] is True and payload["state"] == {"on": False}


def test_a_change_reaches_subscribers_once(config: Config) -> None:
    service = make_service(config)
    service.prime()
    seen: list[DeviceState] = []
    other: list[DeviceState] = []
    unsubscribe = service.subscribe(seen.append)
    service.subscribe(other.append)

    assert service.check() == []  # nothing changed yet
    LampStore.from_config(config).set("desk", True)
    [change] = service.check()
    assert change.id == "sim:lamp:desk" and change.state == {"on": True} and change.simulated
    assert seen == [change] and other == [change]
    assert service.check() == []  # told once

    unsubscribe()
    unsubscribe()  # harmless twice
    LampStore.from_config(config).set("desk", False)
    service.check()
    assert len(seen) == 1 and [d.state for d in other] == [{"on": True}, {"on": False}]


def test_a_failing_subscriber_does_not_stop_the_others(
    config: Config, caplog: pytest.LogCaptureFixture
) -> None:
    service = make_service(config)
    service.prime()

    def broken(state: DeviceState) -> None:
        raise RuntimeError("boom")

    seen: list[DeviceState] = []
    service.subscribe(broken)
    service.subscribe(seen.append)
    LampStore.from_config(config).set("living-room", True)
    with caplog.at_level(logging.ERROR, logger="tau_core.sim.service"):
        service.check()
    assert [device.name for device in seen] == ["living-room"]
    assert "subscriber failed on sim:lamp:living-room" in caplog.text


def test_the_first_look_without_prime_tells_nobody(config: Config) -> None:
    LampStore.from_config(config).set("desk", True)
    service = make_service(config)
    seen: list[DeviceState] = []
    service.subscribe(seen.append)
    assert service.check() == [] and seen == []
    LampStore.from_config(config).set("desk", False)
    assert [device.state for device in service.check()] == [{"on": False}]


def switch_in_another_process(config: Config, name: str, on: bool) -> None:
    """What a ``lamp_set`` in ``tau tui`` does to the file, from a separate interpreter."""
    code = (
        "import sys\n"
        "from tau_core import Config\n"
        "from tau_core.sim import LampStore\n"
        "config = Config.load(sys.argv[1])\n"
        "LampStore.from_config(config).set(sys.argv[2], sys.argv[3] == 'on')\n"
    )
    env = {**os.environ, "TAU_DATA_DIR": str(config.data_dir)}
    env.pop("TAU_HOME", None)
    subprocess.run(
        [sys.executable, "-c", code, str(config.home), name, "on" if on else "off"],
        env=env,
        check=True,
        timeout=60,
    )


def test_a_running_service_sees_a_change_made_in_another_process(config: Config) -> None:
    service = SimService(config, poll_seconds=0.02)
    hub = Hub(config)

    async def main() -> list[DeviceState]:
        loop = asyncio.get_running_loop()
        arrived = asyncio.Event()
        seen: list[DeviceState] = []

        def on_change(state: DeviceState) -> None:
            assert asyncio.get_running_loop() is loop  # callbacks run on the hub's loop
            seen.append(state)
            arrived.set()

        await service.start(hub)
        try:
            service.subscribe(on_change)
            assert hub.status()["sim"]["lamps"] == {
                "desk": {"on": False},
                "living-room": {"on": False},
            }
            await asyncio.to_thread(switch_in_another_process, config, "living-room", True)
            await asyncio.wait_for(arrived.wait(), timeout=10)
            status = hub.status()["sim"]
            assert status["simulated"] is True and status["watching"] is True
            assert status["lamps"]["living-room"] == {"on": True}
            assert status["subscribers"] == 1 and status["last_error"] is None
        finally:
            await service.stop()
        assert service.status()["watching"] is False
        return seen

    [change] = asyncio.run(main())
    assert change.id == "sim:lamp:living-room" and change.state == {"on": True}
    assert change.simulated and change.updated <= datetime.now(UTC)


def test_an_invalid_table_fails_the_factory(make_config) -> None:
    config = make_config('[component.sim]\nlamps = ["Desk Lamp"]\n')
    with pytest.raises(SimConfigError):
        make_service(config)


def test_poll_seconds_must_be_positive(config: Config) -> None:
    with pytest.raises(ValueError):
        SimService(config, poll_seconds=0)
