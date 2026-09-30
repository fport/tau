"""The control API: JSON on 127.0.0.1 only, /health and /status, additive routes."""

from __future__ import annotations

import asyncio
import json
import os
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest
from tau_core.hub import ControlApi, ControlRequest
from tau_core.hub.control import auth_headers, request_auth, response_proof

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # never via a proxy


def call(
    url: str,
    *,
    method: str = "GET",
    body: Any = None,
    headers: dict[str, str] | None = None,
    token: str | None = None,
) -> tuple[int, dict[str, str], Any]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = dict(headers or {})
    if token is not None:
        for name, value in auth_headers(token, method, urlsplit(url).path).items():
            headers.setdefault(name, value)
    if data is not None:
        headers.setdefault("Content-Type", "application/json")
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
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
def api(tmp_path: Path) -> Iterator[ControlApi]:
    server = ControlApi(
        0, lambda: dict(STATUS), routes={("POST", "/echo"): echo}, hub_dir=tmp_path / "hub"
    )
    server.add_route("get", "/boom", boom)
    server.write_token()
    server.serve()
    yield server
    server.shutdown()


def token_of(api: ControlApi) -> str:
    assert api.token_path is not None
    return api.token_path.read_text()


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
    assert call(f"{api.url}/nope")[0] == 403  # unknown paths are protected too
    assert call(f"{api.url}/nope", token=token_of(api))[0] == 404
    status, _, payload = call(f"{api.url}/health", method="POST", body={}, token=token_of(api))
    assert status == 405
    assert payload == {"error": "method not allowed"}


def test_added_routes(api: ControlApi) -> None:
    token = token_of(api)
    status, _, payload = call(f"{api.url}/echo?x=1", method="POST", body={"a": "ş"}, token=token)
    assert status == 201
    assert payload == {"got": {"a": "ş"}, "query": {"x": ["1"]}}
    status, _, payload = call(f"{api.url}/boom", token=token)
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


def test_routes_are_additive_only(api: ControlApi) -> None:
    spoof = lambda request: (200, {"ok": True, "pid": 1, "spoofed": True})  # noqa: E731
    for method, path in (("GET", "/health"), ("get", "/status"), ("POST", "/echo")):
        with pytest.raises(ValueError, match="already registered"):
            api.add_route(method, path, spoof)
    assert api.routes[("GET", "/health")] == api._health
    assert api.routes[("GET", "/status")] == api._status
    assert api.routes[("POST", "/echo")] is echo
    assert call(f"{api.url}/health")[2]["pid"] == os.getpid()
    with pytest.raises(ValueError, match="GET /health"):
        ControlApi(0, dict, routes={("GET", "/health"): spoof})


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


# -- protected routes, the control token and the response proof (issue 110, ADR 0008) --------


def raw_call(
    url: str, *, method: str = "GET", data: bytes | None = None, headers: dict[str, str]
) -> tuple[int, dict[str, str], bytes]:
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with OPENER.open(request, timeout=5) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read()


SIGNED = {"X-Tau-Nonce": "n-1", "X-Tau-Auth": "<auth>"}


@pytest.mark.parametrize(
    ("change", "headers"),
    [
        ("none", {}),
        ("none", {"X-Tau-Nonce": "n-1", "X-Tau-Auth": "0" * 64}),
        ("none", {"X-Tau-Token": "<token>"}),
        ("none", {"X-Tau-Token": "<token>", "X-Tau-Nonce": "n-1"}),
        ("none", {"X-Tau-Auth": "<auth>"}),
        ("none", {"X-Tau-Nonce": "n-2", "X-Tau-Auth": "<auth>"}),
        ("none", {"X-Tau-Nonce": "n-1", "X-Tau-Auth": "<auth-other-path>"}),
        ("none", {"X-Tau-Nonce": "n-1", "X-Tau-Auth": "<auth-other-method>"}),
        ("none", {"X-Tau-Nonce": "n-1", "X-Tau-Auth": "<proof-as-auth>"}),
        ("none", {**SIGNED, "Origin": "https://evil.example"}),
        ("none", {**SIGNED, "Origin": "null"}),
        ("none", {**SIGNED, "Content-Type": "text/plain"}),
        ("none", {**SIGNED, "Content-Type": "application/x-www-form-urlencoded"}),
        ("missing", SIGNED),
        ("empty", SIGNED),
        ("replaced", SIGNED),
    ],
    ids=[
        "unsigned",
        "wrong-auth",
        "raw-token",
        "raw-token-with-nonce",
        "no-nonce",
        "other-nonce",
        "auth-for-another-path",
        "auth-for-another-method",
        "proof-as-auth",
        "origin",
        "origin-null",
        "text-plain",
        "form",
        "token-file-missing",
        "token-file-empty",
        "token-file-replaced",
    ],
)
def test_a_protected_route_refuses(api: ControlApi, change: str, headers: dict[str, str]) -> None:
    token = token_of(api)
    assert api.token_path is not None
    if change == "missing":
        api.token_path.unlink()
    elif change == "empty":
        api.token_path.write_text("")
    elif change == "replaced":
        api.token_path.write_text("someone-elses-token")
    values = {
        "<token>": token,
        "<auth>": request_auth(token, "n-1", "POST", "/echo"),
        "<auth-other-path>": request_auth(token, "n-1", "POST", "/boom"),
        "<auth-other-method>": request_auth(token, "n-1", "GET", "/echo"),
        "<proof-as-auth>": response_proof(token, "n-1", "POST", "/echo", 201, b""),
    }
    headers = {k: values.get(v, v) for k, v in headers.items()}
    headers.setdefault("Content-Type", "application/json")
    status, head, raw = raw_call(f"{api.url}/echo", method="POST", data=b"{}", headers=headers)
    assert (status, json.loads(raw)) == (403, {"error": "forbidden"})
    assert "X-Tau-Proof" not in head
    assert call(f"{api.url}/health")[0] == 200  # the open routes answer whatever happens
    assert call(f"{api.url}/status")[0] == 200


def test_a_protected_route_accepts_json_with_parameters(api: ControlApi) -> None:
    headers = {
        **auth_headers(token_of(api), "POST", "/echo"),
        "Content-Type": "application/json; charset=utf-8",
    }
    status, _, raw = raw_call(f"{api.url}/echo", method="POST", data=b'{"a": 1}', headers=headers)
    assert status == 201 and json.loads(raw)["got"] == {"a": 1}
    headers["Content-Type"] = "Application/JSON"
    assert raw_call(f"{api.url}/echo", method="POST", data=b"{}", headers=headers)[0] == 201


def test_only_health_and_status_are_open(api: ControlApi) -> None:
    assert api.open_routes == {("GET", "/health"), ("GET", "/status")}
    assert api.is_open("get", "/status") and not api.is_open("POST", "/echo")
    assert not api.is_open("GET", "/nope")
    api.add_route("GET", "/public", lambda request: (200, {}), open=True)
    assert call(f"{api.url}/public")[0] == 200


def test_the_response_proof(api: ControlApi) -> None:
    token = token_of(api)
    headers = {**auth_headers(token, "POST", "/echo", nonce="n-123")}
    headers["Content-Type"] = "application/json"
    status, head, raw = raw_call(f"{api.url}/echo?x=1", method="POST", data=b"{}", headers=headers)
    assert status == 201
    assert head["X-Tau-Proof"] == response_proof(token, "n-123", "POST", "/echo", 201, raw)
    assert head["X-Tau-Proof"] != response_proof(token, "n-124", "POST", "/echo", 201, raw)
    headers = auth_headers(token, "GET", "/boom", nonce="n-123")
    status, head, raw = raw_call(f"{api.url}/boom", headers=headers)
    assert status == 500
    assert head["X-Tau-Proof"] == response_proof(token, "n-123", "GET", "/boom", 500, raw)
    open_head = raw_call(f"{api.url}/status", headers={"X-Tau-Nonce": "n-1"})[1]
    assert "X-Tau-Proof" not in open_head  # open routes never prove anything
    status, _, _ = raw_call(f"{api.url}/status", headers={"X-Tau-Nonce": "n" * 129})
    assert status == 400


def test_request_auth_and_proof_are_separate_hmac_domains() -> None:
    import hashlib
    import hmac

    def mac(message: bytes) -> str:
        return hmac.new(b"tok", message, hashlib.sha256).hexdigest()

    # pinned, so other clients (the tau app's Rust side, 115) can implement the same bytes
    assert request_auth("tok", "n", "get", "/guard/status") == mac(b"req|n|GET|/guard/status")
    assert response_proof("tok", "n", "GET", "/guard/status", 200, b"{}") == mac(
        b"resp|n|GET|/guard/status|200|{}"
    )
    headers = auth_headers("tok", "POST", "/guard/lock")
    assert set(headers) == {"X-Tau-Nonce", "X-Tau-Auth"}
    assert len(headers["X-Tau-Nonce"]) == 32
    assert headers != auth_headers("tok", "POST", "/guard/lock")  # a fresh nonce every time
    assert "tok" not in "".join(headers.values())


def run_hub_in_thread(hub: Any) -> tuple[threading.Thread, list[int]]:
    result: list[int] = []
    thread = threading.Thread(target=lambda: result.append(hub.run()))
    thread.start()
    return thread, result


def test_the_token_lifecycle_with_a_real_hub(tmp_path: Path) -> None:
    from tau_core.hub import AlreadyRunning, Hub
    from tau_core.testing import test_config

    config = test_config(tmp_path)
    hub = Hub(config)
    api = ControlApi(0, hub.status)
    hub.add_service(api)
    token_file = config.hub_dir / "control.token"
    thread, result = run_hub_in_thread(hub)
    try:
        until = time.monotonic() + 10
        while (api.port == 0 or hub.state is None) and time.monotonic() < until:
            time.sleep(0.02)
        assert api.hub_dir == config.hub_dir
        assert token_file.stat().st_mode & 0o777 == 0o600
        assert config.hub_dir.stat().st_mode & 0o777 == 0o700
        token = token_file.read_text()
        assert len(token) >= 43 and token == api._token
        assert call(f"{api.url}/nope", token=token)[0] == 404
        second = Hub(config)
        second_api = ControlApi(0, second.status)
        second.add_service(second_api)
        with pytest.raises(AlreadyRunning):
            second.run()  # lost the lock: never started, never touched the token
        assert token_file.read_text() == token and second_api._token is None
    finally:
        hub.request_stop()
        thread.join(timeout=10)
    assert result == [0]
    assert not token_file.exists()  # its own token: removed on stop


def test_stop_leaves_a_token_that_is_not_its_own(tmp_path: Path) -> None:
    api = ControlApi(0, dict, hub_dir=tmp_path / "hub")

    async def main() -> None:
        await api.start(None)  # type: ignore[arg-type]
        assert api.token_path is not None and api.token_path.is_file()
        api.token_path.write_text("a-newer-hubs-token")
        await api.stop()

    asyncio.run(main())
    assert api.token_path is not None
    assert api.token_path.read_text() == "a-newer-hubs-token"


def test_a_failed_bind_removes_the_token(tmp_path: Path) -> None:
    import socket

    with socket.socket() as taken:
        taken.bind(("127.0.0.1", 0))
        taken.listen()
        api = ControlApi(taken.getsockname()[1], dict, hub_dir=tmp_path / "hub")
        with pytest.raises(OSError):
            asyncio.run(api.start(None))  # type: ignore[arg-type]
    assert api.token_path is not None and not api.token_path.exists()
