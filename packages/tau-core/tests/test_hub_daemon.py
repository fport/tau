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
from tau_core.testing import test_config

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # never via a proxy


def get_json(url: str, timeout: float = 5, token: str | None = None) -> tuple[int, Any]:
    from urllib.parse import urlsplit

    from tau_core.hub.control import auth_headers

    headers = auth_headers(token, "GET", urlsplit(url).path) if token else {}
    request = urllib.request.Request(url, headers=headers)
    try:
        with OPENER.open(request, timeout=timeout) as response:
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


def test_find_service_sees_only_started_services(config: Config) -> None:
    seen: dict[str, Any] = {}

    class Failing:
        name = "failing"

        async def start(self, hub: Hub) -> None:
            raise RuntimeError("no network today")

        async def stop(self) -> None:
            raise AssertionError("never started, never stopped")

    class Later:
        name = "later"

        async def start(self, hub: Hub) -> None:
            seen["failing"] = hub.find_service("failing")
            seen["earlier"] = hub.find_service("earlier")
            seen["self"] = hub.find_service("later")  # not started yet: its own start is running
            seen["stopper"] = hub.find_service("stopper")  # starts after this one

        async def stop(self) -> None:
            pass

    log: list[str] = []
    earlier = Recorder("earlier", log)
    hub = Hub(config, services=[earlier])
    hub.add_service(Failing(), optional=True)
    hub.add_service(Later())
    hub.add_service(Stopper())
    assert hub.find_service("earlier") is None  # nothing has started before run()
    assert hub.run() == 0
    assert seen == {"failing": None, "earlier": earlier, "self": None, "stopper": None}
    assert hub.find_service("earlier") is None  # and nothing is running after it


def test_a_service_cannot_replace_health_or_status(tmp_path: Path, caplog) -> None:
    import logging

    class Spoof:
        name = "spoof"

        async def start(self, hub: Hub) -> None:
            api = hub.find_service("control-api")
            assert isinstance(api, ControlApi)
            api.add_route("GET", "/health", lambda r: (200, {"ok": True, "pid": 1, "x": True}))

        async def stop(self) -> None:
            raise AssertionError("never started, never stopped")

    from tau_core.hub.cli import assemble_hub

    hub, api = assemble_hub(test_config(tmp_path), port=0)
    hub.add_service(Spoof(), optional=True)
    result: list[int] = []
    with caplog.at_level(logging.WARNING):
        thread = threading.Thread(target=lambda: result.append(hub.run()))
        thread.start()
        try:
            deadline = time.monotonic() + 10
            while (api.port == 0 or hub.state is None) and time.monotonic() < deadline:
                time.sleep(0.02)
            code, payload = get_json(f"{api.url}/health")
            assert code == 200 and payload["pid"] == os.getpid() and "x" not in payload
            assert hub.find_service("spoof") is None
        finally:
            hub.request_stop()
            thread.join(timeout=10)
    assert result == [0]
    assert "hub service spoof failed to start; running without it" in caplog.text
    assert "GET /health is already registered" in caplog.text


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
        assert status["profile"] == "home" and status["role"] == "hub"
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
    assert f"tau hub is running (pid {proc.pid}, profile home)" in out
    assert out.rstrip().endswith("tau hub stopped.")
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
    assert f"tau hub is running (pid {second.pid})." in result.output
    assert f"  Last crash: pid {first.pid}, last heartbeat " in result.output
    assert UNCLEAN_EXIT in result.output

    result = CliRunner().invoke(cli, ["hub", "stop"], env=env)
    assert result.exit_code == 0, result.output
    assert f"Stop signal sent (pid {second.pid})." in result.output
    assert "tau hub stopped." in result.output
    second.wait(timeout=30)
    assert second.returncode == 0
    reports = HubFiles(config.hub_dir).read_crash_reports()
    assert [r.pid for r in reports] == [first.pid]


# -- tau.hub_services components (issues 058 / 065) --------------------------------------------


def run_assembled(config: Config, check) -> int:
    """Run ``assemble_hub(config, port=0)`` in a thread, call ``check(hub, api)``, stop it."""
    from tau_core.hub.cli import assemble_hub

    hub, api = assemble_hub(config, port=0)
    result: list[int] = []
    thread = threading.Thread(target=lambda: result.append(hub.run()))
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while (api.port == 0 or hub.state is None) and time.monotonic() < deadline:
            time.sleep(0.02)
        check(hub, api)
    finally:
        hub.request_stop()
        thread.join(timeout=10)
    return result[0]


def test_discovered_service_adds_status_keys_and_routes(tmp_path: Path) -> None:
    config = test_config(tmp_path, component_tables={"example": {"greeting": "hi"}})
    seen: dict[str, Any] = {}

    def check(hub: Hub, api: ControlApi) -> None:
        names = [s.name for s in hub.services]
        assert names[0] == "control-api"  # the control API first
        # tau-core ships spend and telegram; other workspace packages (tau-net) add their own
        assert {"example", "spend", "telegram"} <= set(names[1:])
        seen["service"] = hub.find_service("example")
        code, status = get_json(f"{api.url}/status")
        assert code == 200 and status["example"] == {"profile": "home"}
        # Without a token the Telegram poller starts idle and the hub runs on.
        assert status["telegram"] == {
            "configured": False,
            "reason": "TELEGRAM_BOT_TOKEN is not set",
        }
        assert get_json(f"{api.url}/example")[0] == 403  # a service's route is protected
        token = (config.hub_dir / "control.token").read_text()
        code, payload = get_json(f"{api.url}/example", token=token)
        assert code == 200
        assert payload == {"example": True, "component": {"greeting": "hi"}}

    assert run_assembled(config, check) == 0
    assert seen["service"].started and seen["service"].stopped


def test_disabled_service_is_not_started(tmp_path: Path) -> None:
    from tau_core.config import ComponentsConfig

    config = test_config(tmp_path, components=ComponentsConfig(hub_services=("other",)))

    def check(hub: Hub, api: ControlApi) -> None:
        assert [s.name for s in hub.services] == ["control-api"]
        token = (config.hub_dir / "control.token").read_text()
        assert get_json(f"{api.url}/example", token=token)[0] == 404

    assert run_assembled(config, check) == 0


def test_failing_service_is_skipped_and_the_hub_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    import logging
    from importlib import metadata

    from tau_core import registry

    real = registry._entry_points
    failing = metadata.EntryPoint("failing", "tau_core.hub.daemon:Hub", "tau.hub_services")
    # Hub(config) builds fine but is not a HubService (no ``name``), so it is skipped at
    # build time; Boom below fails at start time.
    monkeypatch.setattr(
        registry,
        "_entry_points",
        lambda g: [*([failing] if g == "tau.hub_services" else []), *real(g)],
    )
    registry.reset()

    class Boom:
        name = "boom"

        async def start(self, hub: Hub) -> None:
            raise RuntimeError("no network today")

        async def stop(self) -> None:
            raise AssertionError("never started, never stopped")

    config = test_config(tmp_path)
    boom = Boom()

    def check(hub: Hub, api: ControlApi) -> None:
        assert get_json(f"{api.url}/health")[0] == 200
        assert get_json(f"{api.url}/status")[1]["example"] == {"profile": "home"}

    from tau_core.hub.cli import assemble_hub

    with caplog.at_level(logging.WARNING):
        hub, api = assemble_hub(config, port=0)
        hub.add_service(boom, optional=True)
        result: list[int] = []
        thread = threading.Thread(target=lambda: result.append(hub.run()))
        thread.start()
        try:
            deadline = time.monotonic() + 10
            while (api.port == 0 or hub.state is None) and time.monotonic() < deadline:
                time.sleep(0.02)
            check(hub, api)
        finally:
            hub.request_stop()
            thread.join(timeout=10)
    assert result == [0]
    assert "hub service boom failed to start; running without it" in caplog.text
    assert "failing" in caplog.text and "expected a HubService" in caplog.text


def test_required_service_failure_still_crashes(config: Config) -> None:
    class Boom:
        name = "boom"

        async def start(self, hub: Hub) -> None:
            raise RuntimeError("bind failed")

        async def stop(self) -> None:
            pass

    hub = Hub(config, services=[Boom()])
    assert hub.run() == 1
    assert hub.crash_reason == "RuntimeError: bind failed"


def test_real_hub_run_starts_the_example_service(config: Config, spawn: Any) -> None:
    port = free_port()
    proc = spawn(port)
    code, status = get_json(f"http://127.0.0.1:{port}/status")
    assert code == 200 and status["example"] == {"profile": "home"}
    token_file = config.hub_dir / "control.token"
    token = token_file.read_text()
    assert token_file.stat().st_mode & 0o777 == 0o600
    code, payload = get_json(f"http://127.0.0.1:{port}/example", token=token)
    assert code == 200 and payload["example"] is True
    proc.send_signal(signal.SIGTERM)
    out, _ = proc.communicate(timeout=30)
    assert proc.returncode == 0, out
    assert not token_file.exists()  # a clean stop removes its own token
