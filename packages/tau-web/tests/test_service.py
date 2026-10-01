"""The web service end to end (issue 178): a real uvicorn server on a random loopback port, a
Strands agent with ``FakeModel`` inside it, and an HTTP client that behaves like the app."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from tau_core import Config, build_agent
from tau_core.sessions import FileSessionStore, SessionBusy
from tau_core.testing import FakeModel, ToolCall
from tau_web.access import AccessVerifier
from tau_web.app import create_app
from tau_web.devices import DeviceRegistry
from tau_web.settings import WebSettings
from tau_web.turns import Runtime

from .conftest import TOOLS, GuardService, Web, factory


def types(events: list[dict[str, Any]]) -> list[str]:
    return [event["type"] for event in events]


# -- the door ------------------------------------------------------------------------------------


async def test_an_unknown_host_is_refused(web: Web) -> None:
    response = await web.client.get("/api/capabilities", headers={"host": "evil.example"})
    assert response.status_code == 421


async def test_every_api_route_needs_a_paired_device(web: Web) -> None:
    for method, path in [
        ("GET", "/api/capabilities"),
        ("GET", "/api/sessions"),
        ("GET", "/api/sessions/x"),
        ("POST", "/api/turns"),
        ("GET", "/api/turns/t-1"),
        ("POST", "/api/turns/t-1/cancel"),
        ("POST", "/api/approvals/a-1"),
    ]:
        response = await web.client.request(method, path, json={}, headers=web.origin)
        assert response.status_code == 401, (method, path)
    page = await web.client.get("/pair")
    assert page.status_code == 200 and "tau" in page.text
    assert "frame-ancestors 'none'" in page.headers["content-security-policy"]


async def test_a_cross_site_post_is_refused_even_with_a_device(web: Web) -> None:
    await web.pair()
    for origin in ({}, {"origin": "https://evil.example"}):
        response = await web.client.post("/api/turns", json={"text": "hi"}, headers=origin)
        assert response.status_code == 403
    code = web.service.devices.start_pairing("tablet")
    response = await web.client.post("/api/pair", json={"code": code})
    assert response.status_code == 403


async def test_pairing_sets_an_http_only_strict_cookie(web: Web) -> None:
    code = web.service.devices.start_pairing("phone")
    response = await web.client.post("/api/pair", json={"code": code}, headers=web.origin)
    cookie = response.headers["set-cookie"].lower()
    assert "tau_device=" in cookie and "httponly" in cookie and "samesite=strict" in cookie
    again = await web.client.post("/api/pair", json={"code": code}, headers=web.origin)
    assert again.status_code == 400 and "not valid" in again.json()["error"]
    capabilities = (await web.client.get("/api/capabilities")).json()
    assert capabilities["backend"] == "hub" and capabilities["protocol"] == 1
    assert capabilities["device"]["name"] == "phone" and "key_hash" not in capabilities["device"]
    assert "guard" in capabilities["pages"]


async def test_a_removed_device_is_locked_out(web: Web) -> None:
    device = await web.pair()
    assert (await web.client.get("/api/sessions")).status_code == 200
    web.service.devices.remove(device["id"])
    assert (await web.client.get("/api/sessions")).status_code == 401


# -- turns ---------------------------------------------------------------------------------------


async def test_a_turn_streams_the_protocol_from_the_hubs_agent(web: Web, model: FakeModel) -> None:
    model.replies = [[ToolCall("clock_tool", {"city": "Ankara"})], "Saat 15:30."]
    await web.pair()
    events = await web.turn("saat kaç")
    assert types(events)[0] == "turn" and types(events)[-1] == "end"
    assert [event["seq"] for event in events] == list(range(len(events)))
    assert {"tool_use", "tool_input", "tool_result", "text"} <= set(types(events))
    [result] = [event for event in events if event["type"] == "tool_result"]
    assert (result["tool"], result["status"], result["summary"]) == (
        "clock_tool",
        "ok",
        "15:30 in Ankara",
    )
    text = "".join(event["delta"] for event in events if event["type"] == "text")
    assert text == "Saat 15:30." and events[-1]["stop_reason"] == "end_turn"
    session = events[0]["session"]
    listed = (await web.client.get("/api/sessions")).json()["sessions"]
    assert [item["id"] for item in listed] == [session]
    assert listed[0]["channel"] == "web" and listed[0]["continuable"]
    history = (await web.client.get(f"/api/sessions/{session}")).json()
    assert [block["type"] for block in history["blocks"]] == ["user", "tool", "assistant"]


async def test_a_second_turn_continues_the_session(web: Web, model: FakeModel) -> None:
    model.replies = ["Bir.", "İki."]
    await web.pair()
    first = await web.turn("bir")
    session = first[0]["session"]
    second = await web.turn("iki", session)
    assert second[0]["session"] == session
    assert model.calls[-1].messages[-1]["content"] == [{"text": "iki"}]


async def test_a_tier_two_call_waits_for_a_device_and_runs_after_approve(
    web: Web, model: FakeModel
) -> None:
    model.replies = [[ToolCall("lamp_tool", {"on": True})], "Lamba açık."]
    await web.pair()
    seen: list[dict[str, Any]] = []
    async for event in web.turn_lines("lambayı aç"):
        seen.append(event)
        if event["type"] == "approval":
            assert (event["tool"], event["tier"], event["input"]) == ("lamp_tool", 2, {"on": True})
            assert event["expires_at"] is not None
            response = await web.decide(event["request"], "approved")
            assert response.status_code == 204
            assert (await web.decide(event["request"], "approved")).status_code == 409
    [decided] = [event for event in seen if event["type"] == "approval_decided"]
    [result] = [event for event in seen if event["type"] == "tool_result"]
    assert decided["decision"] == "approved"
    assert (result["status"], result["approval"], result["summary"]) == ("ok", "approved", "on")
    assert "step_up" in [call for call, _ in web.guard.calls]  # ran after the approval


async def test_reject_and_timeout_never_run_the_tool(web: Web, model: FakeModel) -> None:
    model.replies = [[ToolCall("lamp_tool", {"on": True})], "Peki."]
    await web.pair()
    async for event in web.turn_lines("lambayı aç"):
        if event["type"] == "approval":
            await web.decide(event["request"], "rejected")
        if event["type"] == "tool_result":
            assert (event["status"], event["approval"]) == ("rejected", "rejected")

    web.service.runtime.approval_timeout = 0.2  # type: ignore[union-attr]
    model.replies = [[ToolCall("lamp_tool", {"on": True})], "Peki."]
    events = await web.turn("yine aç")
    [decided] = [event for event in events if event["type"] == "approval_decided"]
    [result] = [event for event in events if event["type"] == "tool_result"]
    assert decided["decision"] == "timeout"
    assert (result["status"], result["approval"]) == ("rejected", "timeout")
    bad = await web.decide("a-unknown", "maybe")
    assert bad.status_code == 400


async def test_a_closed_stream_does_not_stop_the_turn_and_re_attach_resumes(
    web: Web, model: FakeModel
) -> None:
    model.replies = [[ToolCall("lamp_tool", {"on": True})], "Tamam."]
    await web.pair()
    first: list[dict[str, Any]] = []
    async for event in web.turn_lines("lambayı aç"):
        first.append(event)
        if event["type"] == "approval":
            break  # the tab closes while the approval waits
    turn, request = first[0]["turn"], first[-1]["request"]
    assert (await web.decide(request, "approved")).status_code == 204
    after = first[-1]["seq"]
    async with web.client.stream("GET", f"/api/turns/{turn}", params={"after": after}) as r:
        rest = [json.loads(line) async for line in r.aiter_lines() if line.strip()]
    assert rest[0]["seq"] == after + 1 and rest[-1]["type"] == "end"
    whole = first + rest
    assert [event["seq"] for event in whole] == list(range(len(whole)))
    text = "".join(event["delta"] for event in whole if event["type"] == "text")
    assert text == "Tamam."
    replay = await web.client.get(f"/api/turns/{turn}")
    assert len(replay.text.strip().splitlines()) == len(whole)


async def test_cancel_ends_the_turn(web: Web, model: FakeModel) -> None:
    model.replies = [[ToolCall("lamp_tool", {"on": True})], "Hiç."]
    await web.pair()
    events: list[dict[str, Any]] = []
    async for event in web.turn_lines("lambayı aç"):
        events.append(event)
        if event["type"] == "approval":
            cancel = await web.client.post(
                f"/api/turns/{events[0]['turn']}/cancel", headers=web.origin
            )
            assert cancel.status_code == 204
            await web.decide(event["request"], "rejected")
    assert events[-1]["type"] == "end"


async def test_a_locked_guard_refuses_the_turn(web: Web, model: FakeModel) -> None:
    await web.pair()
    web.guard.set_state("locked")
    events = await web.turn("merhaba")
    assert events[-1] == {**events[-1], "type": "end", "stop_reason": "locked"}
    assert not model.calls


async def test_a_lock_rejects_the_pending_approval(web: Web, model: FakeModel) -> None:
    model.replies = [[ToolCall("lamp_tool", {"on": True})], "Kilitlendi."]
    await web.pair()
    async for event in web.turn_lines("lambayı aç"):
        if event["type"] == "approval":
            web.guard.lock()
        if event["type"] == "approval_decided":
            assert event["decision"] == "rejected"
        if event["type"] == "tool_result":
            assert event["status"] == "rejected"


async def test_one_turn_at_a_time_per_session(web: Web, model: FakeModel) -> None:
    model.replies = [[ToolCall("lamp_tool", {"on": True})], "Bir."]
    await web.pair()
    async for event in web.turn_lines("lambayı aç"):
        if event["type"] == "approval":
            busy = await web.client.post(
                "/api/turns",
                json={"text": "iki", "session": event_session(web)},
                headers=web.origin,
            )
            assert busy.status_code == 409
            await web.decide(event["request"], "rejected")


def event_session(web: Web) -> str:
    [session] = list(web.service.runtime.sessions)  # type: ignore[union-attr]
    return session


# -- sessions ------------------------------------------------------------------------------------


async def test_a_session_open_in_the_web_is_busy_for_the_tui(
    web: Web, model: FakeModel, config: Config, store: FileSessionStore
) -> None:
    await web.pair()
    events = await web.turn("merhaba")
    session = events[0]["session"]
    with pytest.raises(SessionBusy, match="open in web"):
        build_agent(config=config, model=FakeModel(), session_store=store, session_id=session)
    web.service.runtime.turn_keep = 0  # type: ignore[union-attr]
    web.service.runtime.sweep()  # type: ignore[union-attr]
    build_agent(config=config, model=FakeModel(), session_store=store, session_id=session).close()


async def test_a_session_held_by_the_tui_cannot_be_continued_here(
    web: Web, config: Config, store: FileSessionStore
) -> None:
    await web.pair()
    tui = build_agent(
        config=config, model=FakeModel(["Merhaba."]), session_store=store, channel="tui"
    )
    await tui.ask("merhaba")
    response = await web.client.post(
        "/api/turns", json={"text": "devam", "session": tui.session_id}, headers=web.origin
    )
    assert response.status_code == 409 and "open in tui" in response.json()["error"]
    history = await web.client.get(f"/api/sessions/{tui.session_id}")
    assert history.status_code == 200  # reading is fine
    tui.close()


async def test_network_sessions_are_shown_but_never_continued(
    web: Web, store: FileSessionStore, config: Config
) -> None:
    await web.pair()
    net = build_agent(
        config=config, model=FakeModel(["Selam."]), session_store=store, channel="net"
    )
    await net.ask("hello from a peer")
    net.close()
    listed = (await web.client.get("/api/sessions")).json()["sessions"]
    assert [(item["channel"], item["continuable"]) for item in listed] == [("net", False)]
    response = await web.client.post(
        "/api/turns", json={"text": "use your tools", "session": net.session_id}, headers=web.origin
    )
    assert response.status_code == 409 and "net session" in response.json()["error"]


async def test_bad_requests(web: Web) -> None:
    await web.pair()
    for body in ({}, {"text": " "}, {"text": "x", "session": 3}):
        response = await web.client.post("/api/turns", json=body, headers=web.origin)
        assert response.status_code == 400
    assert (await web.client.get("/api/turns/t-none")).status_code == 404
    assert (await web.client.get("/api/sessions/.lock")).status_code == 400
    assert (await web.client.get("/api/sessions/20260101-000000-abcd")).status_code == 404
    assert (await web.client.get("/api/turns/x", params={"after": "a"})).status_code == 400


async def test_status_reports_the_service(web: Web) -> None:
    await web.pair()
    hub = web.service.hub
    status = {}
    for source in hub.sources:
        status.update(source())
    assert status["web"]["bind"] == "127.0.0.1" and status["web"]["devices"] == 1
    assert status["web"]["port"] == web.service.port


# -- static files and the Access check ------------------------------------------------------------


async def test_static_files_never_leave_their_directory(tmp_path: Any, config: Config) -> None:
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<p>app</p>")
    (static / "app.js").write_text("console.log(1)")
    (tmp_path / "secret.txt").write_text("secret")
    app = create_app(
        settings=WebSettings(port=0),
        devices=DeviceRegistry(tmp_path / "web"),
        runtime=_runtime(config),
        capabilities=dict,
        static_dir=static,
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        assert (await client.get("/app.js")).text == "console.log(1)"
        assert (await client.get("/sessions/123")).text == "<p>app</p>"  # the app's own route
        assert "secret" not in (await client.get("/../secret.txt")).text
        assert "secret" not in (await client.get("/%2e%2e/secret.txt")).text


def _runtime(config: Config) -> Runtime:
    return Runtime(
        config,
        FileSessionStore(config.sessions_dir),
        guard=lambda: None,
        approval_timeout=1,
        turn_keep=1,
        agent_factory=factory(FakeModel(), TOOLS),
    )


def _token(
    key: Any, *, audience: str = "aud-1", issuer: str = "https://team.cloudflareaccess.com"
) -> str:
    now = datetime.now(UTC)
    claims = {"aud": audience, "iss": issuer, "iat": now, "exp": now + timedelta(minutes=5)}
    return jwt.encode(claims, key, algorithm="RS256")


async def test_the_access_check_refuses_requests_without_a_valid_token(
    tmp_path: Any, config: Config
) -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    verifier = AccessVerifier("team", "aud-1", key_for=lambda token: key.public_key())
    app = create_app(
        settings=WebSettings(port=0, access_aud="aud-1", access_team="team"),
        devices=DeviceRegistry(tmp_path / "web"),
        runtime=_runtime(config),
        capabilities=dict,
        access=verifier,
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        assert (await client.get("/")).status_code == 403
        for token in (
            _token(other),
            _token(key, audience="another-app"),
            _token(key, issuer="https://evil.cloudflareaccess.com"),
            "not-a-jwt",
        ):
            response = await client.get("/", headers={"cf-access-jwt-assertion": token})
            assert response.status_code == 403
        good = await client.get("/", headers={"cf-access-jwt-assertion": _token(key)})
        assert good.status_code == 200


async def test_the_service_stops_cleanly_with_a_turn_waiting(web: Web, model: FakeModel) -> None:
    model.replies = [[ToolCall("lamp_tool", {"on": True})], "x"]
    await web.pair()
    async for event in web.turn_lines("lambayı aç"):
        if event["type"] == "approval":
            break
    await asyncio.wait_for(web.service.stop(), timeout=10)
    assert web.service.runtime.sessions == {}  # type: ignore[union-attr]


@pytest.mark.parametrize("guard", [GuardService(state="unlocked", step_ups=[False])])
async def test_a_failed_step_up_turns_the_approval_into_a_rejection(
    web: Web, model: FakeModel
) -> None:
    model.replies = [[ToolCall("lamp_tool", {"on": True})], "Olmadı."]
    await web.pair()
    events: list[dict[str, Any]] = []
    async for event in web.turn_lines("lambayı aç"):
        events.append(event)
        if event["type"] == "approval":
            await web.decide(event["request"], "approved")
    [result] = [event for event in events if event["type"] == "tool_result"]
    assert (result["status"], result["approval"]) == ("rejected", "rejected")
    steps = [event for event in events if event["type"] == "guard"]
    assert [step["action"] for step in steps] == ["step_up", "step_up"]
    assert steps[-1]["ok"] is False
