"""The fake session and brain routes answer like ``cloud/spine/src/store.ts``: status codes,
error bodies, validation order, the meta merge and implicit session creation."""

from __future__ import annotations

import json
from typing import Any

import pytest
from tau_cloud.testing import FakeCloud
from tau_net.spine import SpineClient
from tau_net.testing import FakeSpine


def call(client: SpineClient, method: str, path: str, **kwargs: Any) -> tuple[int, Any]:
    response = client.request(method, path, **kwargs)
    return response.status, response.json()


def test_local_mode_is_off(spine: FakeSpine, cloud: FakeCloud, client: SpineClient) -> None:
    spine.mode = "local"
    for method, path in [
        ("GET", "/hub/sessions"),
        ("POST", "/hub/sessions"),
        ("GET", "/hub/brain"),
    ]:
        assert call(client, method, path) == (404, {"error": "cloud_mode_off"})


def test_the_token_is_required(spine: FakeSpine, cloud: FakeCloud) -> None:
    anonymous = SpineClient(spine.url, "nope", transport=spine)
    assert call(anonymous, "GET", "/hub/sessions") == (401, {"error": "unauthorized"})
    assert call(anonymous, "GET", "/hub/brain") == (401, {"error": "unauthorized"})


def test_sessions_create_list_and_conflicts(cloud: FakeCloud, client: SpineClient) -> None:
    data = {"session_id": "s1", "session_type": "AGENT"}
    assert call(client, "POST", "/hub/sessions", json={"session_id": "s1", "data": data}) == (
        201,
        {"ok": True},
    )
    assert call(client, "POST", "/hub/sessions", json={"session_id": "s1", "data": {}}) == (
        409,
        {"error": "exists"},
    )
    assert call(client, "GET", "/hub/sessions/s1") == (200, {"data": data})
    assert call(client, "GET", "/hub/sessions/s2") == (404, {"error": "not_found"})
    status, listed = call(client, "GET", "/hub/sessions")
    assert status == 200
    [row] = listed["sessions"]
    assert row["session_id"] == "s1" and row["meta"] == {} and row["message_count"] == 0
    assert row["created_at"].endswith("Z") and row["created_at"] == row["updated_at"]


@pytest.mark.parametrize(
    ("method", "path", "body", "detail"),
    [
        ("POST", "/hub/sessions", {"session_id": "s1"}, "body must carry data"),
        ("POST", "/hub/sessions", {"session_id": "../x", "data": {}}, "session_id must match"),
        ("GET", "/hub/sessions/..", None, "session id must match"),
        ("PATCH", "/hub/sessions/s1/meta", {"meta": [1]}, 'body must be {"meta": {...}}'),
        ("POST", "/hub/sessions/s1/agents", {"agent_id": "a b", "data": {}}, "agent_id must"),
        ("GET", "/hub/sessions/s1/agents/tau/messages/x", None, "message id must be"),
        ("GET", "/hub/sessions?limit=0", None, "limit must be an integer from 1 to 200"),
        ("GET", "/hub/sessions?limit=201", None, "limit must be an integer from 1 to 200"),
    ],
)
def test_bad_requests(
    cloud: FakeCloud, client: SpineClient, method: str, path: str, body: Any, detail: str
) -> None:
    status, answer = call(client, method, path, json=body)
    assert status == 400 and answer["error"] == "bad_request"
    assert detail in answer["detail"]


def test_bodies_must_be_objects_and_small(cloud: FakeCloud, client: SpineClient) -> None:
    assert call(client, "POST", "/hub/sessions", body="[1, 2]", content_type="application/json")[
        1
    ] == {"error": "bad_request", "detail": "body must be a JSON object"}
    huge = {"session_id": "s1", "data": "x" * (1024 * 1024)}
    assert call(client, "POST", "/hub/sessions", json=huge) == (413, {"error": "too_large"})


def test_methods_not_allowed(cloud: FakeCloud, client: SpineClient) -> None:
    response = client.request("DELETE", "/hub/sessions/s1")
    assert response.status == 405 and response.header("allow") == "GET"
    assert client.request("PUT", "/hub/sessions").header("allow") == "GET, POST"
    assert client.request("GET", "/hub/sessions/s1/agents").header("allow") == "POST"
    assert client.request("POST", "/hub/brain").status == 405
    assert call(client, "GET", "/hub/sessions/s1/other") == (404, {"error": "not_found"})


def test_meta_merges_shallowly_and_creates_the_session(
    cloud: FakeCloud, client: SpineClient
) -> None:
    assert call(client, "GET", "/hub/sessions/s1/meta") == (200, {"meta": {}})
    first = {"meta": {"channel": "telegram", "nested": {"a": 1}}}
    assert call(client, "PATCH", "/hub/sessions/s1/meta", json=first)[0] == 200
    second = {"meta": {"title": "t", "nested": {"b": 2}}}
    assert call(client, "PATCH", "/hub/sessions/s1/meta", json=second) == (
        200,
        {"meta": {"channel": "telegram", "nested": {"b": 2}, "title": "t"}},
    )
    data = cloud.session_data("s1")
    assert data is not None and data["session_id"] == "s1" and data["session_type"] == "AGENT"
    assert data["created_at"] == data["updated_at"]


def test_agents_and_messages(cloud: FakeCloud, client: SpineClient) -> None:
    agent = {"agent_id": "tau", "data": {"agent_id": "tau"}}
    assert call(client, "POST", "/hub/sessions/s1/agents", json=agent) == (
        404,
        {"error": "not_found"},
    )
    call(client, "POST", "/hub/sessions", json={"session_id": "s1", "data": {}})
    assert call(client, "POST", "/hub/sessions/s1/agents", json=agent)[0] == 201
    assert call(client, "POST", "/hub/sessions/s1/agents", json=agent)[0] == 409
    messages = "/hub/sessions/s1/agents/tau/messages"
    for mid in (10, 2, 1):
        assert (
            call(client, "POST", messages, json={"message_id": mid, "data": {"m": mid}})[0] == 201
        )
    assert call(client, "POST", messages, json={"message_id": 2, "data": {}})[0] == 409
    assert call(client, "POST", messages, json={"message_id": True, "data": {}})[0] == 400
    assert call(client, "GET", messages) == (200, {"messages": [{"m": 1}, {"m": 2}, {"m": 10}]})
    assert call(client, "GET", messages, params={"offset": 1, "limit": 1}) == (
        200,
        {"messages": [{"m": 2}]},
    )
    assert call(client, "PUT", f"{messages}/2", json={"data": {"m": "two"}}) == (200, {"ok": True})
    assert call(client, "PUT", f"{messages}/3", json={"data": {}})[0] == 404
    assert call(client, "GET", "/hub/sessions/s1/agents/ghost/messages")[0] == 404
    status, listed = call(client, "GET", "/hub/sessions")
    assert listed["sessions"][0]["message_count"] == 3


def test_events_keep_their_order(cloud: FakeCloud, client: SpineClient) -> None:
    assert call(client, "GET", "/hub/sessions/s1/events") == (200, {"events": []})
    for n in range(3):
        assert call(client, "POST", "/hub/sessions/s1/events", json={"data": {"n": n}})[0] == 201
    assert call(client, "GET", "/hub/sessions/s1/events") == (
        200,
        {"events": [{"n": 0}, {"n": 1}, {"n": 2}]},
    )
    assert cloud.session_data("s1") is not None  # created by the first event


def test_the_listing_follows_the_latest_write(cloud: FakeCloud, client: SpineClient) -> None:
    for sid in ("a", "b", "c"):
        call(client, "POST", "/hub/sessions", json={"session_id": sid, "data": {}})
    call(client, "POST", "/hub/sessions/a/events", json={"data": {}})
    status, listed = call(client, "GET", "/hub/sessions", params={"limit": 2})
    assert [row["session_id"] for row in listed["sessions"]] == ["a", "c"]


def test_the_brain(cloud: FakeCloud, client: SpineClient) -> None:
    assert call(client, "GET", "/hub/brain") == (503, {"error": "brain_unavailable"})
    cloud.brain = {"ok": True, "version": "0.1.0", "hub": None}
    assert call(client, "GET", "/hub/brain") == (200, cloud.brain)
    cloud.brain = lambda: None
    assert call(client, "GET", "/hub/brain")[0] == 503


def test_stored_documents_are_json_text(cloud: FakeCloud, client: SpineClient) -> None:
    call(client, "POST", "/hub/sessions", json={"session_id": "s1", "data": {"ş": [1, None]}})
    assert json.loads(cloud.sessions["s1"].data) == {"ş": [1, None]}
