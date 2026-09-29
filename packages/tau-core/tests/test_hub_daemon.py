"""The hub process: service order, stop requests, control API while running."""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
from typing import Any

import pytest
from tau_core import Config
from tau_core.hub import ControlApi, Hub, HubFiles

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # never via a proxy


def get_json(url: str, timeout: float = 5) -> tuple[int, Any]:
    try:
        with OPENER.open(url, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


class Recorder:
    def __init__(self, name: str, log: list[str], *, fail_stop: bool = False):
        self.name = name
        self.log = log
        self.fail_stop = fail_stop

    async def start(self, hub: Hub) -> None:
        self.log.append(f"start {self.name}")

    async def stop(self) -> None:
        self.log.append(f"stop {self.name}")
        if self.fail_stop:
            raise RuntimeError("stop failed")


class Stopper:
    name = "stopper"

    async def start(self, hub: Hub) -> None:
        hub.request_stop()

    async def stop(self) -> None:
        pass


def test_services_start_in_order_and_stop_in_reverse(config: Config) -> None:
    log: list[str] = []
    hub = Hub(config, services=[Recorder("a", log), Recorder("b", log)])
    hub.add_service(Recorder("c", log))
    hub.add_service(Stopper())
    assert hub.run() == 0
    assert log == ["start a", "start b", "start c", "stop c", "stop b", "stop a"]


def test_a_failing_stop_does_not_skip_the_others(config: Config) -> None:
    log: list[str] = []
    hub = Hub(config, services=[Recorder("a", log), Recorder("b", log, fail_stop=True), Stopper()])
    assert hub.run() == 0
    assert log == ["start a", "start b", "stop b", "stop a"]
    assert HubFiles(config.hub_dir).read_state().stopped_at is not None


def test_request_stop_before_run(config: Config) -> None:
    hub = Hub(config)
    hub.request_stop()
    assert hub.run() == 0


def test_status_sources_extend_status(config: Config) -> None:
    hub = Hub(config)
    hub.add_status_source(lambda: {"spend": {"today_usd": 0.0}})
    hub.add_status_source(lambda: 1 / 0)  # a broken source is logged and skipped
    status = hub.status()
    for key in (
        "role",
        "profile",
        "version",
        "started_at",
        "heartbeat_at",
        "last_crash",
        "approvals_pending",
        "nodes",
    ):
        assert key in status
    assert status["approvals_pending"] == 0
    assert status["nodes"] is None
    assert status["spend"] == {"today_usd": 0.0}


def test_hub_in_a_thread_serves_health_and_status(config: Config) -> None:
    hub = Hub(config)
    api = ControlApi(0, hub.status)
    hub.add_service(api)
    result: list[int] = []
    thread = threading.Thread(target=lambda: result.append(hub.run()))
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while (api.port == 0 or hub.state is None) and time.monotonic() < deadline:
            time.sleep(0.02)
        code, health = get_json(f"{api.url}/health")
        assert code == 200 and health["ok"] is True and health["pid"] == os.getpid()
        code, status = get_json(f"{api.url}/status")
        assert code == 200
        assert status["pid"] == os.getpid()
        assert status["profile"] == "ev" and status["role"] == "hub"
        assert status["started_at"] == hub.state.started_at
    finally:
        hub.request_stop()
        thread.join(timeout=10)
    assert result == [0]
    with pytest.raises(OSError):
        OPENER.open(f"{api.url}/health", timeout=2)
