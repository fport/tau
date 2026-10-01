"""The ``routines`` hub service, started with a stand-in hub (no lock, no control API)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from routine_helpers import CATALOG, Clock, SideEffects, local, routine_config
from tau_core import Config
from tau_core.testing import record_events
from tau_routines import RoutineConfigError, RoutineContext, RoutinesService, commit
from tau_routines.service import make_service


class StubHub:
    """What the service uses of :class:`tau_core.hub.daemon.Hub`."""

    def __init__(self) -> None:
        self.sources: list[Any] = []

    def add_status_source(self, source: Any) -> None:
        self.sources.append(source)


def test_the_entry_point_builds_the_service(config: Config) -> None:
    from tau_core import registry

    factory = registry.discover(registry.HUB_SERVICES_GROUP)["routines"]
    assert isinstance(factory(config), RoutinesService)
    assert isinstance(make_service(config), RoutinesService)
    assert make_service(config).name == "routines"


async def test_the_service_fires_routines_and_reports_status(
    config: Config, clock: Clock, context: RoutineContext
) -> None:
    commit(
        context.store,
        context.draft(trigger="daily 08:10", tool="hall_lamp", arguments={"on": True}),
        context.now(),
    )
    advanced = asyncio.Event()

    async def sleep(seconds: float) -> None:
        clock.advance(seconds=seconds)
        if clock() >= local(2026, 10, 2, 8, 11):
            advanced.set()
            await asyncio.Event().wait()  # stay asleep until the hub stops the service

    service = RoutinesService(config, tools=CATALOG, clock=clock, sleep=sleep)
    seen = record_events(service.events, "routine")
    hub = StubHub()
    await service.start(hub)  # type: ignore[arg-type]
    try:
        await asyncio.wait_for(advanced.wait(), 5)
        [source] = hub.sources
        status = source()["routines"]
        assert status["total"] == 1 and status["enabled"] == 1
        assert status["next_at"] == "2026-10-03T05:10:00+00:00"
    finally:
        await service.stop()
    assert SideEffects.lamp == [{"on": True, "brightness": 100}]
    assert [event.data["status"] for event in seen] == ["ok"]
    await service.stop()  # twice is fine


async def test_a_bad_table_stops_the_start(tmp_path: Path) -> None:
    config = routine_config(tmp_path, table="grace_minutes = -5\n")
    service = RoutinesService(config, tools=CATALOG)
    with pytest.raises(RoutineConfigError):
        await service.start(StubHub())  # type: ignore[arg-type]
    assert service.status() == {"routines": None}
    await service.stop()
