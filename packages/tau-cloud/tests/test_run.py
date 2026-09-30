"""``tau cloud run``, the brain container's entrypoint: the pull, the tau.toml patch, the health
endpoint, the hub runner, the refusals, SIGTERM, and one end-to-end run of the real hub in a
subprocess against the fake spine behind a local socket."""

from __future__ import annotations

import asyncio
import json
import os
import signal
import socket
import stat
import subprocess
import sys
import threading
import time
import tomllib
import urllib.error
import urllib.request
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import click
import pytest
from cloud_helpers import SECRET, USER_FACT, invoke, make_home, spine_env
from tau_cloud import __version__
from tau_cloud.cli import MARKER_FILE
from tau_cloud.health import HealthServer
from tau_cloud.sessions import make_store
from tau_cloud.testing import FakeCloud, install_cloud_routes
from tau_core import Config, build_agent
from tau_core.hub import ControlApi, Hub, HubFiles
from tau_core.testing import FakeModel
from tau_net.testing import DEFAULT_HUB_TOKEN, FakeSpine

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


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


def run_env(spine: FakeSpine, **extra: str) -> dict[str, str]:
    values = {"TAU_CLOUD_HEALTH_PORT": "0", "TAU_CLOUD_HEALTH_HOST": "127.0.0.1", **extra}
    return spine_env(spine, **values)


def push_home(spine: FakeSpine, root: Path, *, control_port: int | None = None) -> Path:
    source = make_home(root / "machine")
    if control_port is not None:
        toml = source / "tau.toml"
        text = toml.read_text(encoding="utf-8")
        toml.write_text(
            text.replace("control_port = 7877", f"control_port = {control_port}"),
            encoding="utf-8",
        )
    result = invoke(spine, source, "push", "--yes", "--include-user")
    assert result.exit_code == 0, result.output
    return source


@pytest.fixture
def container(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An empty ``TAU_HOME`` as the image starts it, with its own ``TAU_DATA_DIR``."""
    monkeypatch.setenv("TAU_DATA_DIR", str(tmp_path / "container" / "data"))
    return tmp_path / "container" / "tau"


class Runner:
    """A hub runner that records what it got and returns ``code``."""

    def __init__(self, code: int = 0, during: Any = None):
        self.code = code
        self.during = during
        self.calls: list[tuple[Config, HealthServer]] = []

    def __call__(self, ctx: click.Context, config: Config, health: HealthServer) -> int:
        self.calls.append((config, health))
        if self.during is not None:
            self.during(config, health)
        return self.code


# -- the pull, the patch, the health endpoint, the runner -------------------------------------


def test_run_prepares_the_home_serves_health_and_runs_the_hub(
    tmp_path: Path, spine: FakeSpine, cloud: FakeCloud, container: Path
) -> None:
    control_port = free_port()
    source = push_home(spine, tmp_path, control_port=control_port)
    seen: dict[str, Any] = {}

    def during(config: Config, health: HealthServer) -> None:
        seen["before"] = get_json(health.url)
        api = ControlApi(config.hub.control_port, lambda: {"pid": 42, "uptime_s": 1.0})
        api.serve()
        try:
            seen["during"] = get_json(health.url)
            seen["other"] = get_json(health.url.replace("/health", "/status"))
        finally:
            api.shutdown()
        seen["url"] = health.url

    runner = Runner(code=3, during=during)
    result = invoke(spine, container, "run", env=run_env(spine), runner=runner)
    assert result.exit_code == 3, result.output  # the hub's exit code
    assert f"Pulled 4 files from {spine.url} into {container}." in result.output
    assert "Health endpoint: http://127.0.0.1:" in result.output

    text = (container / "tau.toml").read_text(encoding="utf-8")
    patched = tomllib.loads(text)
    assert patched["sessions"] == {"backend": "spine"}
    assert patched["component"]["net"] == {"name": "Alice's tau", "store": "spine"}
    assert (
        patched["models"]
        == tomllib.loads((source / "tau.toml").read_text(encoding="utf-8"))["models"]
    )
    assert "# The network: comments must survive the cloud patch." in text
    assert "# shown on the card" in text
    for name in ("persona/persona.md", "persona/net.md", "persona/user.md"):
        assert (container / name).read_text(encoding="utf-8") == (source / name).read_text(
            encoding="utf-8"
        )
    assert (container / "persona" / "user.md").read_text(encoding="utf-8") == USER_FACT + "\n"
    assert stat.S_IMODE((container / "persona" / "user.md").stat().st_mode) == 0o600
    assert (container / MARKER_FILE).is_file()
    assert not (container / ".env").exists()

    config, _ = runner.calls[0]
    assert config.home == container and config.sessions.backend == "spine"
    assert seen["before"] == (200, {"ok": True, "version": __version__, "hub": None})
    assert seen["during"] == (
        200,
        {"ok": True, "version": __version__, "hub": {"pid": 42, "uptime_s": 1.0}},
    )
    assert seen["other"] == (404, {"error": "not_found"})
    with pytest.raises(OSError):  # stopped with the hub
        get_json(seen["url"], timeout=1)


async def test_the_container_config_keeps_sessions_in_the_spine(
    tmp_path: Path, spine: FakeSpine, cloud: FakeCloud, container: Path
) -> None:
    push_home(spine, tmp_path)
    runner = Runner()
    assert invoke(spine, container, "run", env=run_env(spine), runner=runner).exit_code == 0
    config, _ = runner.calls[0]
    store = make_store(config, env=spine_env(spine), transport=spine)
    agent = build_agent(
        config=config,
        model=FakeModel(["Hello from the cloud."]),
        tools=[],
        session_store=store,
        channel="telegram",
    )
    assert await agent.ask("hi") == "Hello from the cloud."
    listed = store.list_sessions()
    assert [s.session_id for s in listed] == [agent.session_id]
    assert listed[0].channel == "telegram" and listed[0].message_count == 2
    assert cloud.session_data(agent.session_id) is not None


def test_run_needs_the_spine_variables(tmp_path: Path, spine: FakeSpine, container: Path) -> None:
    runner = Runner()
    result = invoke(spine, container, "run", env={}, runner=runner)
    assert result.exit_code == 1
    assert result.output.strip().splitlines() == [
        "tau cloud: TAU_SPINE_URL and TAU_SPINE_TOKEN must be set (the spine's URL and its "
        "HUB_TOKEN secret, in the environment or in .env)."
    ]
    assert runner.calls == [] and not container.exists()


def test_run_needs_a_cloud_spine(tmp_path: Path, spine: FakeSpine, container: Path) -> None:
    push_home(spine, tmp_path)
    spine.mode = "local"
    runner = Runner()
    result = invoke(spine, container, "run", env=run_env(spine), runner=runner)
    assert result.exit_code == 1
    assert len(result.output.strip().splitlines()) == 1
    assert f"tau cloud: the spine at {spine.url} runs in local mode" in result.output
    assert runner.calls == [] and not container.exists()


def test_run_with_an_unreachable_spine(tmp_path: Path, spine: FakeSpine, container: Path) -> None:
    spine.fail("GET", "/hub/health", ConnectionError("refused"))
    result = invoke(spine, container, "run", env=run_env(spine), runner=Runner())
    assert result.exit_code == 1
    assert "spine unreachable: refused" in result.output


def test_run_without_a_pushed_config(tmp_path: Path, spine: FakeSpine, container: Path) -> None:
    runner = Runner()
    result = invoke(spine, container, "run", env=run_env(spine), runner=runner)
    assert result.exit_code == 1
    assert "holds no tau.toml yet; run `tau cloud push` on your machine first" in result.output
    assert runner.calls == []


def test_run_never_overwrites_a_config_it_did_not_write(
    tmp_path: Path, spine: FakeSpine, container: Path
) -> None:
    push_home(spine, tmp_path)
    mine = make_home(tmp_path / "mine")
    before = (mine / "tau.toml").read_text(encoding="utf-8")
    runner = Runner()
    result = invoke(spine, mine, "run", env=run_env(spine), runner=runner)
    assert result.exit_code == 1
    assert "holds a tau.toml that `tau cloud run` did not write" in result.output
    assert (mine / "tau.toml").read_text(encoding="utf-8") == before
    assert runner.calls == []


def test_a_restart_pulls_the_new_files(tmp_path: Path, spine: FakeSpine, container: Path) -> None:
    source = push_home(spine, tmp_path)
    assert invoke(spine, container, "run", env=run_env(spine), runner=Runner()).exit_code == 0
    (source / "persona" / "persona.md").write_text("A new persona.\n", encoding="utf-8")
    assert invoke(spine, source, "push", "--yes").exit_code == 0
    again = invoke(spine, container, "run", env=run_env(spine), runner=Runner())
    assert again.exit_code == 0, again.output
    assert (container / "persona" / "persona.md").read_text(encoding="utf-8") == (
        "A new persona.\n"
    )


def test_run_pulls_the_sub_taus_and_drops_removed_ones(
    tmp_path: Path, spine: FakeSpine, container: Path
) -> None:
    source = push_home(spine, tmp_path)
    subs = source / "persona" / "subs"
    subs.mkdir()
    (subs / "coach.md").write_text("+++\nabout = 'A coach.'\n+++\n\nCoach.\n", encoding="utf-8")
    (subs / "coach.public.md").write_text("- Public.\n", encoding="utf-8")
    assert invoke(spine, source, "push", "--yes").exit_code == 0
    spine.files["persona/subs/../escape.md"] = {"text": "x", "updated_at": 1}

    first = invoke(spine, container, "run", env=run_env(spine), runner=Runner())
    assert first.exit_code == 0, first.output
    assert f"Pulled 6 files from {spine.url} into {container}." in first.output  # 4 + 2
    for name in ("coach.md", "coach.public.md"):
        pulled = container / "persona" / "subs" / name
        assert pulled.read_text(encoding="utf-8") == (subs / name).read_text(encoding="utf-8")
        assert stat.S_IMODE(pulled.stat().st_mode) == 0o600
    assert not (container / "persona" / "escape.md").exists()

    (subs / "coach.public.md").unlink()
    assert invoke(spine, source, "push", "--yes").exit_code == 0
    again = invoke(spine, container, "run", env=run_env(spine), runner=Runner())
    assert again.exit_code == 0, again.output
    assert sorted(p.name for p in (container / "persona" / "subs").iterdir()) == ["coach.md"]


def test_a_bad_health_port(tmp_path: Path, spine: FakeSpine, container: Path) -> None:
    push_home(spine, tmp_path)
    result = invoke(
        spine, container, "run", env=run_env(spine, TAU_CLOUD_HEALTH_PORT="http"), runner=Runner()
    )
    assert result.exit_code == 1
    assert "TAU_CLOUD_HEALTH_PORT must be a port number, not 'http'." in result.output


def test_a_taken_health_port(tmp_path: Path, spine: FakeSpine, container: Path) -> None:
    push_home(spine, tmp_path)
    with socket.socket() as taken:
        taken.bind(("127.0.0.1", 0))
        taken.listen()
        port = str(taken.getsockname()[1])
        result = invoke(
            spine,
            container,
            "run",
            env=run_env(spine, TAU_CLOUD_HEALTH_PORT=port),
            runner=Runner(),
        )
    assert result.exit_code == 1
    assert f"the health endpoint cannot listen on port {port}" in result.output


# -- the default runner and SIGTERM -----------------------------------------------------------


@pytest.mark.parametrize("code", [0, 1])
def test_the_default_runner_is_tau_hub_run(
    tmp_path: Path,
    spine: FakeSpine,
    container: Path,
    monkeypatch: pytest.MonkeyPatch,
    code: int,
) -> None:
    push_home(spine, tmp_path)
    started: list[Hub] = []

    def fake_run(self: Hub) -> int:
        started.append(self)
        return code

    monkeypatch.setattr(Hub, "run", fake_run)
    result = invoke(spine, container, "run", env=run_env(spine))
    assert result.exit_code == code, result.output
    assert len(started) == 1
    hub = started[0]
    assert hub.config.home == container
    assert hub.config.sessions.backend == "spine"
    assert hub.config.component("net")["store"] == "spine"
    assert "control-api" in [service.name for service in hub.services]
    if code == 0:
        assert result.output.rstrip().endswith("tau hub stopped.")
    else:
        assert "tau hub stopped unexpectedly" in result.output


def test_sigterm_before_the_hub_starts_stops_cleanly(
    tmp_path: Path, spine: FakeSpine, container: Path
) -> None:
    push_home(spine, tmp_path)
    before = signal.getsignal(signal.SIGTERM)

    def during(config: Config, health: HealthServer) -> None:
        os.kill(os.getpid(), signal.SIGTERM)
        time.sleep(5)  # the signal interrupts this
        raise AssertionError("SIGTERM was ignored")

    result = invoke(spine, container, "run", env=run_env(spine), runner=Runner(5, during))
    assert result.exit_code == 0, result.output
    assert signal.getsignal(signal.SIGTERM) is before


# -- end to end: the real hub in a subprocess ---------------------------------------------------


class SpineServer:
    """A :class:`FakeSpine` in cloud mode behind a real HTTP socket on 127.0.0.1."""

    def __init__(self) -> None:
        spine_ref: dict[str, FakeSpine] = {}

        class Handler(BaseHTTPRequestHandler):
            def _forward(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b""
                status, headers, data = spine_ref["spine"].handle(
                    self.command, self.path, dict(self.headers.items()), body
                )
                self.send_response(status)
                for key, value in headers.items():
                    self.send_header(key, value)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = _forward

            def log_message(self, format: str, *args: Any) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        port = self.server.server_address[1]
        self.spine = FakeSpine(f"127.0.0.1:{port}", mode="cloud")
        spine_ref["spine"] = self.spine
        self.cloud = install_cloud_routes(self.spine)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def spine_server() -> Iterator[SpineServer]:
    server = SpineServer()
    yield server
    server.close()


def test_the_real_hub_in_a_container_like_process(
    tmp_path: Path, spine_server: SpineServer
) -> None:
    spine = spine_server.spine
    push_home(spine, tmp_path)
    home, data = tmp_path / "container" / "tau", tmp_path / "container" / "data"
    health_port, hub_port = free_port(), free_port()
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("AWS_", "ANTHROPIC_", "TAU_", "TELEGRAM_", "COV_CORE_"))
    }
    env.update(
        TAU_HOME=str(home),
        TAU_DATA_DIR=str(data),
        TAU_SPINE_URL=spine.url,
        TAU_SPINE_TOKEN=DEFAULT_HUB_TOKEN,
        TAU_HUB_PORT=str(hub_port),
        TAU_CLOUD_HEALTH_PORT=str(health_port),
        TAU_CLOUD_HEALTH_HOST="127.0.0.1",
        PYTHONUNBUFFERED="1",
    )
    proc = subprocess.Popen(
        [sys.executable, "-m", "tau_core", "cloud", "run"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        deadline = time.monotonic() + 60
        health: Any = None
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                pytest.fail(f"tau cloud run exited early ({proc.returncode}): {proc.stdout.read()}")
            try:
                code, health = get_json(f"http://127.0.0.1:{health_port}/health", timeout=1)
                if code == 200 and health.get("hub"):
                    break
            except OSError:
                pass
            time.sleep(0.1)
        else:
            pytest.fail("the health endpoint never showed the hub")
        assert health["ok"] is True and health["version"] == __version__
        assert health["hub"]["pid"] == proc.pid

        # A turn through the container's own configuration lands in the spine.
        config = Config.load(home, env={"TAU_DATA_DIR": str(data)})
        store = make_store(
            config, env={"TAU_SPINE_URL": spine.url, "TAU_SPINE_TOKEN": DEFAULT_HUB_TOKEN}
        )
        agent = build_agent(config=config, model=FakeModel(["pong"]), tools=[], session_store=store)
        assert asyncio.run(agent.ask("ping")) == "pong"
        assert [s.session_id for s in store.list_sessions()] == [agent.session_id]

        proc.send_signal(signal.SIGTERM)
        out, _ = proc.communicate(timeout=30)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    assert proc.returncode == 0, out
    assert "Pulled 4 files" in out and out.rstrip().endswith("tau hub stopped.")
    assert SECRET not in out
    state = HubFiles(Path(data) / "hub").read_state()
    assert state is not None and state.stopped_at is not None
    with pytest.raises(OSError):
        get_json(f"http://127.0.0.1:{health_port}/health", timeout=1)
