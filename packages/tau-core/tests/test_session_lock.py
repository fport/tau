"""A session is open in one place at a time (issue 178): ``SessionStore.hold`` and the file
store's ``flock`` on ``<session>/.lock``, taken by ``build_agent`` and released by ``close``."""

from __future__ import annotations

import json
import stat
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from tau_core import Config, MemorySessionStore, build_agent
from tau_core.sessions import FileSessionStore
from tau_core.sessions.base import SessionBusy
from tau_core.sessions.file import LOCK_FILE
from tau_core.testing import FakeModel

HOLDER = textwrap.dedent(
    """
    import sys
    from tau_core.sessions import FileSessionStore

    store = FileSessionStore(sys.argv[1])
    release = store.hold(sys.argv[2], "web")
    print("held", flush=True)
    sys.stdin.read()  # until the parent closes stdin
    release()
    """
)


@pytest.fixture
def store(tmp_path: Path) -> FileSessionStore:
    return FileSessionStore(tmp_path / "sessions")


def _other_process(root: Path, session_id: str) -> subprocess.Popen[str]:
    child = subprocess.Popen(
        [sys.executable, "-c", HOLDER, str(root), session_id],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    assert child.stdout is not None and child.stdout.readline().strip() == "held"
    return child


def test_the_same_channel_may_hold_a_session_twice(store: FileSessionStore) -> None:
    first = store.hold("s-1", "tui")
    second = store.hold("s-1", "tui")
    first()
    with pytest.raises(SessionBusy):
        store.hold("s-1", "web")  # still held by the second hold
    second()
    store.hold("s-1", "web")()


def test_another_channel_of_this_process_is_refused_by_name(store: FileSessionStore) -> None:
    release = store.hold("s-1", "telegram")
    with pytest.raises(SessionBusy) as caught:
        store.hold("s-1", "web")
    assert caught.value.holder["channel"] == "telegram"
    assert "open in telegram" in str(caught.value)
    release()


def test_release_is_idempotent_and_empties_the_lock_file(store: FileSessionStore) -> None:
    release = store.hold("s-1", "tui")
    lock = store.root / "s-1" / LOCK_FILE
    assert json.loads(lock.read_text())["channel"] == "tui"
    assert stat.S_IMODE(lock.stat().st_mode) == 0o600
    release()
    release()
    assert lock.read_text() == ""
    store.hold("s-1", "web")()


def test_another_process_holding_it_is_named(store: FileSessionStore) -> None:
    child = _other_process(store.root, "s-1")
    try:
        with pytest.raises(SessionBusy) as caught:
            store.hold("s-1", "tui")
        assert caught.value.holder["channel"] == "web"
        assert caught.value.holder["pid"] == child.pid
        assert f"open in web (pid {child.pid})" in str(caught.value)
        store.hold("s-2", "tui")()  # other sessions are free
    finally:
        child.communicate("")
    store.hold("s-1", "tui")()


def test_a_dead_holder_leaves_the_session_free(store: FileSessionStore) -> None:
    child = _other_process(store.root, "s-1")
    child.kill()
    child.wait()
    store.hold("s-1", "tui")()


def test_memory_sessions_need_no_lock() -> None:
    store = MemorySessionStore()
    store.hold("s-1", "tui")
    store.hold("s-1", "web")()


def test_build_agent_holds_the_session_until_close(config: Config, store: FileSessionStore) -> None:
    agent = build_agent(config=config, model=FakeModel(), session_store=store, channel="tui")
    with pytest.raises(SessionBusy, match="open in tui"):
        build_agent(
            config=config,
            model=FakeModel(),
            session_store=store,
            session_id=agent.session_id,
            channel="web",
        )
    # The same channel may rebuild on it (``/model``), and closing the old one keeps the new.
    again = build_agent(
        config=config,
        model=FakeModel(),
        session_store=store,
        session_id=agent.session_id,
        channel="tui",
    )
    agent.close()
    with pytest.raises(SessionBusy):
        store.hold(agent.session_id, "web")
    again.close()
    again.close()
    store.hold(agent.session_id, "web")()


def test_a_failed_build_releases_the_session(
    config: Config, store: FileSessionStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    import tau_core.agent as agent_module

    def broken(*args: object, **kwargs: object) -> None:
        raise ValueError("the SDK refused")

    monkeypatch.setattr(agent_module, "Agent", broken)
    with pytest.raises(ValueError, match="the SDK refused"):
        build_agent(config=config, model=FakeModel(), session_store=store, session_id="s-9")
    store.hold("s-9", "web")()


def test_the_lock_file_is_not_a_session(config: Config, store: FileSessionStore) -> None:
    agent = build_agent(config=config, model=FakeModel(["Merhaba."]), session_store=store)
    [summary] = store.list_sessions()
    assert summary.session_id == agent.session_id
    agent.close()
