"""``HubGuard`` and ``HubClient`` against fake hubs on port 0 (issue 110, ADR 0008).

``FakeHub`` is the real ``ControlApi`` (token, proof) with test routes that emulate
``/guard/*``; ``RawHub`` is a bare listener that answers whatever a test says, proof or not.
Nothing here talks to the live hub: every config points at a port the test bound.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from tau_core import Admission, Config, GuardStatus, GuardTurn, GuardVerdict, HubGuard, Tier
from tau_core.approval import ApprovalRequest
from tau_core.config import HubConfig
from tau_core.guard import ENROLLED_MARKER
from tau_core.hub import ControlApi, ControlRequest, HubClient, HubError, HubUnavailable
from tau_core.hub.control import TOKEN_FILE, response_proof
from tau_core.testing import test_config

TURN = GuardTurn(channel="tui", session_id="s1", client_id="c1")
REQUEST = ApprovalRequest("r1", "lamp", Tier.PHYSICAL, {"state": "on"}, "", "s1", "tui")


def write_marker(config: Config, enrollment: str = "E1") -> None:
    path = config.data_dir / ENROLLED_MARKER
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"v": 1, "enrollment": enrollment}), encoding="utf-8")


def until(condition: Callable[[], bool], timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("timed out")
        time.sleep(0.01)


@dataclass
class GuardRoutes:
    """What the fake hub's ``/guard/*`` routes answer, and what they were asked."""

    admit: tuple[int, Any] = (200, {"allowed": True, "reason": "ok", "enrollment": "E1"})
    verify: tuple[int, Any] = (202, {"attempt": "a1", "seq": 5})
    lock: tuple[int, Any] = (200, {"state": "locked"})
    statuses: list[dict[str, Any]] = field(default_factory=list)
    delay: float = 0.0
    blocking: bool = False
    release: threading.Event = field(default_factory=threading.Event)
    requests: list[tuple[str, Any, dict[str, list[str]]]] = field(default_factory=list)

    def paths(self) -> list[str]:
        return [path for path, _, _ in self.requests]

    def install(self, api: ControlApi) -> None:
        api.add_route("POST", "/guard/admit", self._admit)
        api.add_route("GET", "/guard/status", self._status)
        api.add_route("POST", "/guard/verify", self._verify)
        api.add_route("POST", "/guard/cancel", self._ok)
        api.add_route("POST", "/guard/lock", self._lock)

    def _record(self, request: ControlRequest) -> None:
        self.requests.append((request.path, request.json(), request.query))

    def _admit(self, request: ControlRequest) -> tuple[int, Any]:
        self._record(request)
        if self.delay:
            time.sleep(self.delay)
        status, payload = self.admit
        if status == 500:
            raise RuntimeError("guard service bug")
        return status, payload

    def _status(self, request: ControlRequest) -> tuple[int, Any]:
        self._record(request)
        if self.blocking:
            self.release.wait(5)
        if not self.statuses:
            return 200, {"state": "locked", "seq": 0, "attempt": None, "enrollment": "E1"}
        return 200, self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]

    def _verify(self, request: ControlRequest) -> tuple[int, Any]:
        self._record(request)
        return self.verify

    def _ok(self, request: ControlRequest) -> tuple[int, Any]:
        self._record(request)
        return 200, {"ok": True}

    def _lock(self, request: ControlRequest) -> tuple[int, Any]:
        self._record(request)
        return self.lock


@dataclass
class FakeHub:
    config: Config
    api: ControlApi
    routes: GuardRoutes

    @property
    def guard(self) -> HubGuard:
        return HubGuard(self.config)


@pytest.fixture
def hub(tmp_path: Path) -> Iterator[FakeHub]:
    base = test_config(tmp_path)
    api = ControlApi(0, lambda: {"pid": 1}, hub_dir=base.hub_dir)
    routes = GuardRoutes()
    routes.install(api)
    api.write_token()
    api.serve()
    config = base.with_overrides(
        hub=HubConfig(control_port=api.port, heartbeat_seconds=5),
        component_tables={"guard": {"step_up": "face", "unlock_liveness": "challenge"}},
    )
    write_marker(config)
    yield FakeHub(config, api, routes)
    routes.release.set()
    api.shutdown()


# -- HubClient --------------------------------------------------------------------------------


def test_client_verifies_the_proof_and_reads_open_routes_without_a_token(hub: FakeHub) -> None:
    client = HubClient(hub.config)
    assert client.post("/guard/admit", {"channel": "tui"}, timeout=5)["allowed"] is True
    assert client.get("/health", timeout=5)["ok"] is True
    assert hub.api.token_path is not None
    hub.api.token_path.unlink()  # the hub is gone (or never wrote one): nothing is sent
    count = len(hub.routes.requests)
    with pytest.raises(HubUnavailable) as caught:
        client.post("/guard/admit", {}, timeout=5)
    assert caught.value.reason == "no_hub" and len(hub.routes.requests) == count
    assert client.get("/status", timeout=5) == {"pid": 1}


def test_client_rereads_the_token_once_after_a_403(
    hub: FakeHub, monkeypatch: pytest.MonkeyPatch
) -> None:
    import tau_core.hub.client as client_module

    real = client_module.read_token
    seen: list[str | None] = []

    def stale_first(path: Path) -> str | None:
        token = "stale-token" if not seen else real(path)
        seen.append(token)
        return token

    monkeypatch.setattr(client_module, "read_token", stale_first)
    assert HubClient(hub.config).post("/guard/admit", {}, timeout=5)["allowed"] is True
    assert seen[0] == "stale-token" and len(seen) == 2


def test_client_gives_up_after_a_second_403(hub: FakeHub) -> None:
    assert hub.api.token_path is not None
    hub.api.token_path.write_text("not-this-hubs-token")  # the hub now refuses everything
    with pytest.raises(HubError) as caught:
        HubClient(hub.config).post("/guard/admit", {}, timeout=5)
    assert caught.value.status == 403
    assert hub.routes.requests == []


def test_client_without_a_listener(tmp_path: Path) -> None:
    import socket

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    config = test_config(tmp_path).with_overrides(hub=HubConfig(control_port=port))
    config.hub_dir.mkdir(parents=True)
    (config.hub_dir / TOKEN_FILE).write_text("some-token")
    with pytest.raises(HubUnavailable) as caught:
        HubClient(config).get("/guard/status", timeout=2)
    assert caught.value.reason == "no_hub"


def test_client_never_sends_the_token_and_signs_each_request(hub: FakeHub) -> None:
    seen: list[dict[str, str]] = []
    hub.api.add_route(
        "GET", "/headers", lambda request: (seen.append(dict(request.headers)) or 200, {})
    )
    client = HubClient(hub.config)
    client.get("/headers", timeout=5)
    client.get("/headers", timeout=5)
    assert hub.api.token_path is not None
    token = hub.api.token_path.read_text()
    first, second = seen
    assert "x-tau-token" not in first
    assert not any(token in value for request in seen for value in request.values())
    assert first["x-tau-auth"] != second["x-tau-auth"]  # a fresh nonce signs every request
    assert first["x-tau-nonce"] != second["x-tau-nonce"]


# -- a raw listener: no proof, a wrong proof, bad JSON ------------------------------------------


class RawHub:
    """Answers every request with ``status`` and ``body``; ``proof`` is ``valid``,
    ``missing`` or ``wrong`` (``valid`` uses the token file the client reads)."""

    def __init__(self, token_path: Path, status: int, body: bytes, proof: str) -> None:
        raw = self

        class Handler(BaseHTTPRequestHandler):
            def _answer(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    self.rfile.read(length)
                raw.requests += 1
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                nonce = self.headers.get("X-Tau-Nonce") or ""
                path = self.path.split("?", 1)[0]
                if proof == "valid":
                    token = token_path.read_text().strip()
                    value = response_proof(token, nonce, self.command, path, status, body)
                    self.send_header("X-Tau-Proof", value)
                elif proof == "wrong":
                    self.send_header("X-Tau-Proof", "0" * 64)
                self.end_headers()
                self.wfile.write(body)

            do_GET = do_POST = _answer

            def log_message(self, format: str, *args: Any) -> None:
                pass

        self.requests = 0
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


def raw_guard(tmp_path: Path, status: int, body: bytes, proof: str) -> tuple[HubGuard, RawHub]:
    base = test_config(tmp_path)
    base.hub_dir.mkdir(parents=True)
    token_path = base.hub_dir / TOKEN_FILE
    token_path.write_text("raw-token")
    raw = RawHub(token_path, status, body, proof)
    config = base.with_overrides(hub=HubConfig(control_port=raw.port))
    write_marker(config)
    return HubGuard(config), raw


UNLOCKED = json.dumps(
    {"allowed": True, "reason": "ok", "state": "unlocked", "enrollment": "E1"}
).encode()


@pytest.mark.parametrize(
    ("status", "body", "proof"),
    [
        (200, UNLOCKED, "missing"),
        (200, UNLOCKED, "wrong"),
        (200, b"{not json", "valid"),
        (200, json.dumps({"state": "unlocked"}).encode(), "missing"),
    ],
    ids=["no-proof", "wrong-proof", "bad-json", "bare-unlocked"],
)
def test_an_unproven_or_broken_answer_never_admits(
    tmp_path: Path, status: int, body: bytes, proof: str
) -> None:
    guard, raw = raw_guard(tmp_path, status, body, proof)
    try:
        assert asyncio.run(guard.admit(TURN)) == Admission(False, "unavailable")
        assert asyncio.run(guard.status()).state == "unavailable"
        assert raw.requests == 2
    finally:
        raw.close()


def test_an_unproven_403_never_picks_the_verdict(tmp_path: Path) -> None:
    body = json.dumps({"reason": "cooldown", "retry_after": 900}).encode()
    guard, raw = raw_guard(tmp_path, 403, body, "missing")  # any listener can say this
    try:
        assert asyncio.run(guard.unlock(channel="tui", client_id="c1")) == GuardVerdict(
            False, "unavailable"
        )
        assert asyncio.run(guard.step_up(REQUEST, client_id="c1")) is False
        assert asyncio.run(guard.admit(TURN)) == Admission(False, "unavailable")
        assert raw.requests == 6  # every request retried once after re-reading the token
    finally:
        raw.close()


def test_a_proven_raw_answer_admits(tmp_path: Path) -> None:
    guard, raw = raw_guard(tmp_path, 200, UNLOCKED, "valid")
    try:
        assert asyncio.run(guard.admit(TURN)) == Admission(True, "ok")
    finally:
        raw.close()


class Squatter:
    """A process that bound the port after a hard hub exit left a stale ``control.token``.

    It knows nothing up front: it records every request and signs each answer with whatever
    the request carried that could be a key (the raw token of the old scheme, the auth value,
    the nonce), and it answers exactly what an unlocked guard for ``enrollment`` would say."""

    def __init__(self, enrollment: str) -> None:
        squatter = self
        self.requests: list[bytes] = []

        class Handler(BaseHTTPRequestHandler):
            def _answer(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b""
                squatter.requests.append(
                    self.requestline.encode() + b"\n" + bytes(self.headers) + body
                )
                path = self.path.split("?", 1)[0]
                if path == "/guard/verify":
                    status, payload = 202, {"attempt": "a1", "seq": 1}
                else:
                    done = {"id": "a1", "step": "done", "seq": 2, "done": True, "ok": True}
                    status, payload = (
                        200,
                        {
                            "allowed": True,
                            "reason": "ok",
                            "state": "unlocked",
                            "enrollment": enrollment,
                            "seq": 2,
                            "attempt": {**done, "reason": "match", "method": "face"},
                        },
                    )
                data = json.dumps(payload).encode()
                key = (
                    self.headers.get("X-Tau-Token")
                    or self.headers.get("X-Tau-Auth")
                    or self.headers.get("X-Tau-Nonce")
                    or ""
                )
                nonce = self.headers.get("X-Tau-Nonce") or ""
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                proof = response_proof(key, nonce, self.command, path, status, data)
                self.send_header("X-Tau-Proof", proof)
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_POST = _answer

            def log_message(self, format: str, *args: Any) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


def test_a_squatter_with_a_stale_token_file_learns_nothing_and_never_admits(
    tmp_path: Path,
) -> None:
    squatter = Squatter(enrollment="E1")  # it even knows the enrollment id
    try:
        base = test_config(tmp_path)
        base.hub_dir.mkdir(parents=True)
        stale = "stale-token-of-a-crashed-hub"
        (base.hub_dir / TOKEN_FILE).write_text(stale)
        config = base.with_overrides(hub=HubConfig(control_port=squatter.port))
        write_marker(config, "E1")
        guard = HubGuard(config)
        assert asyncio.run(guard.admit(TURN)) == Admission(False, "unavailable")
        assert asyncio.run(guard.unlock(channel="tui", client_id="c1")) == GuardVerdict(
            False, "unavailable"
        )
        assert asyncio.run(guard.step_up(REQUEST, client_id="c1")) is False
        assert asyncio.run(guard.status()) == GuardStatus("unavailable", reason="bad_proof")
        with pytest.raises(HubUnavailable) as caught:
            HubClient(config).post("/guard/admit", {}, timeout=5)
        assert caught.value.reason == "bad_proof"
        assert squatter.requests
        assert not any(stale.encode() in request for request in squatter.requests)
    finally:
        squatter.close()


def test_client_refuses_a_redirect_and_sends_nothing_to_its_target(tmp_path: Path) -> None:
    target = RawHub(tmp_path / "unused", 200, b"{}", "missing")
    location = f"http://127.0.0.1:{target.port}/guard/admit".encode()

    class Redirecting(BaseHTTPRequestHandler):
        def _answer(self) -> None:
            self.send_response(307)
            self.send_header("Location", location.decode())
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"{}")

        do_GET = do_POST = _answer

        def log_message(self, format: str, *args: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Redirecting)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        base = test_config(tmp_path)
        base.hub_dir.mkdir(parents=True)
        (base.hub_dir / TOKEN_FILE).write_text("a-token")
        config = base.with_overrides(hub=HubConfig(control_port=server.server_address[1]))
        client = HubClient(config)
        for call in (
            lambda: client.post("/guard/admit", {}, timeout=5),
            lambda: client.get("/status", timeout=5),
        ):
            with pytest.raises(HubUnavailable) as caught:
                call()
            assert caught.value.reason == "bad_response"
        assert target.requests == 0
    finally:
        server.shutdown()
        server.server_close()
        target.close()


# -- HubGuard.admit ---------------------------------------------------------------------------


def test_admit_only_a_proven_unlocked_answer_for_our_enrollment(hub: FakeHub) -> None:
    assert asyncio.run(hub.guard.admit(TURN)) == Admission(True, "ok")
    [(path, body, _)] = hub.routes.requests
    assert path == "/guard/admit"
    assert body == {"channel": "tui", "session_id": "s1", "client_id": "c1"}


@pytest.mark.parametrize(
    ("admit", "expected"),
    [
        ((404, {"error": "not found"}), "unavailable"),
        ((500, None), "unavailable"),
        ((503, {"error": "starting"}), "unavailable"),
        ((200, {"allowed": True, "state": "off", "enrollment": "E1"}), "unavailable"),
        ((200, {"allowed": True, "reason": "ok", "enrollment": "E2"}), "unavailable"),
        ((200, {"allowed": True, "reason": "ok"}), "unavailable"),
        ((200, {"allowed": "true", "reason": "ok", "enrollment": "E1"}), "error"),
        ((200, {"allowed": False, "reason": "recheck", "enrollment": "E1"}), "recheck"),
        ((200, {"allowed": False, "reason": "cooldown"}), "cooldown"),
        ((200, {"allowed": False, "reason": "whatever"}), "error"),
        ((200, ["allowed"]), "unavailable"),
    ],
    ids=[
        "404",
        "500",
        "503",
        "off",
        "other-enrollment",
        "no-enrollment",
        "allowed-string",
        "recheck",
        "cooldown",
        "unknown-reason",
        "not-an-object",
    ],
)
def test_admit_refuses_everything_else(hub: FakeHub, admit: Any, expected: str) -> None:
    hub.routes.admit = admit
    assert asyncio.run(hub.guard.admit(TURN)) == Admission(False, expected)


def test_admit_refuses_after_two_403s(hub: FakeHub) -> None:
    assert hub.api.token_path is not None
    hub.api.token_path.write_text("not-this-hubs-token")
    assert asyncio.run(hub.guard.admit(TURN)) == Admission(False, "unavailable")


def test_admit_refuses_without_a_local_marker(hub: FakeHub) -> None:
    (hub.config.data_dir / ENROLLED_MARKER).unlink()  # forgotten here: nothing admits
    assert asyncio.run(hub.guard.admit(TURN)) == Admission(False, "unavailable")


def test_admit_has_its_own_timeout(hub: FakeHub, monkeypatch: pytest.MonkeyPatch) -> None:
    import tau_core.guard as guard_module

    monkeypatch.setattr(guard_module, "ADMIT_TIMEOUT", 0.2)
    hub.routes.delay = 1.0
    started = time.monotonic()
    assert asyncio.run(hub.guard.admit(TURN)) == Admission(False, "unavailable")
    assert time.monotonic() - started < 0.9


# -- HubGuard.status and watch ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("payload", "state", "reason"),
    [
        ({"state": "unlocked", "enrollment": "E1", "method": "face", "seq": 3}, "unlocked", None),
        ({"state": "unlocked", "enrollment": "E2", "seq": 3}, "unavailable", "enrollment"),
        ({"state": "unlocked", "seq": 3}, "unavailable", "enrollment"),
        ({"state": "off", "seq": 0}, "unavailable", "guard_off"),
        ({"state": "locked", "lock_trigger": "idle", "seq": 4}, "locked", None),
        ({"state": "sleeping"}, "unavailable", None),
    ],
)
def test_status_maps_strictly(
    hub: FakeHub, payload: dict[str, Any], state: str, reason: str | None
) -> None:
    hub.routes.statuses = [payload]
    status = asyncio.run(hub.guard.status())
    assert (status.state, status.reason) == (state, reason)
    if state == "locked":
        assert status.lock_trigger == "idle" and status.seq == 4


def test_status_without_a_hub(tmp_path: Path) -> None:
    config = test_config(tmp_path)  # no token file: the client never sends anything
    write_marker(config)
    status = asyncio.run(HubGuard(config).status())
    assert status == GuardStatus("unavailable", reason="no_hub")


def test_watch_passes_since_and_wait(hub: FakeHub) -> None:
    hub.routes.statuses = [{"state": "locked", "seq": 8, "enrollment": "E1"}]
    status = asyncio.run(hub.guard.watch(7, wait=3))
    assert status.state == "locked" and status.seq == 8
    [(_, _, query)] = hub.routes.requests
    assert query == {"since": ["7"], "wait": ["3"]}


# -- unlock and step_up: verify, then long-poll the attempt -------------------------------------


def attempt(step: str, seq: int, **extra: Any) -> dict[str, Any]:
    return {"id": "a1", "step": step, "seq": seq, "done": False, **extra}


def progress_script() -> list[dict[str, Any]]:
    deadline = "2026-09-30T12:00:03+00:00"
    done = attempt("done", 3, done=True, ok=True, reason="match", method="face")
    return [
        {"state": "verifying", "seq": 6, "attempt": attempt("look", 1, deadline=deadline)},
        {"state": "verifying", "seq": 7, "attempt": attempt("turn_left", 2, hint="too_dark")},
        {"state": "verifying", "seq": 7, "attempt": attempt("turn_left", 2, hint="too_dark")},
        {"state": "unlocked", "seq": 8, "attempt": done, "enrollment": "E1"},
    ]


def test_unlock_long_polls_and_reports_each_step_once(hub: FakeHub) -> None:
    hub.routes.statuses = progress_script()
    steps: list[Any] = []
    verdict = asyncio.run(hub.guard.unlock(channel="tui", client_id="c1", on_progress=steps.append))
    assert verdict == GuardVerdict(True, "match", "face")
    assert [(p.step, p.seq, p.hint) for p in steps] == [
        ("look", 1, None),
        ("turn_left", 2, "too_dark"),
        ("done", 3, None),
    ]
    assert steps[0].deadline is not None and steps[0].deadline.isoformat().endswith("+00:00")
    verify = hub.routes.requests[0]
    assert verify[0] == "/guard/verify"
    assert verify[1] == {
        "channel": "tui",
        "client_id": "c1",
        "kind": "unlock",
        "policy": {"step_up": "face", "unlock_liveness": "challenge"},
    }
    sinces = [
        query["since"][0] for path, _, query in hub.routes.requests if path == "/guard/status"
    ]
    assert sinces == ["5", "6", "7", "7"]


@pytest.mark.parametrize(
    ("final", "expected"),
    [
        (
            {"state": "locked", "attempt": attempt("done", 3, done=True, ok=False, reason="spoof")},
            GuardVerdict(False, "spoof"),
        ),
        (
            {
                "state": "locked",
                "attempt": attempt(
                    "done", 3, done=True, ok=False, reason="cooldown", retry_after=30
                ),
            },
            GuardVerdict(False, "cooldown", None, 30.0),
        ),
        (
            {
                "state": "unlocked",
                "enrollment": "E2",
                "attempt": attempt("done", 3, done=True, ok=True, reason="match"),
            },
            GuardVerdict(False, "unavailable"),
        ),
        (
            {
                "state": "locked",
                "enrollment": "E1",
                "attempt": attempt("done", 3, done=True, ok=True, reason="match"),
            },
            GuardVerdict(False, "error"),
        ),
        (
            {
                "state": "unlocked",
                "enrollment": "E1",
                "attempt": attempt("done", 3, done=True, ok=1, reason="match"),
            },
            GuardVerdict(False, "error"),
        ),
        (
            {
                "state": "unlocked",
                "enrollment": "E1",
                "attempt": {**attempt("done", 3), "id": "other"},
            },
            GuardVerdict(False, "unavailable"),
        ),
    ],
    ids=["spoof", "cooldown", "other-enrollment", "not-unlocked", "ok-not-true", "other-attempt"],
)
def test_unlock_verdicts_map_strictly(
    hub: FakeHub, final: dict[str, Any], expected: GuardVerdict
) -> None:
    hub.routes.statuses = [final]
    assert asyncio.run(hub.guard.unlock(channel="tui", client_id="c1")) == expected


def test_a_step_up_queued_behind_another_attempt_follows_its_own_id(hub: FakeHub) -> None:
    hub.routes.verify = (202, {"attempt": "s1", "seq": 10})
    queued = {"id": "s1", "kind": "step_up", "step": "starting", "seq": 1, "done": False}
    done = {**queued, "step": "done", "seq": 2, "done": True, "ok": True, "reason": "match"}
    hub.routes.statuses = [
        {"state": "verifying", "seq": 11, "attempt": queued},  # another client's unlock runs
        {"state": "verifying", "seq": 12, "attempt": queued},
        {"state": "unlocked", "seq": 13, "enrollment": "E1", "attempt": {**done, "method": "face"}},
    ]
    assert asyncio.run(hub.guard.step_up(REQUEST, client_id="c1")) is True
    polls = [query for path, _, query in hub.routes.requests if path == "/guard/status"]
    assert [query["attempt"] for query in polls] == [["s1"], ["s1"], ["s1"]]
    assert [query["since"] for query in polls] == [["10"], ["11"], ["12"]]


def test_an_unknown_or_expired_attempt_is_unavailable(hub: FakeHub) -> None:
    hub.routes.statuses = [{"state": "unlocked", "seq": 6, "enrollment": "E1", "attempt": None}]
    assert asyncio.run(hub.guard.unlock(channel="tui", client_id="c1")) == GuardVerdict(
        False, "unavailable"
    )


def test_unlock_refused_by_the_hub(hub: FakeHub) -> None:
    hub.routes.verify = (429, {"reason": "cooldown", "retry_after": 12})
    verdict = asyncio.run(hub.guard.unlock(channel="tui", client_id="c1"))
    assert verdict == GuardVerdict(False, "cooldown", None, 12.0)
    hub.routes.verify = (409, {"reason": "match"})  # a refusal can never say "match"
    assert asyncio.run(hub.guard.unlock(channel="tui", client_id="c1")).ok is False
    assert asyncio.run(hub.guard.unlock(channel="tui", client_id="c1", kind="step_up")) == (
        GuardVerdict(False, "error")
    )


def test_step_up_sends_the_request_and_passes_only_a_verified_match(hub: FakeHub) -> None:
    hub.routes.statuses = progress_script()
    steps: list[Any] = []
    assert asyncio.run(hub.guard.step_up(REQUEST, client_id="c1", on_progress=steps.append))
    assert len(steps) == 3
    assert hub.routes.requests[0][1] == {
        "channel": "tui",
        "client_id": "c1",
        "kind": "step_up",
        "request_id": "r1",
        "tool": "lamp",
        "policy": {"step_up": "face", "unlock_liveness": "challenge"},
    }
    hub.routes.statuses = [
        {"state": "locked", "attempt": attempt("done", 3, done=True, ok=False, reason="no_match")}
    ]
    assert asyncio.run(hub.guard.step_up(REQUEST, client_id="c1")) is False
    hub.api.shutdown()
    assert asyncio.run(hub.guard.step_up(REQUEST, client_id="c1")) is False


def test_cancelling_an_unlock_posts_cancel_and_reraises(hub: FakeHub) -> None:
    hub.routes.blocking = True

    async def main() -> None:
        task = asyncio.create_task(hub.guard.unlock(channel="tui", client_id="c1"))
        while "/guard/status" not in hub.routes.paths():
            await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(main())  # returns at once: the blocked request runs in a daemon thread
    until(lambda: "/guard/cancel" in hub.routes.paths())
    [cancel] = [body for path, body, _ in hub.routes.requests if path == "/guard/cancel"]
    assert cancel == {"client_id": "c1", "attempt": "a1"}


def test_lock_and_cancel_post_and_never_raise(hub: FakeHub) -> None:
    asyncio.run(hub.guard.lock(channel="telegram", client_id="c1", trigger="telegram"))
    asyncio.run(hub.guard.lock(channel="tui", client_id="c1", trigger="made-up"))
    asyncio.run(hub.guard.cancel(client_id="c1"))
    bodies = [(path, body) for path, body, _ in hub.routes.requests]
    assert bodies == [
        ("/guard/lock", {"channel": "telegram", "client_id": "c1", "trigger": "telegram"}),
        ("/guard/lock", {"channel": "tui", "client_id": "c1", "trigger": "command"}),
        ("/guard/cancel", {"client_id": "c1"}),
    ]
    hub.api.shutdown()
    asyncio.run(hub.guard.lock(channel="tui", client_id="c1"))  # no hub: logged, not raised
    asyncio.run(hub.guard.cancel(client_id="c1"))


def test_a_lock_the_hub_did_not_confirm_is_logged_as_an_error(
    hub: FakeHub, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level("ERROR", logger="tau_core.guard")
    asyncio.run(hub.guard.lock(channel="tui", client_id="c1"))
    assert caplog.records == []
    hub.routes.lock = (200, {"state": "unlocked"})
    asyncio.run(hub.guard.lock(channel="tui", client_id="c1"))
    assert "did not confirm" in caplog.records[-1].getMessage()
    hub.api.shutdown()
    asyncio.run(hub.guard.lock(channel="tui", client_id="c1"))
    assert "did not reach the hub" in caplog.records[-1].getMessage()
    assert all(record.levelname == "ERROR" for record in caplog.records)


# -- the Touch ID fallback (issue 114) -----------------------------------------------------------


def test_a_touch_id_unlock_asks_the_hub_to_run_it_and_maps_the_verdict(hub: FakeHub) -> None:
    done = attempt("done", 3, done=True, ok=True, reason="match", method="touch_id")
    hub.routes.statuses = [
        {"state": "verifying", "seq": 6, "attempt": attempt("touch_id", 1)},
        {"state": "unlocked", "seq": 7, "attempt": done, "enrollment": "E1"},
    ]
    steps: list[Any] = []
    verdict = asyncio.run(
        hub.guard.unlock(channel="tui", client_id="c1", on_progress=steps.append, method="touch_id")
    )
    assert verdict == GuardVerdict(True, "match", "touch_id")
    assert [p.step for p in steps] == ["touch_id", "done"]
    assert hub.routes.requests[0][1] == {
        "channel": "tui",
        "client_id": "c1",
        "kind": "unlock",
        "policy": {"step_up": "face", "unlock_liveness": "challenge"},
        "fallback": "touch_id",  # a request to look, never a result
    }


def test_a_touch_id_unlock_the_hub_does_not_offer_is_refused(hub: FakeHub) -> None:
    hub.routes.verify = (409, {"reason": "touch_id_unavailable"})
    verdict = asyncio.run(hub.guard.unlock(channel="tui", client_id="c1", method="touch_id"))
    assert verdict == GuardVerdict(False, "touch_id_unavailable")


@pytest.mark.parametrize(
    ("kind", "method"), [("recheck", "touch_id"), ("unlock", "password"), ("unlock", "")]
)
def test_only_an_unlock_may_ask_for_touch_id(hub: FakeHub, kind: str, method: str) -> None:
    verdict = asyncio.run(hub.guard.unlock(channel="tui", client_id="c1", kind=kind, method=method))
    assert verdict == GuardVerdict(False, "error")
    assert hub.routes.requests == []  # nothing was sent


@pytest.mark.parametrize(
    ("payload", "fallback"),
    [
        ({"state": "locked", "fallback": "touch_id"}, "touch_id"),
        ({"state": "locked", "fallback": "touch_id_or_password"}, "touch_id_or_password"),
        ({"state": "locked", "fallback": "none"}, None),
        ({"state": "locked", "fallback": ["touch_id"]}, None),
        ({"state": "locked"}, None),
        ({"state": "unlocked", "enrollment": "E1", "fallback": "touch_id"}, None),
        ({"state": "verifying", "fallback": "touch_id"}, None),
    ],
)
def test_status_reads_the_fallback_offer_only_while_locked(
    hub: FakeHub, payload: dict[str, Any], fallback: str | None
) -> None:
    hub.routes.statuses = [{"seq": 3, **payload}]
    assert asyncio.run(hub.guard.status()).fallback == fallback
