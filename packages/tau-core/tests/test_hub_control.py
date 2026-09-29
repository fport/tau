"""The control API: JSON on 127.0.0.1 only, /health and /status, additive routes."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Iterator
from typing import Any

import pytest
from tau_core.hub import ControlApi, ControlRequest

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # never via a proxy


def call(
    url: str, *, method: str = "GET", body: Any = None, headers: dict[str, str] | None = None
) -> tuple[int, dict[str, str], Any]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with OPENER.open(request, timeout=5) as response:
            raw, status, head = response.read(), response.status, dict(response.headers)
    except urllib.error.HTTPError as exc:
        raw, status, head = exc.read(), exc.code, dict(exc.headers)
    return status, head, json.loads(raw.decode("utf-8"))


STATUS = {"role": "hub", "profile": "home", "not": "ascii: çğıöşü"}


def echo(request: ControlRequest) -> tuple[int, Any]:
    return 201, {"got": request.json(), "query": request.query}


def boom(request: ControlRequest) -> tuple[int, Any]:
    raise RuntimeError("handler bug")


@pytest.fixture
def api() -> Iterator[ControlApi]:
    server = ControlApi(0, lambda: dict(STATUS), routes={("POST", "/echo"): echo})
    server.add_route("get", "/boom", boom)
    server.serve()
    yield server
    server.shutdown()


def test_binds_loopback_on_an_ephemeral_port(api: ControlApi) -> None:
    assert api.port != 0
    assert api.url == f"http://127.0.0.1:{api.port}"
    assert api._server is not None
    assert api._server.server_address[0] == "127.0.0.1"


def test_health(api: ControlApi) -> None:
    status, headers, payload = call(f"{api.url}/health")
    assert status == 200
    assert headers["Content-Type"] == "application/json; charset=utf-8"
    assert payload["ok"] is True
    assert payload["pid"] == os.getpid()
    assert payload["uptime_s"] >= 0


def test_status_comes_from_the_provider(api: ControlApi) -> None:
    status, _, payload = call(f"{api.url}/status")
    assert status == 200
    assert payload == STATUS


def test_unknown_path_and_wrong_method(api: ControlApi) -> None:
    assert call(f"{api.url}/nope")[0] == 404
    status, _, payload = call(f"{api.url}/health", method="POST", body={})
    assert status == 405
    assert payload == {"error": "method not allowed"}


def test_added_routes(api: ControlApi) -> None:
    status, _, payload = call(f"{api.url}/echo?x=1", method="POST", body={"a": "ş"})
    assert status == 201
    assert payload == {"got": {"a": "ş"}, "query": {"x": ["1"]}}
    status, _, payload = call(f"{api.url}/boom")
    assert status == 500
    assert payload == {"error": "internal error; details are in the log"}


@pytest.mark.parametrize(
    ("host", "allowed"),
    [
        ("127.0.0.1", True),
        ("localhost", True),
        ("LOCALHOST:1234", True),
        ("[::1]:1234", True),
        ("evil.example", False),
        ("127.0.0.1.evil.example", False),
    ],
)
def test_non_loopback_host_header_is_refused(api: ControlApi, host: str, allowed: bool) -> None:
    status, _, payload = call(f"{api.url}/health", headers={"Host": host})
    if allowed:
        assert status == 200
    else:
        assert status == 403
        assert payload == {"error": "local access only"}


def test_shutdown_closes_the_port() -> None:
    server = ControlApi(0, dict)
    server.serve()
    url = server.url
    assert call(f"{url}/health")[0] == 200
    server.shutdown()
    server.shutdown()  # idempotent
    with pytest.raises(OSError):
        OPENER.open(f"{url}/health", timeout=2)


def test_handle_without_http() -> None:
    server = ControlApi(0, lambda: {"x": 1})
    assert server.handle(ControlRequest("GET", "/status")) == (200, {"x": 1})
    assert server.handle(ControlRequest("DELETE", "/status"))[0] == 405
    assert server.handle(ControlRequest("GET", "/"))[0] == 404


async def test_start_and_stop_as_a_hub_service() -> None:
    server = ControlApi(0, dict)
    await server.start(None)  # type: ignore[arg-type]  # the hub is not needed for the base routes
    assert call(f"{server.url}/health")[0] == 200
    await server.stop()
    with pytest.raises(OSError):
        OPENER.open(f"{server.url}/health", timeout=2)
