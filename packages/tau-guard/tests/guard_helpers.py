"""Shared helpers: a guard config, the enrollment marker, a hub on port 0 with the service.

Nothing here talks to the live hub: every config points at a port the test bound, under its
own ``tmp_path``.
"""

from __future__ import annotations

import json
import os
import socket
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tau_core import Config, HubGuard
from tau_core.config import HubConfig
from tau_core.guard import ENROLLED_MARKER, GuardTurn
from tau_core.hub import ControlApi, Hub, HubClient
from tau_core.testing import test_config
from tau_guard.service import GuardService
from tau_guard.testing import FakeClock, FakePresence, fake_worker_command, write_script

TURN = GuardTurn(channel="tui", session_id="s1", client_id="c1")


def write_marker(config: Config, enrollment: str = "E1") -> None:
    path = config.data_dir / ENROLLED_MARKER
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"v": 1, "enrollment": enrollment}), encoding="utf-8")


def guard_config(tmp_path: Path, *, enrolled: bool = True, **table: Any) -> Config:
    config = test_config(tmp_path, component_tables={"guard": {"enabled": True, **table}})
    if enrolled:
        write_marker(config)
    return config


def until(condition: Callable[[], bool], timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("timed out")
        time.sleep(0.01)


async def until_async(condition: Callable[[], bool], timeout: float = 10.0) -> None:
    """``until`` for a test on the event loop: yields while it waits."""
    import asyncio

    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("timed out")
        await asyncio.sleep(0.01)


class FakeHub:
    """Enough of ``Hub`` for a service unit test: status sources and ``find_service``."""

    def __init__(self, services: dict[str, Any] | None = None) -> None:
        self.sources: list[Callable[[], dict]] = []
        self.services = services or {}

    def add_status_source(self, source: Callable[[], dict]) -> None:
        self.sources.append(source)

    def find_service(self, name: str) -> Any:
        return self.services.get(name)

    def status(self) -> dict:
        data: dict = {}
        for source in self.sources:
            data.update(source())
        return data


@dataclass
class Running:
    """A real ``Hub`` in a thread: the ``ControlApi`` on port 0 and the guard service."""

    config: Config
    service: GuardService
    api: ControlApi
    hub: Hub
    clock: FakeClock
    presence: FakePresence
    script: Path
    thread: threading.Thread

    @property
    def guard(self) -> HubGuard:
        return HubGuard(self.config)

    @property
    def client(self) -> HubClient:
        return HubClient(self.config)

    def script_runs(self, *runs: list[dict]) -> None:
        write_script(self.script, list(runs))

    def advance(self, seconds: float, *, step: float = 2.0) -> None:
        """Move the fake clock in reflex-loop steps, ticking after each."""
        left = seconds
        while left > 0:
            delta = min(step, left)
            self.clock.advance(delta)
            self.service.tick()
            left -= delta

    def stop(self) -> None:
        self.hub.request_stop()
        self.thread.join(timeout=15)


@contextmanager
def running_hub(
    tmp_path: Path,
    *,
    config: Config | None = None,
    runs: list[list[dict]] | None = None,
    clock: FakeClock | None = None,
    presence: FakePresence | None = None,
    attempt_timeout: float = 10.0,
    **service_kwargs: Any,
) -> Iterator[Running]:
    config = config or guard_config(tmp_path)
    clock = clock or FakeClock()
    presence = presence or FakePresence()
    work = tmp_path / "worker"
    work.mkdir(exist_ok=True)
    script = write_script(work / "script.json", runs or [[]])
    service = GuardService(
        config,
        clock=clock,
        presence=presence,
        worker_command=fake_worker_command(script),
        platform=service_kwargs.pop("platform", "darwin"),
        reflex_loop=service_kwargs.pop("reflex_loop", False),
        attempt_timeout=attempt_timeout,
        **service_kwargs,
    )
    hub = Hub(config)
    api = ControlApi(0, hub.status)
    hub.add_service(api)
    hub.add_service(service, optional=True)
    thread = threading.Thread(target=hub.run, name="test-hub", daemon=True)
    thread.start()
    until(lambda: api.port != 0 and service.mode != "idle")
    port_config = config.with_overrides(hub=HubConfig(control_port=api.port, heartbeat_seconds=5))
    handle = Running(port_config, service, api, hub, clock, presence, script, thread)
    try:
        yield handle
    finally:
        handle.stop()


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def cli_config(tmp_path: Path, *, active: bool = True, port: int | None = None) -> Config:
    """A home whose tau.toml points at a port nothing listens on (never 7877)."""
    config = test_config(tmp_path)
    toml = config.home / "tau.toml"
    text = toml.read_text().replace("control_port = 7877", f"control_port = {port or free_port()}")
    if active:
        text += "\n[component.guard]\nenabled = true\n"
    toml.write_text(text)
    os.environ["TAU_DATA_DIR"] = str(config.data_dir)
    loaded = Config.load(config.home)
    if active:
        write_marker(loaded)
    return loaded
