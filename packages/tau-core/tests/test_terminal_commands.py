"""``/clear``, ``/compact``, ``/status`` and ``/model`` in the terminal REPL (issue 072).

The REPL runs in-process with a scripted ``input`` and a captured Rich console, so every line
the user would see is asserted on. The model is ``FakeModel``; no credentials, no network.
"""

from __future__ import annotations

import io
from collections.abc import Callable
from pathlib import Path

import pytest
from rich.console import Console
from tau_core import Config, build_agent
from tau_core.builder import Check
from tau_core.channels.terminal import CLEAR_SCREEN, ReplState, run_repl
from tau_core.config import SessionsConfig
from tau_core.sessions import FileSessionStore, SessionStore, open_session_store
from tau_core.testing import AutoRejectApprover, FakeModel, test_config

HUB_DOWN = Check(
    "hub", "info", "hub is not running (nothing answers on http://127.0.0.1:7877/health)"
)


def feed(lines: list[str]) -> Callable[[str], str]:
    """An ``input`` replacement: the lines in order, then Ctrl-D."""
    remaining = list(lines)

    def read(prompt: str) -> str:
        if not remaining:
            raise EOFError
        return remaining.pop(0)

    return read


@pytest.fixture(autouse=True)
def _no_hub(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("tau_core.status.check_hub", lambda config: HUB_DOWN)


@pytest.fixture
def file_config(tmp_path: Path) -> Config:
    return test_config(tmp_path, sessions=SessionsConfig(backend="file"))


def make_state(
    config: Config,
    store: SessionStore,
    *,
    replies: list | None = None,
    role: str = "brain",
    role_pinned: bool = False,
    session_id: str | None = None,
) -> ReplState:
    approver = AutoRejectApprover()
    agent = build_agent(
        config=config,
        role=role,
        model=FakeModel(replies or []),
        tools=[],
        approver=approver,
        session_id=session_id,
        session_store=store,
        channel="terminal",
    )
    console = Console(
        file=io.StringIO(), markup=False, emoji=False, highlight=False, soft_wrap=True, width=200
    )
    return ReplState(
        config=config,
        store=store,
        approver=approver,
        agent=agent,
        console=console,
        role=role,
        role_pinned=role_pinned,
        language=config.ui.language,
    )


def run(state: ReplState, lines: list[str], *, resume: str | None = None) -> str:
    run_repl(state, resume=resume, input_func=feed(lines))
    return state.console.file.getvalue()


def texts(messages: list) -> list[str]:
    return [block["text"] for m in messages for block in m["content"] if "text" in block]


# -- /clear ------------------------------------------------------------------------------------


def test_clear_erases_the_screen_and_keeps_the_session(file_config: Config) -> None:
    store = open_session_store(file_config)
    state = make_state(file_config, store, replies=["Buyurun."])
    session_id = state.agent.session_id
    out = run(state, ["merhaba", "/clear", "/session"])
    assert CLEAR_SCREEN in out
    after = out.split(CLEAR_SCREEN, 1)[1]
    assert after.startswith(f"tau ready. Profile: home, session: {session_id}. Commands: /help")
    assert "Screen cleared; the session continues (2 messages kept)." in after
    assert f"Session: {session_id}" in after and "Messages: 2" in after
    assert out.count("tau ready.") == 2
    assert len(store.list_messages(session_id, "tau")) == 2  # nothing deleted


def test_clear_alias_and_turkish(file_config: Config) -> None:
    state = make_state(file_config, open_session_store(file_config))
    state.language = "tr"
    out = run(state, ["/temizle"])
    assert CLEAR_SCREEN in out and "tau hazır." in out.split(CLEAR_SCREEN, 1)[1]
    assert "Ekran temizlendi; oturum devam ediyor (0 mesaj korundu)." in out


# -- /compact ----------------------------------------------------------------------------------


def test_compact_end_to_end(file_config: Config) -> None:
    store = open_session_store(file_config)
    assert isinstance(store, FileSessionStore)
    summary = "Kullanıcı salon sıcaklığını sordu; 22 derece olduğu söylendi. Türkçe yazıyor."
    state = make_state(file_config, store, replies=["Salon 22 derece.", summary])
    old = state.agent
    old_model = old.agent.model
    out = run(state, ["Salon kaç derece?", "/compact", "Devam.", "/session"])

    new = state.agent
    assert new is not old and new.session_id != old.session_id
    assert "Compacting 2 messages…" in out
    assert (
        f"Compacted 2 messages into a summary. New session {new.session_id}; the previous "
        f"session {old.session_id} is kept."
    ) in out
    assert summary in out  # the summary itself is printed
    assert f"Session: {new.session_id}" in out and "Messages: 4" in out

    # The summarizer ran on the old agent's model, over a copy of the history, without tools.
    call = old_model.calls[-1]
    assert texts(call.messages) == [
        "Salon kaç derece?",
        "Salon 22 derece.",
        "Write the summary now.",
    ]
    assert not call.tool_specs
    assert len(old.messages) == 2

    # The old session is intact and linked; the new one starts with the seed and inherits the title.
    assert len(store.list_messages(old.session_id, "tau")) == 2
    assert store.read_meta(old.session_id)["compacted_to"] == new.session_id
    assert store.read_meta(old.session_id)["title"] == "Salon kaç derece?"
    new_meta = store.read_meta(new.session_id)
    assert new_meta["compacted_from"] == old.session_id and new_meta["title"] == "Salon kaç derece?"
    stored = [m.to_message() for m in store.list_messages(new.session_id, "tau")]
    assert texts(stored)[0] == (
        f"Summary of the previous conversation (session {old.session_id}):\n\n{summary}"
    )
    assert texts(stored)[1] == "Understood. I will continue from this summary."
    assert texts(stored)[2] == "Devam."
    # The next turn's model saw the seed, then the new prompt.
    assert texts(new.agent.model.calls[0].messages) == texts(stored)[:3]

    # /sessions lists both: compacted sessions are never hidden.
    listing = {s.session_id for s in store.list_sessions()}
    assert {old.session_id, new.session_id} <= listing


def test_compact_resume_shows_the_seed_and_a_focus_reaches_the_model(file_config: Config) -> None:
    store = open_session_store(file_config)
    state = make_state(file_config, store, replies=["Tamam.", "Odak: açık işler."])
    old = state.agent
    run(state, ["Bir şey yap", "/özet açık işler"])
    new_id = state.agent.session_id
    assert old.agent.model.calls[-1].system_prompt.endswith("Focus on: açık işler")

    # A new REPL resuming the compacted session gets the seed as its history.
    second = make_state(file_config, open_session_store(file_config), replies=["Devam."])
    out = run(second, ["/session"], resume=new_id)
    assert f"Resuming: Bir şey yap · {new_id} (2 messages loaded)." in out
    assert "Messages: 2" in out
    assert texts(second.agent.messages)[0].startswith(
        f"Summary of the previous conversation (session {old.session_id}):"
    )


def test_compact_failures_keep_the_current_agent(file_config: Config) -> None:
    store = open_session_store(file_config)
    state = make_state(file_config, store)
    agent = state.agent
    out = run(state, ["/compact"])
    assert "Compaction failed: the session has no messages to summarize." in out
    assert state.agent is agent

    def boom(messages, system_prompt):
        raise RuntimeError("provider down")

    state = make_state(file_config, store, replies=["ok", boom])
    agent = state.agent
    out = run(state, ["hi", "/compact"])
    assert "Compaction failed: the model call failed: provider down." in out
    assert state.agent is agent and len(agent.messages) == 2
    assert "compacted_to" not in store.read_meta(agent.session_id)


# -- /status -----------------------------------------------------------------------------------


def test_status_lines(file_config: Config) -> None:
    store = open_session_store(file_config)
    state = make_state(file_config, store, replies=["Buyurun."], session_id="20260929-120000-abcd")
    out = run(state, ["Merhaba", "/status", "/durum"])
    assert "Profile: home\n" in out
    assert "Session: 20260929-120000-abcd · Merhaba · 2 messages stored · role brain\n" in out
    assert "Model: brain → fake · fake\n" in out
    assert "Context: sliding, window 60 · 2 messages in memory\n" in out
    assert "Tools: 0 registered · 0 need approval (tier 2)\n" in out
    assert "UI language: en\n" in out
    assert "Versions: tau-core " in out
    assert "Hub: hub is not running (nothing answers on http://127.0.0.1:7877/health)\n" in out
    assert out.count("Profile: home\n") == 2  # the alias works too


# -- /model ------------------------------------------------------------------------------------


def test_model_lists_switches_and_persists_the_role(file_config: Config) -> None:
    store = open_session_store(file_config)
    state = make_state(file_config, store, replies=["Buyurun."])
    first = state.agent
    out = run(
        state,
        ["merhaba", "/model", "/model nope", "/model fast", "/model", "/status"],
    )
    assert (
        "Model role: brain (fake)\nRoles in tau.toml:\n  brain  fake · current\n  fast   fake\n"
    ) in out
    assert "Unknown role: nope. Roles: brain, fast, local" in out
    assert "Model role: fast (fake)" in out
    assert "  brain  fake\n  fast   fake · current\n" in out
    assert "role fast" in out  # /status reports the switched role
    assert state.role == "fast" and state.agent.role == "fast"
    assert state.agent is not first and state.agent.session_id == first.session_id
    assert texts(state.agent.messages) == ["merhaba", "Buyurun."]  # the same conversation
    assert store.read_meta(first.session_id)["role"] == "fast"


def test_model_failure_keeps_the_current_agent(
    file_config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    import tau_core.models as models

    monkeypatch.setitem(models.PLANNED_PROVIDERS, "futurebox", "999")
    store = open_session_store(file_config)
    state = make_state(file_config, store)
    agent = state.agent
    out = run(state, ["/model local", "/rol local"])
    # ``local`` is a fake role here; make it fail through an undefined provider instead.
    assert state.agent.role in ("local", "brain")
    roles = dict(file_config.roles)
    from tau_core.config import RoleConfig

    roles["fast"] = RoleConfig(provider="futurebox", model_id="f")  # planned, not available
    state = make_state(file_config.with_overrides(roles=roles), store)
    agent = state.agent
    out = run(state, ["/model fast"])
    assert "Provider 'futurebox' is not supported yet (issue 999)." in out
    assert state.agent is agent and state.role == "brain"
    assert store.read_meta(agent.session_id)["role"] == "brain"  # the role it runs on


def test_resume_honours_the_stored_role_unless_pinned(file_config: Config) -> None:
    store = open_session_store(file_config)
    state = make_state(file_config, store, replies=["Buyurun."])
    first_id = state.agent.session_id
    run(state, ["merhaba", "/model fast", "/new", "/model brain", "/resume"])
    assert state.agent.session_id == first_id
    assert state.role == "fast" and state.agent.role == "fast"  # meta.role won

    # Without --role, --resume comes back on the stored role.
    plain = make_state(file_config, open_session_store(file_config))
    run(plain, [], resume=first_id)
    assert plain.role == "fast" and plain.agent.role == "fast"

    # --role pins the role: the stored one is ignored, and the session now records brain.
    pinned = make_state(
        file_config, open_session_store(file_config), role="brain", role_pinned=True
    )
    out = run(pinned, [], resume=first_id)
    assert f"Resuming: merhaba · {first_id}" in out
    assert pinned.role == "brain" and pinned.agent.role == "brain"
    assert store.read_meta(first_id)["role"] == "brain"


def test_new_and_compact_sessions_remember_the_role(file_config: Config) -> None:
    """M3: every session records the role it runs on, not only the one ``/model`` touched."""
    store = open_session_store(file_config)
    state = make_state(file_config, store, replies=["Buyurun."])
    first_id = state.agent.session_id
    assert store.read_meta(first_id)["role"] == "brain"
    run(state, ["merhaba", "/model fast", "/new", "selam", "/compact"])
    compacted_id = state.agent.session_id
    opened = store.read_meta(compacted_id)["compacted_from"]
    assert opened != first_id  # the session /new opened, then compacted
    assert store.read_meta(opened)["role"] == "fast"
    assert store.read_meta(compacted_id)["role"] == "fast"

    for session_id in (opened, compacted_id):
        again = make_state(file_config, open_session_store(file_config))
        run(again, [], resume=session_id)
        assert again.role == "fast" and again.agent.role == "fast"


def test_model_carries_the_pending_repair_over(file_config: Config) -> None:
    """Nit: the specific repair notice of a failed turn survives the ``/model`` rebuild."""

    def boom(messages, system_prompt):
        raise RuntimeError("provider down")

    store = open_session_store(file_config)
    state = make_state(file_config, store, replies=[boom])
    out = run(state, ["ilk soru", "/model fast", "tekrar"])
    assert "Model call failed: provider down" in out
    sent = state.agent.agent.model.calls[0].messages  # the fast agent's first call
    assert texts(sent) == [
        "ilk soru",
        "(Model call failed: provider down. Details are in the log.)",
        "tekrar",
    ]


def test_context_mismatch_is_one_clear_message(
    file_config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    """m4: a session recorded under ``sliding`` cannot be restored under ``summarize``; every
    path says so in one sentence and keeps the current agent (no traceback)."""
    from click.testing import CliRunner
    from tau_core import SessionContextMismatch
    from tau_core.cli import cli
    from tau_core.config import AgentConfig

    store = open_session_store(file_config)
    recorded = make_state(file_config, store, replies=["Buyurun."])
    run(recorded, ["merhaba"])
    session_id = recorded.agent.session_id
    summarizing = file_config.with_overrides(agent=AgentConfig(context="summarize"))
    expected = (
        f"Session {session_id} was recorded with a different [agent] context setting; "
        "set it back to sliding or start a new session."
    )
    with pytest.raises(SessionContextMismatch, match="set it back to sliding") as info:
        build_agent(config=summarizing, tools=[], session_store=store, session_id=session_id)
    assert str(info.value) == expected and info.value.previous == "sliding"

    # /resume in the REPL: the message, the agent unchanged.
    state = make_state(summarizing, open_session_store(summarizing))
    agent = state.agent
    out = run(state, [f"/resume {session_id}", "/session"])
    assert expected in out and "Traceback" not in out
    assert state.agent is agent and f"Session: {agent.session_id}" in out

    # tau chat --session <id>: exit 2 with the message, no traceback.
    toml = (file_config.home / "tau.toml").read_text(encoding="utf-8")
    toml = toml.replace('backend = "memory"', 'backend = "file"')
    toml = toml.replace("[agent]\n", '[agent]\ncontext = "summarize"\n')
    (file_config.home / "tau.toml").write_text(toml, encoding="utf-8")
    env = {
        "TAU_HOME": str(file_config.home),
        "TAU_DATA_DIR": str(file_config.data_dir),
        "TAU_PROFILE": None,
        "TAU_LANG": None,
    }
    result = CliRunner().invoke(cli, ["chat", "--session", session_id], env=env, input="")
    assert result.exit_code == 2, result.output
    assert expected in result.output and "Traceback" not in result.output

    # The SDK's own refusal (a stored state the pre-check does not see) gets the same shape.
    monkeypatch.setattr("tau_core.agent._check_context_state", lambda *args: None)
    with pytest.raises(SessionContextMismatch, match="set it back or start a new session"):
        build_agent(config=summarizing, tools=[], session_store=store, session_id=session_id)
