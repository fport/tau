"""The hub process: service order, stop requests, and the real ``tau hub run`` under signals."""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner
from tau_core import Config
from tau_core.cli import cli
from tau_core.hub import UNCLEAN_EXIT, ControlApi, FakeLaunchctl, Hub, HubFiles

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # never via a proxy


def get_json(url: str, timeout: float = 5) -> tuple[int, Any]:
    try:
        with OPENER.open(url, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


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


# -- the real process ------------------------------------------------------------------------


def hub_env(config: Config, port: int) -> dict[str, str]:
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("AWS_", "ANTHROPIC_", "TAU_", "COV_CORE_"))
    }
    env.update(
        TAU_HOME=str(config.home),
        TAU_DATA_DIR=str(config.data_dir),
        TAU_HUB_PORT=str(port),
        PYTHONUNBUFFERED="1",
    )
    return env


@pytest.fixture
def spawn(config: Config) -> Iterator[Any]:
    procs: list[subprocess.Popen[str]] = []

    def start(port: int) -> subprocess.Popen[str]:
        proc = subprocess.Popen(
            [sys.executable, "-m", "tau_core", "hub", "run"],
            env=hub_env(config, port),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        procs.append(proc)
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                pytest.fail(f"hub exited early ({proc.returncode}): {proc.stdout.read()}")
            try:
                code, _ = get_json(f"http://127.0.0.1:{port}/health", timeout=1)
                if code == 200:
                    return proc
            except OSError:
                pass
            time.sleep(0.1)
        pytest.fail("hub did not answer /health in time")

    yield start
    for proc in procs:
        if proc.poll() is None:
            proc.kill()
            proc.wait()


def test_sigterm_stops_the_hub_cleanly(config: Config, spawn: Any) -> None:
    port = free_port()
    proc = spawn(port)
    code, health = get_json(f"http://127.0.0.1:{port}/health")
    assert code == 200 and health["pid"] == proc.pid
    proc.send_signal(signal.SIGTERM)
    out, _ = proc.communicate(timeout=30)
    assert proc.returncode == 0, out
    assert f"tau hub çalışıyor (pid {proc.pid}, profil ev)" in out
    assert out.rstrip().endswith("tau hub durdu.")
    files = HubFiles(config.hub_dir)
    state = files.read_state()
    assert state is not None and state.pid == proc.pid and state.stopped_at is not None
    assert not files.crash_reports.exists()


def test_kill_9_then_restart_reports_the_crash(config: Config, spawn: Any, tmp_path: Path) -> None:
    port = free_port()
    first = spawn(port)
    first.send_signal(signal.SIGKILL)
    first.wait(timeout=30)

    second = spawn(port)
    code, status = get_json(f"http://127.0.0.1:{port}/status")
    assert code == 200
    assert status["pid"] == second.pid
    assert status["last_crash"]["pid"] == first.pid
    assert status["last_crash"]["reason"] == UNCLEAN_EXIT

    env = {
        "TAU_HOME": str(config.home),
        "TAU_DATA_DIR": str(config.data_dir),
        "TAU_HUB_PORT": str(port),
        "HOME": str(tmp_path),
    }
    result = CliRunner().invoke(cli, ["hub", "status"], env=env, obj={"launchctl": FakeLaunchctl()})
    assert result.exit_code == 0, result.output
    assert f"tau hub çalışıyor (pid {second.pid})." in result.output
    assert f"  Son çökme: pid {first.pid}, son nabız " in result.output
    assert UNCLEAN_EXIT in result.output

    result = CliRunner().invoke(cli, ["hub", "stop"], env=env)
    assert result.exit_code == 0, result.output
    assert f"Durdurma sinyali gönderildi (pid {second.pid})." in result.output
    assert "tau hub durdu." in result.output
    second.wait(timeout=30)
    assert second.returncode == 0
    reports = HubFiles(config.hub_dir).read_crash_reports()
    assert [r.pid for r in reports] == [first.pid]
