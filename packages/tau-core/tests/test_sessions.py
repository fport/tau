"""SessionStore contract (memory and file backends) and the file layout of FileSessionStore."""

from __future__ import annotations

import itertools
import json
import logging
import os
import stat
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from strands.types.exceptions import SessionException
from strands.types.session import Session, SessionAgent, SessionMessage, SessionType
from tau_core import Config, ConfigError
from tau_core.config import SessionsConfig
from tau_core.events import AgentEvent, EventBus
from tau_core.sessions import (
    PLANNED_BACKENDS,
    SESSION_BACKENDS,
    FileSessionStore,
    InvalidSessionId,
    MemorySessionStore,
    SessionStore,
    open_session_store,
)
from tau_core.testing import test_config

ROOT = Path(__file__).resolve().parents[3]
AGENT = "tau"


@pytest.fixture
def ticking_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make ``updated_at`` strictly increasing (one second per write) in both backends."""
    start = datetime(2030, 1, 1, tzinfo=UTC)
    counter = itertools.count()

    def now() -> str:
        return (start + timedelta(seconds=next(counter))).isoformat()

    monkeypatch.setattr("tau_core.sessions.file.utc_now_iso", now)
    monkeypatch.setattr("tau_core.sessions.memory.utc_now_iso", now)


@pytest.fixture(params=["memory", "file"])
def store(request: pytest.FixtureRequest, tmp_path: Path) -> SessionStore:
    if request.param == "memory":
        return MemorySessionStore()
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
    with pytest.raises(SessionException):
        store.create_session(Session(session_id="s1", session_type=SessionType.AGENT))

    agent = store.read_agent("s1", AGENT)
    assert agent is not None and agent.agent_id == AGENT and agent.state == {}
    assert store.read_agent("s1", "other") is None
    assert store.read_agent("missing", AGENT) is None

    store.update_agent("s1", SessionAgent(AGENT, {"k": "v"}, {"removed_message_count": 0}))
    updated = store.read_agent("s1", AGENT)
    assert updated is not None and updated.state == {"k": "v"}
    assert updated.created_at == agent.created_at
    with pytest.raises(SessionException):
        store.update_agent("s1", SessionAgent("ghost", {}, {}))


def test_agent_needs_a_session(store: SessionStore) -> None:
    with pytest.raises(SessionException):
        store.create_agent("missing", SessionAgent(AGENT, {}, {}))


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
    assert store.read_message("s1", AGENT, 4).message["content"][0]["text"] == "m4"
    assert store.read_message("s1", AGENT, 99) is None
    with pytest.raises(SessionException):
        store.list_messages("s1", "ghost")


def test_update_message_keeps_the_original(store: SessionStore) -> None:
    new_session(store)
    store.create_message("s1", AGENT, message(0, "gizli"))
    created = store.read_message("s1", AGENT, 0)
    redacted = message(0, "gizli")
    redacted.redact_message = {"role": "user", "content": [{"text": "[redacted]"}]}
    store.update_message("s1", AGENT, redacted)
    stored = store.read_message("s1", AGENT, 0)
    assert stored.message["content"][0]["text"] == "gizli"
    assert stored.to_message()["content"][0]["text"] == "[redacted]"
    if isinstance(store, FileSessionStore):  # the memory reference store keeps its own copy
        assert stored.created_at == created.created_at
    with pytest.raises(SessionException):
        store.update_message("s1", AGENT, message(7, "yok"))


def test_bytes_survive(store: SessionStore) -> None:
    new_session(store)
    image = {"image": {"format": "png", "source": {"bytes": b"\x89PNG\x00\xff"}}}
    store.create_message("s1", AGENT, SessionMessage({"role": "user", "content": [image]}, 0))
    restored = store.read_message("s1", AGENT, 0).to_message()
    assert restored["content"][0]["image"]["source"]["bytes"] == b"\x89PNG\x00\xff"


def test_meta_merges_and_creates_the_session(store: SessionStore) -> None:
    assert store.read_meta("s9") == {}
    store.write_meta("s9", channel="terminal", profile="home")
    store.write_meta("s9", title="Saat kaç?")
    assert store.read_meta("s9") == {"channel": "terminal", "profile": "home", "title": "Saat kaç?"}
    assert store.read_session("s9") is not None


def test_events_round_trip(store: SessionStore) -> None:
    at = datetime(2026, 9, 29, 12, 30, tzinfo=UTC)
    first = AgentEvent("tool_call", at, "s1", {"tool": "saat", "arguments": {"ş": "ğ"}})
    second = AgentEvent("robot_moved", at, "s1", {"x": 1})  # unknown kinds pass through
    assert store.read_events("s1") == []
    store.append_event("s1", first)  # creates the session record
    store.append_event("s1", second)
    assert store.read_events("s1") == [first, second]
    assert store.read_session("s1") is not None


def test_event_sink_ignores_other_sessions(store: SessionStore) -> None:
    bus = EventBus()
    bus.subscribe(store.event_sink("s1"))
    bus.emit(AgentEvent.create("notice", {"text": "bir"}, session_id="s1"))
    bus.emit(AgentEvent.create("notice", {"text": "iki"}, session_id="s2"))
    bus.emit(AgentEvent.create("notice", {"text": "üç"}))
    assert [e.data["text"] for e in store.read_events("s1")] == ["bir", "üç"]
    assert store.read_events("s2") == []


def test_list_sessions_newest_first(store: SessionStore, ticking_clock: None) -> None:
    for session_id in ("a", "b", "c"):
        store.write_meta(
            session_id, channel="terminal", profile="home", title=f"başlık {session_id}"
        )
    new_session(store, "d")
    store.create_message("d", AGENT, message(0, "merhaba"))
    store.create_message("d", AGENT, message(1, "buyurun", "assistant"))
    store.append_event("a", AgentEvent.create("notice", {"text": "yeni"}, session_id="a"))

    listed = store.list_sessions()
    assert [s.session_id for s in listed] == ["a", "d", "c", "b"]
    assert [s.session_id for s in store.list_sessions(limit=2)] == ["a", "d"]
    by_id = {s.session_id: s for s in listed}
    assert by_id["d"].message_count == 2 and by_id["a"].message_count == 0
    assert by_id["b"].title == "başlık b" and by_id["b"].channel == "terminal"
    assert by_id["b"].profile == "home"
    assert by_id["a"].updated_at > by_id["a"].created_at


# -- registry and config ----------------------------------------------------------------------


def test_file_backend_registered(tmp_path: Path) -> None:
    assert "file" in SESSION_BACKENDS and "file" not in PLANNED_BACKENDS
    config = test_config(tmp_path, sessions=SessionsConfig(backend="file"))
    store = open_session_store(config)
    assert isinstance(store, FileSessionStore)
    assert store.root == config.sessions_dir
    assert isinstance(open_session_store(test_config(tmp_path)), MemorySessionStore)


def test_cloud_backend_still_planned(tmp_path: Path) -> None:
    config = test_config(tmp_path, sessions=SessionsConfig(backend="cloud"))
    with pytest.raises(ConfigError, match="issue 018"):
        open_session_store(config)


def test_repo_tau_toml_uses_the_file_backend() -> None:
    assert Config.load(ROOT, env={}).sessions.backend == "file"


# -- FileSessionStore specifics ---------------------------------------------------------------


def all_files(root: Path) -> set[Path]:
    return {p.relative_to(root) for p in root.rglob("*")}


def test_file_layout(tmp_path: Path) -> None:
    root = tmp_path / "sessions"
    store = FileSessionStore(root)
    new_session(store, "20260929-153012-3f9a")
    store.create_message("20260929-153012-3f9a", AGENT, message(0, "merhaba"))
    store.write_meta("20260929-153012-3f9a", title="merhaba")
    store.append_event(
        "20260929-153012-3f9a", AgentEvent.create("notice", {"text": "x"}, session_id="s")
    )
    assert all_files(root) == {
        Path(p)
        for p in (
            "20260929-153012-3f9a",
            "20260929-153012-3f9a/session.json",
            "20260929-153012-3f9a/meta.json",
            "20260929-153012-3f9a/events.jsonl",
            "20260929-153012-3f9a/agents",
            "20260929-153012-3f9a/agents/tau",
            "20260929-153012-3f9a/agents/tau/agent.json",
            "20260929-153012-3f9a/agents/tau/messages",
            "20260929-153012-3f9a/agents/tau/messages/000000.json",
        )
    }  # no temp files are left behind
    session_dir = root / "20260929-153012-3f9a"
    assert json.loads((session_dir / "meta.json").read_text(encoding="utf-8")) == {
        "title": "merhaba"
    }
    lines = (session_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1 and json.loads(lines[0])["kind"] == "notice"


def test_private_permissions(tmp_path: Path) -> None:
    root = tmp_path / "sessions"
    store = FileSessionStore(root)
    new_session(store)
    store.create_message("s1", AGENT, message(0, "merhaba"))
    store.append_event("s1", AgentEvent.create("notice", {"text": "x"}, session_id="s1"))
    for path in [root, *root.rglob("*")]:
        mode = stat.S_IMODE(path.stat().st_mode)
        assert mode == (0o700 if path.is_dir() else 0o600), (path, oct(mode))


def test_survives_a_new_store_instance(tmp_path: Path) -> None:
    root = tmp_path / "sessions"
    first = FileSessionStore(root)
    new_session(first)
    first.create_message("s1", AGENT, message(0, "merhaba"))
    first.write_meta("s1", title="merhaba")
    first.append_event("s1", AgentEvent.create("notice", {"text": "x"}, session_id="s1"))

    second = FileSessionStore(root)
    assert [m.message_id for m in second.list_messages("s1", AGENT)] == [0]
    assert second.read_meta("s1") == {"title": "merhaba"}
    assert [e.kind for e in second.read_events("s1")] == ["notice"]
    assert second.list_sessions()[0].message_count == 1


def test_create_message_never_overwrites(tmp_path: Path) -> None:
    store = FileSessionStore(tmp_path / "sessions")
    new_session(store)
    store.create_message("s1", AGENT, message(0, "ilk"))
    with pytest.raises(SessionException, match="already exists"):
        store.create_message("s1", AGENT, message(0, "ikinci"))
    assert store.read_message("s1", AGENT, 0).message["content"][0]["text"] == "ilk"


def test_truncated_event_line_is_skipped_and_kept(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    root = tmp_path / "sessions"
    store = FileSessionStore(root)
    store.append_event("s1", AgentEvent.create("notice", {"text": "bir"}, session_id="s1"))
    events_file = root / "s1" / "events.jsonl"
    with events_file.open("a", encoding="utf-8") as f:
        f.write('{"kind": "tool_call", "at": "2026-')  # a crash mid-write
    store.append_event("s1", AgentEvent.create("notice", {"text": "iki"}, session_id="s1"))
    with caplog.at_level(logging.WARNING, logger="tau_core.sessions.file"):
        events = store.read_events("s1")
    assert [e.data["text"] for e in events] == ["bir", "iki"]
    assert "unreadable event line 2" in caplog.text
    assert '"at": "2026-' in events_file.read_text(encoding="utf-8")  # nothing dropped on disk


def test_unreadable_sessions_are_skipped_in_the_listing(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    root = tmp_path / "sessions"
    store = FileSessionStore(root)
    store.write_meta("good", title="iyi")
    (root / "broken").mkdir()
    (root / "broken" / "session.json").write_text("{not json", encoding="utf-8")
    (root / "empty-dir").mkdir()
    (root / "stray.txt").write_text("x", encoding="utf-8")
    (root / "linked").symlink_to(root / "good")
    with caplog.at_level(logging.WARNING, logger="tau_core.sessions.file"):
        assert [s.session_id for s in store.list_sessions()] == ["good"]
    assert "broken" in caplog.text
    assert FileSessionStore(tmp_path / "does-not-exist").list_sessions() == []


def test_symlinks_are_refused(tmp_path: Path) -> None:
    root = tmp_path / "sessions"
    store = FileSessionStore(root)
    store.write_meta("real", title="gerçek")
    (root / "alias").symlink_to(root / "real")
    with pytest.raises(SessionException, match="symlink"):
        store.read_session("alias")
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    (root / "real" / "meta.json").unlink()
    (root / "real" / "meta.json").symlink_to(outside)
    with pytest.raises(SessionException, match="symlink"):
        store.write_meta("real", title="x")
    assert outside.read_text(encoding="utf-8") == "{}"


@pytest.mark.parametrize("bad", ["", "..", ".hidden", "a/b", "../escape", "x y", "a\nb"])
def test_invalid_ids_are_refused(tmp_path: Path, bad: str) -> None:
    store = FileSessionStore(tmp_path / "sessions")
    with pytest.raises(InvalidSessionId) as info:
        store.read_session(bad)
    assert isinstance(info.value, ConfigError) and isinstance(info.value, ValueError)
    assert "Invalid session id" in str(info.value)
    with pytest.raises(InvalidSessionId, match="agent"):
        store.read_agent("ok", bad)
    assert not (tmp_path / "escape").exists()


def test_nothing_is_ever_deleted(tmp_path: Path) -> None:
    deleting = [
        name
        for name in dir(FileSessionStore)
        if any(word in name.lower() for word in ("delete", "remove", "purge", "prune", "clear"))
    ]
    assert deleting == []

    root = tmp_path / "sessions"
    store = FileSessionStore(root)
    seen: set[Path] = set()
    steps: list[Callable[[], object]] = [
        lambda: new_session(store),
        lambda: store.create_message("s1", AGENT, message(0, "bir")),
        lambda: store.create_message("s1", AGENT, message(1, "iki", "assistant")),
        lambda: store.update_message("s1", AGENT, message(1, "iki (düzeltildi)", "assistant")),
        lambda: store.update_agent("s1", SessionAgent(AGENT, {"x": 1}, {})),
        lambda: store.write_meta("s1", title="bir"),
        lambda: store.write_meta("s1", title="başka"),
        lambda: store.append_event("s1", AgentEvent.create("notice", {}, session_id="s1")),
        lambda: store.write_meta("s2", title="ikinci oturum"),
        lambda: store.list_sessions(),
    ]
    for step in steps:
        step()
        now = all_files(root)
        assert seen <= now, f"files disappeared: {seen - now}"
        seen = now
    assert not [p for p in seen if p.name.startswith(".tmp-")]


def test_failed_write_leaves_the_old_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = FileSessionStore(tmp_path / "sessions")
    store.write_meta("s1", title="eski")

    def broken_replace(src: str, dst: str) -> None:
        raise OSError("disk dolu")

    monkeypatch.setattr(os, "replace", broken_replace)
    with pytest.raises(OSError, match="disk dolu"):
        store.write_meta("s1", title="yeni")
    monkeypatch.undo()
    assert store.read_meta("s1") == {"title": "eski"}
    assert not [p for p in (tmp_path / "sessions").rglob(".tmp-*")]
