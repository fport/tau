"""``/clear``, ``/compact``, ``/status``, ``/model`` and the thirteen-row menu (072, 083)."""

from __future__ import annotations

import threading
from datetime import UTC
from pathlib import Path

import pytest
from helpers import SESSION_ID, finish, fixed_clock, make_app, send, wait_until
from tau_core import MemorySessionStore, Tier, tau_tool
from tau_core.builder import Check
from tau_core.testing import FakeModel, ToolCall, test_config
from tau_tui import build_app
from tau_tui.composer import CommandMenu, PromptArea
from tau_tui.transcript import InfoCard, NoticeRow, Turn, WelcomeCard

SUMMARY = "Kullanıcı salon sıcaklığını sordu; 22 derece dendi. Kullanıcı Türkçe yazıyor."
HUB_DOWN = Check(
    "hub", "info", "hub is not running (nothing answers on http://127.0.0.1:7877/health)"
)


@pytest.fixture(autouse=True)
def _no_hub(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("tau_core.status.check_hub", lambda config: HUB_DOWN)


def slow_tool(release: threading.Event):
    @tau_tool(tier=Tier.READ)
    def slow() -> str:
        """Blocks until the test releases it."""
        release.wait(5)
        return "x"

    return slow


def stored_app(tmp_path: Path, replies: list, **kw):
    config = test_config(tmp_path)
    store = MemorySessionStore()
    app = build_app(
        config,
        model=FakeModel(replies),
        tools=[],
        session_store=store,
        session_id=SESSION_ID,
        clock=fixed_clock,
        tz=UTC,
        motion=False,
        show_durations=False,
        **kw,
    )
    return app, store


def notices(app) -> list[str]:
    return [row.content.plain for row in app.transcript.query(NoticeRow)]


def track_close(agent) -> list[bool]:
    closed: list[bool] = []
    original = agent.close
    agent.close = lambda: (closed.append(True), original())  # type: ignore[method-assign]
    return closed


# -- /clear --------------------------------------------------------------------------------------


async def test_clear_empties_the_transcript_and_keeps_the_session(tmp_path: Path) -> None:
    app, store = stored_app(tmp_path, ["Salon 22 derece."])
    async with app.run_test(size=(80, 24)) as pilot:
        assert app.query(WelcomeCard)
        await send(pilot, "Salon kaç derece?")
        await finish(pilot)
        await send(pilot, "/help")
        await pilot.pause()
        assert app.query(Turn) and app.query(InfoCard)
        agent = app.agent
        await send(pilot, "/clear")
        await pilot.pause()
        assert not app.query(Turn) and not app.query(InfoCard) and not app.query(WelcomeCard)
        assert not app.transcript.query("#fold")
        assert notices(app) == ["▸ Screen cleared; the session continues (2 messages kept)."]
        assert app.agent is agent and app.agent.session_id == SESSION_ID
        assert len(agent.messages) == 2 and len(store.list_messages(SESSION_ID, "tau")) == 2
        assert app.transcript.tool_cards == {} and app.transcript.folded == 0
        assert SESSION_ID in app.header.text
        await send(pilot, "Devam")  # the conversation goes on in the same session
        await finish(pilot)
        assert len(agent.messages) == 4 and app.query(Turn)


async def test_clear_removes_the_welcome_card_and_the_turkish_alias_works(tmp_path: Path) -> None:
    app = make_app(tmp_path, [])
    async with app.run_test(size=(80, 24)) as pilot:
        app.language = "tr"
        await send(pilot, "/temizle")
        await pilot.pause()
        assert not app.query(WelcomeCard)
        assert notices(app) == ["▸ Ekran temizlendi; oturum devam ediyor (0 mesaj korundu)."]
        assert app.header.glyph.state == "idle"


async def test_clear_is_refused_while_busy(tmp_path: Path) -> None:
    release = threading.Event()
    app = make_app(tmp_path, [[ToolCall("slow", {})], "ok"], tools=[slow_tool(release)])
    async with app.run_test(size=(80, 24), notifications=True) as pilot:
        await send(pilot, "go")
        await wait_until(pilot, lambda: app.busy)
        await send(pilot, "/clear")
        await pilot.pause()
        assert app.query(Turn)  # nothing was removed
        assert any("before clearing the screen" in str(n.message) for n in app._notifications)
        release.set()
        await finish(pilot)


# -- /compact ------------------------------------------------------------------------------------


async def test_compact_opens_a_seeded_session_and_keeps_the_old_one(tmp_path: Path) -> None:
    app, store = stored_app(tmp_path, ["Salon 22 derece.", SUMMARY, "Devam ediyorum."])
    model = app.agent.agent.model
    async with app.run_test(size=(80, 24)) as pilot:
        await send(pilot, "Salon kaç derece?")
        await finish(pilot)
        old = app.agent
        closed = track_close(old)
        await send(pilot, "/compact")
        await wait_until(pilot, lambda: app.agent.session_id != SESSION_ID and not app.busy)
        await pilot.pause()
        new = app.agent
        assert closed == [True]
        assert store.list_sessions()[0].session_id == new.session_id  # newest, not the old one
        assert store.read_meta(new.session_id)["role"] == "brain"
        assert new.session_id in app.header.text and SESSION_ID not in app.header.text

        # The summarizer used the same model over a copy of the history, without tools.
        summarizer_call = model.calls[1]
        assert "compacting a conversation" in summarizer_call.system_prompt
        assert [b["text"] for m in summarizer_call.messages for b in m["content"]] == [
            "Salon kaç derece?",
            "Salon 22 derece.",
            "Write the summary now.",
        ]
        assert not summarizer_call.tool_specs
        assert len(old.messages) == 2

        # Reset like /new, then the summary card, then the notice; the events pane is empty.
        assert not app.query(Turn) and not app.query(WelcomeCard)
        card = app.query(InfoCard).last().content.plain
        assert card.startswith(f"Summary of the previous conversation (session {SESSION_ID}):")
        assert SUMMARY in card
        assert notices(app)[-1] == (
            f"▸ Compacted 2 messages into a summary. New session {new.session_id}; the previous "
            f"session {SESSION_ID} is kept."
        )
        assert app.events_pane.text.strip() == ""

        # Both sessions in the store: the old one intact, the new one seeded and linked.
        assert len(store.list_messages(SESSION_ID, "tau")) == 2
        assert store.read_meta(SESSION_ID)["compacted_to"] == new.session_id
        assert store.read_meta(new.session_id)["compacted_from"] == SESSION_ID
        assert store.read_meta(new.session_id)["title"] == "Salon kaç derece?"
        assert len(store.list_messages(new.session_id, "tau")) == 2
        assert [m["role"] for m in new.messages] == ["user", "assistant"]
        assert {s.session_id for s in store.list_sessions()} >= {SESSION_ID, new.session_id}

        # The conversation continues from the seed.
        await send(pilot, "Devam")
        await finish(pilot)
        assert "Devam ediyorum." in app.transcript.text
        sent = [b["text"] for m in model.calls[-1].messages for b in m["content"]]
        assert sent[0].startswith("Summary of the previous conversation") and sent[-1] == "Devam"
        assert len(store.list_messages(new.session_id, "tau")) == 4


async def test_compact_failures_keep_the_current_agent(tmp_path: Path) -> None:
    def boom(messages, system_prompt):
        raise RuntimeError("provider down")

    app, store = stored_app(tmp_path, ["ok", boom])
    async with app.run_test(size=(80, 24)) as pilot:
        agent = app.agent
        await send(pilot, "/özet")
        await pilot.pause()
        assert notices(app)[-1] == (
            "▸ Compaction failed: the session has no messages to summarize."
        )
        assert app.agent is agent and app.query(WelcomeCard)
        await send(pilot, "hi")
        await finish(pilot)
        await send(pilot, "/compact")
        await wait_until(pilot, lambda: any("Compaction failed" in n for n in notices(app)))
        await wait_until(pilot, lambda: not app.busy)
        assert notices(app)[-1] == "▸ Compaction failed: the model call failed: provider down."
        assert app.agent is agent and len(agent.messages) == 2
        assert "compacted_to" not in store.read_meta(SESSION_ID)


async def test_compact_is_refused_while_busy(tmp_path: Path) -> None:
    release = threading.Event()
    app = make_app(tmp_path, [[ToolCall("slow", {})], "ok"], tools=[slow_tool(release)])
    async with app.run_test(size=(80, 24), notifications=True) as pilot:
        await send(pilot, "go")
        await wait_until(pilot, lambda: app.busy)
        await send(pilot, "/compact")
        await pilot.pause()
        assert app.agent.session_id == SESSION_ID
        assert any("before switching" in str(n.message) for n in app._notifications)
        release.set()
        await finish(pilot)


# -- /status -------------------------------------------------------------------------------------


async def test_status_card(tmp_path: Path) -> None:
    app, store = stored_app(tmp_path, ["Buyurun."])
    async with app.run_test(size=(80, 24)) as pilot:
        await send(pilot, "Merhaba")
        await finish(pilot)
        await send(pilot, "/status")
        await wait_until(pilot, lambda: bool(app.query(InfoCard)))
        lines = app.query(InfoCard).last().content.plain.splitlines()
        assert lines[0] == "Profile: home"
        assert lines[1] == f"Session: {SESSION_ID} · Merhaba · 2 messages stored · role brain"
        assert lines[2] == "Model: brain → fake · fake"
        assert lines[3] == "Context: sliding, window 60 · 2 messages in memory"
        assert lines[4] == "Tools: 0 registered · 0 need approval (tier 2)"
        assert lines[5] == "UI language: en"
        assert lines[6].startswith("Versions: tau-core ") and "tau-tui" in lines[6]
        assert (
            lines[7] == "Hub: hub is not running (nothing answers on http://127.0.0.1:7877/health)"
        )
        assert "/" not in "".join(lines).replace("http://127.0.0.1:7877/health", "")


async def test_status_runs_while_busy(tmp_path: Path) -> None:
    release = threading.Event()
    app = make_app(tmp_path, [[ToolCall("slow", {})], "ok"], tools=[slow_tool(release)])
    async with app.run_test(size=(80, 24)) as pilot:
        await send(pilot, "go")
        await wait_until(pilot, lambda: app.busy)
        await send(pilot, "/durum")
        await wait_until(pilot, lambda: bool(app.query(InfoCard)))
        card = app.query(InfoCard).last().content.plain
        assert card.startswith("Profile: home") and "Tools: 1 registered" in card
        release.set()
        await finish(pilot)


# -- /model --------------------------------------------------------------------------------------


async def test_model_lists_switches_and_remembers_the_role(tmp_path: Path) -> None:
    app, store = stored_app(tmp_path, ["Buyurun."])
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        assert app.header.text.endswith("brain · en") and "brain → fake" in app.transcript.text
        await send(pilot, "/model")
        await pilot.pause()
        assert app.query(InfoCard).last().content.plain.splitlines() == [
            "Model role: brain (fake)",
            "Roles in tau.toml:",
            "  brain  fake · current",
            "  fast   fake",
            "  local  fake",
        ]
        await send(pilot, "/model nope")
        await pilot.pause()
        assert notices(app)[-1] == "▸ Unknown role: nope. Roles: brain, fast, local"
        assert app.role == "brain"

        first = app.agent
        closed = track_close(first)
        await send(pilot, "/model fast")
        await wait_until(pilot, lambda: app.role == "fast")
        await pilot.pause()
        assert closed == [True] and app.agent is not first
        assert app.agent.session_id == SESSION_ID
        assert notices(app)[-1] == "▸ Model role: fast (fake)"
        assert app.header.text.endswith("fast · en")
        assert "fast → fake" in app.query_one(WelcomeCard).text  # the welcome card follows
        assert store.read_meta(SESSION_ID)["role"] == "fast"

        await send(pilot, "Merhaba")
        await finish(pilot)
        assert "Buyurun." in app.transcript.text

        # /new keeps the current role; a resumed session comes back on its stored role.
        await send(pilot, "/new")
        await wait_until(pilot, lambda: app.agent.session_id != SESSION_ID)
        assert app.role == "fast"
        await send(pilot, "/rol brain")
        await wait_until(pilot, lambda: app.role == "brain")
        await send(pilot, f"/resume {SESSION_ID}")
        await wait_until(pilot, lambda: app.agent.session_id == SESSION_ID)
        await pilot.pause()
        assert app.role == "fast" and app.header.text.endswith("fast · en")


async def test_build_app_honours_the_stored_role_unless_pinned(tmp_path: Path) -> None:
    config = test_config(tmp_path)
    store = MemorySessionStore()
    store.write_meta(SESSION_ID, role="fast")
    kw = dict(model=FakeModel(), tools=[], session_store=store, session_id=SESSION_ID)
    remembered = build_app(config, **kw)
    assert remembered.role == "fast" and not remembered.role_pinned
    remembered.agent.close()
    pinned = build_app(config, role="brain", **kw)
    assert pinned.role == "brain" and pinned.role_pinned
    pinned.agent.close()


async def test_model_switch_is_refused_while_busy(tmp_path: Path) -> None:
    release = threading.Event()
    app = make_app(tmp_path, [[ToolCall("slow", {})], "ok"], tools=[slow_tool(release)])
    async with app.run_test(size=(80, 24), notifications=True) as pilot:
        await send(pilot, "go")
        await wait_until(pilot, lambda: app.busy)
        agent = app.agent
        await send(pilot, "/model fast")
        await pilot.pause()
        assert app.agent is agent and app.role == "brain"
        assert any("before switching the model" in str(n.message) for n in app._notifications)
        await send(pilot, "/model")  # the listing is read-only and allowed
        await wait_until(pilot, lambda: bool(app.query(InfoCard)))
        release.set()
        await finish(pilot)


async def test_model_failure_keeps_the_current_agent(tmp_path: Path) -> None:
    from tau_core.config import RoleConfig

    config = test_config(tmp_path)
    roles = dict(config.roles)
    roles["fast"] = RoleConfig(provider="ollama", model_id="qwen")  # planned: fails to build
    app = build_app(
        config.with_overrides(roles=roles),
        model=None,
        tools=[],
        session_store=MemorySessionStore(),
        session_id=SESSION_ID,
        motion=False,
    )
    async with app.run_test(size=(80, 24)) as pilot:
        agent = app.agent
        await send(pilot, "/model fast")
        await pilot.pause()
        assert notices(app)[-1] == "▸ Provider 'ollama' is not supported yet (issue 012)."
        assert app.agent is agent and app.role == "brain"


# -- the command menu ----------------------------------------------------------------------------


async def test_menu_shows_thirteen_rows_and_completes_compact(tmp_path: Path) -> None:
    app = make_app(tmp_path, ["Merhaba."])
    async with app.run_test(size=(80, 24)) as pilot:
        await send(pilot, "Merhaba tau")
        await finish(pilot)
        menu = app.query_one(CommandMenu)
        await pilot.press("slash")
        await pilot.pause()
        assert menu.open and menu.option_count == 13
        assert menu.region.height == 15 and menu.max_scroll_y == 0  # every row on screen
        assert [cmd.name for cmd in menu.commands] == [
            "help", "tools", "sessions", "resume", "new", "session",
            "compact", "clear", "status", "model", "lang", "settings", "quit",
        ]  # fmt: skip
        assert app.transcript.region.height == 24 - 1 - 15 - 3 - 1
        assert app.transcript.is_vertical_scroll_end  # the transcript keeps its bottom
        for char in "co":
            await pilot.press(char)
        await pilot.pause()
        assert [cmd.name for cmd in menu.commands] == ["compact"]
        await pilot.press("tab")
        assert app.composer.text == "/compact "
        await pilot.press("escape")
        app.query_one(PromptArea).load_text("")
        await pilot.press("slash")
        for char in "st":
            await pilot.press(char)
        await pilot.pause()
        assert menu.highlighted_command is not None and menu.highlighted_command.name == "status"
        await pilot.press("enter")
        await wait_until(pilot, lambda: bool(app.query(InfoCard)))
        assert app.query(InfoCard).last().content.plain.startswith("Profile: home")


async def test_menu_scrolls_in_the_short_band(tmp_path: Path) -> None:
    app = make_app(tmp_path, [])
    async with app.run_test(size=(80, 18)) as pilot:
        await pilot.press("slash")
        await pilot.pause()
        menu = app.query_one(CommandMenu)
        assert menu.open and menu.option_count == 13
        assert menu.region.height == 8 and menu.max_scroll_y > 0
        for _ in range(12):
            await pilot.press("down")
        await pilot.pause()
        assert menu.highlighted_command is not None and menu.highlighted_command.name == "quit"


# -- review findings: the worker, the stored role, the context mismatch --------------------


async def test_compaction_runs_in_a_worker_status_works_and_esc_cancels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M1: summarizing never blocks the message pump. While the model writes the summary the
    chrome is busy, ``/status`` still answers, switches are refused, and Esc cancels the
    summarizer through the SDK's cancel signal; the current session is untouched."""
    import asyncio

    from tau_core import CompactionCancelled

    gate = asyncio.Event()  # opens when the fake model "answers"
    checkpoint = asyncio.Event()  # the SDK's next cancel checkpoint, released by the test
    calls: list[str | None] = []

    async def fake_summarize(agent, *, focus=None, cancel_signal=None):
        calls.append(focus)
        while not gate.is_set():
            if cancel_signal is not None and cancel_signal.is_set():
                await checkpoint.wait()
                raise CompactionCancelled("compaction was cancelled.")
            await asyncio.sleep(0.01)
        return SUMMARY

    monkeypatch.setattr("tau_tui.app.summarize", fake_summarize)
    app, store = stored_app(tmp_path, ["Buyurun."])
    async with app.run_test(size=(80, 24), notifications=True) as pilot:
        await send(pilot, "Merhaba")
        await finish(pilot)
        agent = app.agent
        await send(pilot, "/compact açık işler")
        await wait_until(pilot, lambda: app.busy and "✻ Summarizing…" in app.transcript.text)
        assert calls == ["açık işler"]
        assert app.hint.text.startswith("esc cancel")
        await send(pilot, "/status")  # read-only: answered while the summary is being written
        await wait_until(pilot, lambda: bool(app.query(InfoCard)))
        assert app.query(InfoCard).last().content.plain.startswith("Profile: home")
        await send(pilot, "/new")
        await pilot.pause()
        assert any("before switching" in str(n.message) for n in app._notifications)
        assert app.agent is agent and app.busy
        await pilot.press("escape")
        await wait_until(pilot, lambda: "✻ Cancelling…" in app.transcript.text)
        assert app.busy and app.agent is agent  # still waiting for the SDK's checkpoint
        checkpoint.set()
        await wait_until(pilot, lambda: not app.busy)
        assert notices(app)[-1] == "▸ Compaction cancelled; the session continues."
        assert app.agent is agent and app.agent.session_id == SESSION_ID
        assert "Summarizing" not in app.transcript.text and app.query(Turn)
        assert "compacted_to" not in store.read_meta(SESSION_ID)

        gate.set()  # the next compaction runs to the end, still from the worker
        await send(pilot, "/compact")
        await wait_until(pilot, lambda: app.agent.session_id != SESSION_ID and not app.busy)
        assert store.read_meta(SESSION_ID)["compacted_to"] == app.agent.session_id
        assert SUMMARY in app.query(InfoCard).last().content.plain


async def test_new_and_compact_sessions_remember_the_role(tmp_path: Path) -> None:
    """M3: sessions opened by ``/new`` and ``/compact`` record the role, so a later
    ``build_app(session_id=...)`` (``tau tui --resume``) comes back on it."""
    app, store = stored_app(tmp_path, ["Buyurun.", "Tamam.", SUMMARY])
    async with app.run_test(size=(80, 24)) as pilot:
        await send(pilot, "/model fast")
        await wait_until(pilot, lambda: app.role == "fast")
        await send(pilot, "/new")
        await wait_until(pilot, lambda: app.agent.session_id != SESSION_ID)
        opened = app.agent.session_id
        assert store.read_meta(opened)["role"] == "fast"
        await send(pilot, "selam")
        await finish(pilot)
        await send(pilot, "/compact")
        await wait_until(pilot, lambda: app.agent.session_id != opened and not app.busy)
        compacted = app.agent.session_id
        assert store.read_meta(compacted)["role"] == "fast"
        assert store.read_meta(compacted)["compacted_from"] == opened
    for session_id in (opened, compacted):
        again = build_app(
            test_config(tmp_path), model=FakeModel(), tools=[], session_store=store,
            session_id=session_id, motion=False,
        )  # fmt: skip
        assert again.role == "fast"
        again.agent.close()


async def test_resume_under_another_context_is_one_clear_notice(tmp_path: Path) -> None:
    """m4: a session recorded under ``sliding`` opened under ``summarize``: a notice, the
    current agent unchanged, in the app and in ``tau tui --resume`` alike."""
    from click.testing import CliRunner
    from tau_core import Config, build_agent, open_session_store
    from tau_core.config import AgentConfig
    from tau_tui.cli import tui

    config = test_config(tmp_path)
    store = MemorySessionStore()
    recorded = build_agent(
        config=config, model=FakeModel(["ok"]), tools=[], session_store=store, session_id="rec"
    )
    await recorded.ask("merhaba")
    recorded.close()
    expected = (
        "Session rec was recorded with a different [agent] context setting; "
        "set it back to sliding or start a new session."
    )
    app = build_app(
        config.with_overrides(agent=AgentConfig(context="summarize")),
        model=FakeModel(),
        tools=[],
        session_store=store,
        session_id=SESSION_ID,
        motion=False,
    )
    async with app.run_test(size=(80, 24)) as pilot:
        agent = app.agent
        await send(pilot, "/resume rec")
        await pilot.pause()
        assert notices(app)[-1] == f"▸ {expected}"
        assert app.agent is agent and app.agent.session_id == SESSION_ID

    # ``tau tui --resume rec`` with the file store: exit 2 with the message, no traceback.
    home = config.home
    toml = (home / "tau.toml").read_text(encoding="utf-8")
    toml = toml.replace('backend = "memory"', 'backend = "file"')
    (home / "tau.toml").write_text(toml, encoding="utf-8")
    data = str(tmp_path / "data")
    file_config = Config.load(home, env={"TAU_DATA_DIR": data})
    file_store = open_session_store(file_config)
    recorded = build_agent(
        config=file_config,
        model=FakeModel(["ok"]),
        tools=[],
        session_store=file_store,
        session_id="rec",
    )
    await recorded.ask("merhaba")
    recorded.close()
    (home / "tau.toml").write_text(
        toml.replace("[agent]\n", '[agent]\ncontext = "summarize"\n'), encoding="utf-8"
    )
    env = {"TAU_HOME": str(home), "TAU_DATA_DIR": data, "TAU_PROFILE": None, "TAU_LANG": None}
    result = CliRunner().invoke(tui, ["--resume", "rec"], env=env, prog_name="tau tui")
    assert result.exit_code == 2, result.output
    assert expected in result.output and "Traceback" not in result.output
