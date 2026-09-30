"""The SessionStore contract of tau-core's file store, run against the spine store (over the
fake spine) and the file store side by side, plus what only the spine store has: requests,
errors, retries and the backend factory."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest
from strands.types.exceptions import SessionException
from strands.types.session import Session, SessionAgent, SessionMessage, SessionType
from tau_cloud import sessions as spine_sessions
from tau_cloud.sessions import SpineSessionStore, SpineStoreError, make_store
from tau_cloud.testing import FakeCloud
from tau_core import Config, ConfigError
from tau_core.config import SessionsConfig
from tau_core.events import AgentEvent, EventBus
from tau_core.sessions import FileSessionStore, InvalidSessionId, SessionStore, open_session_store
from tau_core.testing import test_config
from tau_net.spine import SpineClient
from tau_net.testing import DEFAULT_HUB_TOKEN, FakeSpine

AGENT = "tau"


@pytest.fixture(params=["spine", "file"])
def store(
    request: pytest.FixtureRequest, tmp_path: Path, spine_store: SpineSessionStore
) -> SessionStore:
    """The contract cases run on both backends: the spine store must behave like the file
    store it replaces in cloud mode."""
    if request.param == "spine":
        return spine_store
    return FileSessionStore(tmp_path / "sessions")


def new_session(store: SessionStore, session_id: str = "s1") -> None:
    store.create_session(Session(session_id=session_id, session_type=SessionType.AGENT))
    store.create_agent(session_id, SessionAgent(AGENT, {}, {}))


def message(index: int, text: str, role: str = "user") -> SessionMessage:
    return SessionMessage({"role": role, "content": [{"text": text}]}, index)


# -- contract: both backends ------------------------------------------------------------------


def test_session_and_agent_round_trip(store: SessionStore) -> None:
    assert store.read_session("s1") is None
    new_session(store)
    session = store.read_session("s1")
    assert session is not None and session.session_id == "s1"
    assert session.session_type == SessionType.AGENT
    with pytest.raises(SessionException, match="already exists"):
        store.create_session(Session(session_id="s1", session_type=SessionType.AGENT))

    agent = store.read_agent("s1", AGENT)
    assert agent is not None and agent.agent_id == AGENT and agent.state == {}
    assert store.read_agent("s1", "other") is None
    assert store.read_agent("missing", AGENT) is None

    store.update_agent("s1", SessionAgent(AGENT, {"k": "v"}, {"removed_message_count": 0}))
    updated = store.read_agent("s1", AGENT)
    assert updated is not None and updated.state == {"k": "v"}
    assert updated.conversation_manager_state == {"removed_message_count": 0}
    assert updated.created_at == agent.created_at
    with pytest.raises(SessionException):
        store.update_agent("s1", SessionAgent("ghost", {}, {}))


def test_agent_needs_a_session(store: SessionStore) -> None:
    with pytest.raises(SessionException):
        store.create_agent("missing", SessionAgent(AGENT, {}, {}))


def test_creating_an_agent_again_replaces_it(store: SessionStore) -> None:
    new_session(store)
    store.create_agent("s1", SessionAgent(AGENT, {"again": True}, {}))
    assert store.read_agent("s1", AGENT).state == {"again": True}


def test_messages_in_order_with_paging(store: SessionStore) -> None:
    new_session(store)
    for i in range(12):
        store.create_message(
            "s1", AGENT, message(i, f"m{i}", "user" if i % 2 == 0 else "assistant")
        )
    texts = [m.message["content"][0]["text"] for m in store.list_messages("s1", AGENT)]
    assert texts == [f"m{i}" for i in range(12)]  # numeric, not lexicographic, order
    page = store.list_messages("s1", AGENT, limit=3, offset=9)
    assert [m.message_id for m in page] == [9, 10, 11]
    assert [m.message_id for m in store.list_messages("s1", AGENT, offset=10)] == [10, 11]
    assert store.list_messages("s1", AGENT, limit=0) == []
    assert store.read_message("s1", AGENT, 4).message["content"][0]["text"] == "m4"
    assert store.read_message("s1", AGENT, 99) is None
    with pytest.raises(SessionException):
        store.list_messages("s1", "ghost")


def test_message_needs_an_agent(store: SessionStore) -> None:
    store.create_session(Session(session_id="s1", session_type=SessionType.AGENT))
    with pytest.raises(SessionException):
        store.create_message("s1", AGENT, message(0, "hello"))


def test_create_message_never_overwrites(store: SessionStore) -> None:
    new_session(store)
    store.create_message("s1", AGENT, message(0, "first"))
    with pytest.raises(SessionException, match="already exists"):
        store.create_message("s1", AGENT, message(0, "second"))
    assert store.read_message("s1", AGENT, 0).message["content"][0]["text"] == "first"


def test_update_message_keeps_the_original(store: SessionStore) -> None:
    new_session(store)
    store.create_message("s1", AGENT, message(0, "secret"))
    created = store.read_message("s1", AGENT, 0)
    redacted = message(0, "secret")
    redacted.redact_message = {"role": "user", "content": [{"text": "[redacted]"}]}
    store.update_message("s1", AGENT, redacted)
    stored = store.read_message("s1", AGENT, 0)
    assert stored.message["content"][0]["text"] == "secret"
    assert stored.to_message()["content"][0]["text"] == "[redacted]"
    assert stored.created_at == created.created_at
    with pytest.raises(SessionException):
        store.update_message("s1", AGENT, message(7, "missing"))


def test_bytes_survive(store: SessionStore) -> None:
    new_session(store)
    image = {"image": {"format": "png", "source": {"bytes": b"\x89PNG\x00\xff"}}}
    store.create_message("s1", AGENT, SessionMessage({"role": "user", "content": [image]}, 0))
    restored = store.read_message("s1", AGENT, 0).to_message()
    assert restored["content"][0]["image"]["source"]["bytes"] == b"\x89PNG\x00\xff"


def test_meta_merges_and_creates_the_session(store: SessionStore) -> None:
    assert store.read_meta("s9") == {}
    store.write_meta("s9", channel="terminal", profile="home")
    store.write_meta("s9", title="What time is it? ş")
    assert store.read_meta("s9") == {
        "channel": "terminal",
        "profile": "home",
        "title": "What time is it? ş",
    }
    assert store.read_session("s9") is not None


def test_events_round_trip(store: SessionStore) -> None:
    at = datetime(2026, 9, 29, 12, 30, tzinfo=UTC)
    first = AgentEvent("tool_call", at, "s1", {"tool": "clock", "arguments": {"ş": "ğ"}})
    second = AgentEvent("robot_moved", at, "s1", {"x": 1})  # unknown kinds pass through
    assert store.read_events("s1") == []
    store.append_event("s1", first)  # creates the session record
    store.append_event("s1", second)
    assert store.read_events("s1") == [first, second]
    assert store.read_session("s1") is not None


def test_event_sink_ignores_other_sessions(store: SessionStore) -> None:
    bus = EventBus()
    bus.subscribe(store.event_sink("s1"))
    bus.emit(AgentEvent.create("notice", {"text": "one"}, session_id="s1"))
    bus.emit(AgentEvent.create("notice", {"text": "two"}, session_id="s2"))
    bus.emit(AgentEvent.create("notice", {"text": "three"}))
    assert [e.data["text"] for e in store.read_events("s1")] == ["one", "three"]
    assert store.read_events("s2") == []


@pytest.mark.parametrize("bad", ["", "..", ".hidden", "a/b", "../escape", "x y", "a\nb", "a?b"])
def test_invalid_ids_are_refused(store: SessionStore, spine: FakeSpine, bad: str) -> None:
    before = len(spine.requests)
    with pytest.raises(InvalidSessionId) as info:
        store.read_session(bad)
    assert isinstance(info.value, ConfigError) and isinstance(info.value, ValueError)
    assert "Invalid session id" in str(info.value)
    with pytest.raises(InvalidSessionId, match="agent"):
        store.read_agent("ok", bad)
    for call in (
        lambda: store.write_meta(bad, title="x"),
        lambda: store.append_event(bad, AgentEvent.create("notice", {})),
        lambda: store.create_session(Session(session_id=bad, session_type=SessionType.AGENT)),
    ):
        with pytest.raises(InvalidSessionId):
            call()
    assert len(spine.requests) == before  # refused before any request


# -- the spine store --------------------------------------------------------------------------


def test_list_sessions_newest_first(spine_store: SpineSessionStore) -> None:
    store = spine_store
    for session_id in ("a", "b", "c"):
        store.write_meta(
            session_id, channel="terminal", profile="home", title=f"title {session_id}"
        )
    new_session(store, "d")
    store.create_message("d", AGENT, message(0, "hello"))
    store.create_message("d", AGENT, message(1, "hi", "assistant"))
    store.append_event("a", AgentEvent.create("notice", {"text": "new"}, session_id="a"))

    listed = store.list_sessions()
    assert [s.session_id for s in listed] == ["a", "d", "c", "b"]
    assert [s.session_id for s in store.list_sessions(limit=2)] == ["a", "d"]
    assert store.list_sessions(limit=0) == []
    by_id = {s.session_id: s for s in listed}
    assert by_id["d"].message_count == 2 and by_id["a"].message_count == 0
    assert by_id["b"].title == "title b" and by_id["b"].channel == "terminal"
    assert by_id["b"].profile == "home"
    assert by_id["a"].updated_at > by_id["a"].created_at
    assert datetime.fromisoformat(by_id["a"].created_at).tzinfo is not None  # ISO 8601, UTC


def test_message_count_covers_every_agent(spine_store: SpineSessionStore) -> None:
    new_session(spine_store)
    spine_store.create_agent("s1", SessionAgent("helper", {}, {}))
    spine_store.create_message("s1", AGENT, message(0, "one"))
    spine_store.create_message("s1", "helper", message(0, "two"))
    assert spine_store.list_sessions()[0].message_count == 2


def test_survives_a_new_store_instance(spine: FakeSpine, spine_store: SpineSessionStore) -> None:
    new_session(spine_store)
    spine_store.create_message("s1", AGENT, message(0, "hello"))
    spine_store.write_meta("s1", title="hello")
    spine_store.append_event("s1", AgentEvent.create("notice", {"text": "x"}, session_id="s1"))

    second = SpineSessionStore(SpineClient(spine.url, DEFAULT_HUB_TOKEN, transport=spine))
    assert [m.message_id for m in second.list_messages("s1", AGENT)] == [0]
    assert second.read_meta("s1") == {"title": "hello"}
    assert [e.kind for e in second.read_events("s1")] == ["notice"]
    assert second.list_sessions()[0].message_count == 1
    second.update_agent("s1", SessionAgent(AGENT, {"n": 1}, {}))  # reads created_at first
    assert (
        second.read_agent("s1", AGENT).created_at == spine_store.read_agent("s1", AGENT).created_at
    )


def test_long_histories_are_read_in_pages(
    spine: FakeSpine, spine_store: SpineSessionStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(spine_sessions, "MESSAGE_PAGE", 4)
    new_session(spine_store)
    for i in range(10):
        spine_store.create_message("s1", AGENT, message(i, f"m{i}"))
    spine.requests.clear()
    assert [m.message_id for m in spine_store.list_messages("s1", AGENT)] == list(range(10))
    assert len(spine.requests) == 3  # 4 + 4 + 2
    spine.requests.clear()
    assert [m.message_id for m in spine_store.list_messages("s1", AGENT, limit=5, offset=3)] == [
        3,
        4,
        5,
        6,
        7,
    ]
    assert len(spine.requests) == 2


def test_the_spine_keeps_strands_records_as_sent(
    spine_store: SpineSessionStore, cloud: FakeCloud
) -> None:
    new_session(spine_store)
    spine_store.create_message("s1", AGENT, message(0, "hello"))
    record = cloud.session_data("s1")
    assert record is not None
    assert record["session_id"] == "s1" and record["session_type"] == "AGENT"
    assert record["updated_at"]
    stored = cloud.message_data("s1", AGENT)
    assert stored[0]["message"] == {"role": "user", "content": [{"text": "hello"}]}
    assert stored[0]["message_id"] == 0


def test_list_sessions_asks_for_at_most_200(
    spine: FakeSpine, spine_store: SpineSessionStore
) -> None:
    spine_store.write_meta("s1", title="x")
    queries: list[dict[str, str]] = []
    spine.route(
        "GET",
        r"/hub/sessions",
        lambda request: (queries.append(request.query), (200, {"sessions": []}))[1],
    )
    assert spine_store.list_sessions(limit=500) == []
    assert queries == [{"limit": "200"}]


def test_nothing_is_ever_deleted(spine: FakeSpine, spine_store: SpineSessionStore) -> None:
    deleting = [
        name
        for name in dir(SpineSessionStore)
        if any(word in name.lower() for word in ("delete", "remove", "purge", "prune", "clear"))
    ]
    assert deleting == []
    new_session(spine_store)
    spine_store.create_message("s1", AGENT, message(0, "one"))
    spine_store.update_message("s1", AGENT, message(0, "one (fixed)"))
    spine_store.update_agent("s1", SessionAgent(AGENT, {"x": 1}, {}))
    spine_store.write_meta("s1", title="one")
    spine_store.append_event("s1", AgentEvent.create("notice", {}, session_id="s1"))
    spine_store.list_sessions()
    assert {method for method, _ in spine.requests} <= {"GET", "POST", "PUT", "PATCH"}


# -- errors -----------------------------------------------------------------------------------


def test_an_unreachable_spine_is_an_error_with_the_url(
    spine: FakeSpine, spine_store: SpineSessionStore
) -> None:
    new_session(spine_store)
    spine.fail("POST", "/hub/sessions/s1/agents/tau/messages", ConnectionError("refused"))
    with pytest.raises(SpineStoreError) as info:
        spine_store.create_message("s1", AGENT, message(0, "must not vanish"))
    assert isinstance(info.value, SessionException)
    assert "https://spine.example is unreachable" in str(info.value)
    assert DEFAULT_HUB_TOKEN not in str(info.value)
    # A POST is not repeated behind the caller's back: nothing was stored, and the caller knew.
    assert spine_store.list_messages("s1", AGENT) == []


def test_safe_requests_are_tried_twice(spine: FakeSpine, spine_store: SpineSessionStore) -> None:
    spine_store.write_meta("s1", title="kept")
    spine.fail("GET", "/hub/sessions/s1/meta", ConnectionError("blip"))
    assert spine_store.read_meta("s1") == {"title": "kept"}
    spine.fail("PATCH", "/hub/sessions/s1/meta", (503, {"error": "not_configured"}))
    spine_store.write_meta("s1", channel="telegram")
    assert spine_store.read_meta("s1") == {"title": "kept", "channel": "telegram"}
    spine.fail(
        "GET", "/hub/sessions/s1/meta", ConnectionError("down"), ConnectionError("still down")
    )
    with pytest.raises(SpineStoreError, match="unreachable"):
        spine_store.read_meta("s1")


def test_a_local_mode_spine_is_named(spine: FakeSpine, spine_store: SpineSessionStore) -> None:
    spine.mode = "local"
    with pytest.raises(SpineStoreError, match="not in cloud mode"):
        spine_store.read_session("s1")
    with pytest.raises(SpineStoreError, match="cloud_mode_off"):
        spine_store.write_meta("s1", title="x")


def test_other_refusals_carry_the_code(spine: FakeSpine, spine_store: SpineSessionStore) -> None:
    new_session(spine_store)
    huge = message(0, "x" * (1024 * 1024 + 10))
    with pytest.raises(SpineStoreError, match="413 too_large"):
        spine_store.create_message("s1", AGENT, huge)
    wrong = SpineSessionStore(SpineClient(spine.url, "wrong-token", transport=spine))
    with pytest.raises(SpineStoreError, match="401 unauthorized") as info:
        wrong.read_session("s1")
    assert "wrong-token" not in str(info.value)


def test_event_data_that_is_not_json_is_stored_as_text(spine_store: SpineSessionStore) -> None:
    event = AgentEvent.create("notice", {"path": Path("/tmp/x"), "n": 1}, session_id="s1")
    spine_store.append_event("s1", event)
    assert spine_store.read_events("s1")[0].data == {"path": "/tmp/x", "n": 1}


# -- the backend factory ----------------------------------------------------------------------


def _spine_config(tmp_path: Path) -> Config:
    config = test_config(tmp_path)
    toml = config.home / "tau.toml"
    toml.write_text(
        toml.read_text(encoding="utf-8").replace('backend = "memory"', 'backend = "spine"'),
        encoding="utf-8",
    )
    return Config.load(config.home, env={"TAU_DATA_DIR": str(config.data_dir)})


def test_the_backend_is_found_by_name(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = _spine_config(tmp_path)
    assert config.sessions.backend == "spine"
    monkeypatch.delenv("TAU_SPINE_URL", raising=False)
    monkeypatch.delenv("TAU_SPINE_TOKEN", raising=False)
    (config.home / ".env").write_text(
        "TAU_SPINE_URL=https://tau.example.com/\nTAU_SPINE_TOKEN=from-dotenv\n", encoding="utf-8"
    )
    store = open_session_store(config)
    assert isinstance(store, SpineSessionStore)
    assert store.spine.url == "https://tau.example.com"
    assert "from-dotenv" not in repr(store)


def test_the_factory_needs_the_spine_variables(tmp_path: Path) -> None:
    config = test_config(tmp_path, sessions=SessionsConfig(backend="spine"))
    with pytest.raises(ConfigError, match="TAU_SPINE_URL and TAU_SPINE_TOKEN"):
        make_store(config, env={})
    with pytest.raises(ConfigError, match="https"):
        make_store(config, env={"TAU_SPINE_URL": "http://tau.example.com", "TAU_SPINE_TOKEN": "t"})
    local = make_store(
        config, env={"TAU_SPINE_URL": "http://127.0.0.1:8787", "TAU_SPINE_TOKEN": "t"}
    )
    assert local.spine.url == "http://127.0.0.1:8787"


def test_the_factory_sends_no_request(tmp_path: Path, spine: FakeSpine, cloud: FakeCloud) -> None:
    config = test_config(tmp_path)
    before = len(spine.requests)
    store = make_store(
        config,
        env={"TAU_SPINE_URL": spine.url, "TAU_SPINE_TOKEN": DEFAULT_HUB_TOKEN},
        transport=spine,
    )
    assert len(spine.requests) == before
    assert store.read_meta("nothing") == {}


def test_every_body_is_json(spine: FakeSpine, spine_store: SpineSessionStore) -> None:
    seen: list[bytes] = []
    original: Callable = spine.handle

    def recording(method, url, headers, body=None):  # noqa: ANN001
        if body:
            seen.append(body)
        return original(method, url, headers, body)

    spine.handle = recording  # type: ignore[method-assign]
    new_session(spine_store)
    spine_store.create_message("s1", AGENT, message(0, "hello"))
    assert seen and all(isinstance(json.loads(body), dict) for body in seen)
