"""``/sessions``, ``/resume``, ``/new``, ``/session``, the picker and event filtering."""

from __future__ import annotations

from datetime import UTC, timedelta
from pathlib import Path

from helpers import (
    FIXED_NOW,
    PATH_FRAGMENTS,
    SESSION_ID,
    finish,
    fixed_clock,
    seed_sessions,
    send,
    store_clock,
    wait_until,
)
from tau_core import AgentEvent, MemorySessionStore, build_agent
from tau_core.testing import FakeModel, test_config
from tau_tui import build_app
from tau_tui.sessions import SessionPicker, format_session, relative_date
from tau_tui.transcript import InfoCard, NoticeRow, ReplyBlock, WelcomeCard


async def _seed(config, count: int) -> tuple[MemorySessionStore, list[str]]:
    store = MemorySessionStore()
    ids = []
    for n in range(count):
        session_id = f"20260928-1200{n:02d}-{n:04d}"
        agent = build_agent(
            config=config,
            model=FakeModel([f"reply {n}"]),
            tools=[],
            session_store=store,
            session_id=session_id,
            channel="tui",
        )
        await agent.ask(f"question {n}")
        agent.close()
        ids.append(session_id)
    # an empty session must never be listed
    store.write_meta("20260928-000000-0000", channel="tui", profile="home")
    return store, ids


def _app(config, store):
    return build_app(
        config,
        model=FakeModel(["ok"]),
        tools=[],
        session_store=store,
        session_id=SESSION_ID,
        clock=fixed_clock,
        tz=UTC,
        motion=False,
        show_durations=False,
    )


async def test_sessions_and_resume_by_number_id_and_current(tmp_path: Path) -> None:
    config = test_config(tmp_path)
    store, ids = await _seed(config, 12)
    app = _app(config, store)
    async with app.run_test(size=(80, 24)) as pilot:
        await send(pilot, "/sessions")
        await pilot.pause()
        card = app.query(InfoCard).last().content.plain
        lines = card.splitlines()
        assert lines[0] == "Recent sessions:"
        assert len(lines) == 11 and lines[1].startswith(" 1  question 11")
        assert SESSION_ID not in card and "20260928-000000-0000" not in card
        assert app.last_listing[1] == ids[10]

        old_agent = app.agent
        closed = []
        old_close = old_agent.close
        old_agent.close = lambda: (closed.append(True), old_close())  # type: ignore[method-assign]
        await send(pilot, "/resume 2")
        await wait_until(pilot, lambda: app.agent.session_id == ids[10])
        await pilot.pause()
        assert closed == [True]
        assert ids[10] in app.header.text
        assert "› question 10" in app.transcript.text
        assert app.query_one(ReplyBlock).source == "reply 10"
        assert f"Resuming: question 10 · {ids[10]} (2 messages loaded)." in app.transcript.text
        assert "── live ──" not in app.events_pane.text  # no stored events for that session

        # live events are filtered by session id
        bus = app.bus
        bus.emit(
            AgentEvent.create("notice", {"message": "mine"}, session_id=ids[10], clock=fixed_clock)
        )
        bus.emit(
            AgentEvent.create(
                "notice", {"message": "theirs"}, session_id=SESSION_ID, clock=fixed_clock
            )
        )
        await wait_until(pilot, lambda: "mine" in app.events_pane.text)
        assert "theirs" not in app.events_pane.text

        await send(pilot, f"/resume {ids[10]}")
        await pilot.pause()
        assert f"You are already in this session: {ids[10]}." in app.transcript.text
        await send(pilot, "/resume no-such-session")
        await pilot.pause()
        assert "Session not found: no-such-session." in app.transcript.text
        await send(pilot, "/resume 99")
        await pilot.pause()
        assert "There is no session 99 in the list (1-10)." in app.transcript.text

        await send(pilot, "/new")
        await wait_until(pilot, lambda: app.agent.session_id not in (SESSION_ID, ids[10]))
        await pilot.pause()
        assert app.query(WelcomeCard)
        assert f"New session: {app.agent.session_id}." in app.transcript.text
        assert app.events_pane.text.strip() == ""

        await send(pilot, "/session")
        await pilot.pause()
        info = app.query(InfoCard).last().content.plain
        assert f"Session: {app.agent.session_id}" in info
        assert "Title: (untitled)" in info and "Messages: 0" in info and "Store: memory" in info
        assert "/" not in info.replace("Session:", "")  # never a path


async def test_resume_without_argument_takes_the_most_recent(tmp_path: Path) -> None:
    config = test_config(tmp_path)
    store, ids = await _seed(config, 2)
    app = _app(config, store)
    async with app.run_test(size=(80, 24)) as pilot:
        await send(pilot, "/resume")
        await wait_until(pilot, lambda: app.agent.session_id == ids[1])


async def test_picker_enter_resumes_n_creates_esc_closes(tmp_path: Path) -> None:
    config = test_config(tmp_path)
    store, ids = await _seed(config, 3)
    app = _app(config, store)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press("ctrl+r")
        await wait_until(pilot, lambda: isinstance(app.screen, SessionPicker))
        assert "◆ Sessions" in app.screen.query_one("#title").content.plain
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, SessionPicker) and app.agent.session_id == SESSION_ID
        await pilot.press("f2")
        await wait_until(pilot, lambda: isinstance(app.screen, SessionPicker))
        await pilot.press("down")
        await pilot.press("enter")
        await wait_until(pilot, lambda: app.agent.session_id == ids[1])
        await pilot.press("ctrl+r")
        await wait_until(pilot, lambda: isinstance(app.screen, SessionPicker))
        await pilot.press("n")
        await wait_until(pilot, lambda: app.agent.session_id not in (SESSION_ID, *ids))
        assert app.query(WelcomeCard)


async def test_picker_shows_markup_looking_titles_verbatim(tmp_path: Path) -> None:
    """Titles are the user's first message: ``[/x]`` must not be parsed as Textual markup
    (it raised ``MarkupError`` from the option list and took the whole app down)."""
    from textual.widgets import OptionList

    config = test_config(tmp_path)
    store = MemorySessionStore()
    titles = ["see [/x] closing tag", "use [bold]bold[/] words"]
    ids = await seed_sessions(config, store, titles, days_ago=[1, 2])
    app = _app(config, store)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press("ctrl+r")
        await wait_until(pilot, lambda: isinstance(app.screen, SessionPicker))
        await pilot.pause()
        listing = app.screen.query_one("#list", OptionList)
        rows = [str(listing.get_option_at_index(i).prompt) for i in range(listing.option_count)]
        assert [t in row for t, row in zip(titles, rows, strict=True)] == [True, True]
        svg = app.export_screenshot()  # spaces are ``&#160;`` in the SVG: check the tags alone
        assert app.is_running and "[/x]" in svg and "[bold]bold[/]" in svg
        await pilot.press("enter")  # row 1 is the newest: titles[0]
        await wait_until(pilot, lambda: app.agent.session_id == ids[0])
        await send(pilot, "/sessions")
        await pilot.pause()
        text = app.transcript.text  # the resumed history and the ``/sessions`` card
        assert "see [/x] closing tag" in text and "use [bold]bold[/] words" in text
        await pilot.resize_terminal(160, 45)
        await pilot.pause()
        app.sidebar.refresh_list(store, app.agent.session_id, FIXED_NOW)
        assert "see [/x] closing tag" in app.sidebar.text


async def test_switching_is_refused_while_busy(tmp_path: Path) -> None:
    import threading

    from tau_core import Tier, tau_tool
    from tau_core.testing import ToolCall

    release = threading.Event()

    @tau_tool(tier=Tier.READ)
    def slow() -> str:
        """Blocks."""
        release.wait(5)
        return "x"

    config = test_config(tmp_path)
    store, ids = await _seed(config, 1)
    app = build_app(
        config,
        model=FakeModel([[ToolCall("slow", {})], "ok"]),
        tools=[slow],
        session_store=store,
        session_id=SESSION_ID,
        clock=fixed_clock,
        tz=UTC,
        motion=False,
    )
    async with app.run_test(size=(80, 24), notifications=True) as pilot:
        await send(pilot, "go")
        await wait_until(pilot, lambda: app.busy)
        await send(pilot, "/new")
        await pilot.pause()
        assert app.agent.session_id == SESSION_ID
        assert any("before switching" in str(n.message) for n in app._notifications)
        await pilot.press("ctrl+r")
        await pilot.pause()
        assert not isinstance(app.screen, SessionPicker)
        release.set()
        await finish(pilot)


async def test_failed_rebuild_keeps_the_current_agent(tmp_path: Path) -> None:
    config = test_config(tmp_path)
    store, ids = await _seed(config, 1)
    app = _app(config, store)

    def broken(session_id):
        raise RuntimeError("store exploded")

    async with app.run_test(size=(80, 24)) as pilot:
        app.agent_factory = broken
        await send(pilot, "/resume")
        await pilot.pause()
        assert app.agent.session_id == SESSION_ID
        assert "Could not open the session: store exploded" in app.transcript.text
        await send(pilot, "still works?")
        await finish(pilot)
        assert "ok" in app.transcript.text


def test_relative_dates_and_rows() -> None:
    from tau_core.sessions import SessionSummary

    now = FIXED_NOW
    assert relative_date(now.isoformat(), now, "en") == "today 12:00"
    assert relative_date((now - timedelta(days=1)).isoformat(), now, "en") == "yesterday"
    assert relative_date((now - timedelta(days=2)).isoformat(), now, "en") == "Sep 27"
    assert relative_date((now - timedelta(days=2)).isoformat(), now, "tr") == "27.09"
    assert relative_date("garbage", now, "en") == "garbage"
    summary = SessionSummary(
        session_id="s",
        created_at=now.isoformat(),
        updated_at=now.isoformat(),
        channel="tui",
        profile="travel",
        title="",
        message_count=4,
    )
    row = format_session(summary, 3, "en", now, width=70)
    assert (
        row.startswith(" 3  (untitled)") and "today 12:00" in row and row.endswith("4 msgs  travel")
    )


async def test_sidebar_lists_the_current_session_first_and_a_pick_switches(tmp_path: Path) -> None:
    from textual.widgets import OptionList

    config = test_config(tmp_path)
    store = MemorySessionStore()
    ids = await seed_sessions(config, store, ["alarm", "kalibrasyon"], days_ago=[1, 3])
    with store_clock(FIXED_NOW):
        app = _app(config, store)
    async with app.run_test(size=(160, 45)) as pilot:
        with store_clock(FIXED_NOW):
            await wait_until(pilot, lambda: "kalibrasyon" in app.sidebar.text)
            rows = app.sidebar.text.splitlines()
            assert rows[0] == "▸ (untitled)" and rows[1] == "  today 12:00 · 0 msgs"
            assert rows[2] == "  alarm" and rows[3] == "  yesterday · 2 msgs"  # newest first
            assert rows[4] == "  kalibrasyon" and rows[5] == "  Sep 26 · 2 msgs"
            listing = app.sidebar.query_one("#sidebar-list", OptionList)
            listing.highlighted = 2
            listing.action_select()
            await wait_until(pilot, lambda: app.agent.session_id == ids[1])
            await wait_until(pilot, lambda: app.sidebar.text.startswith("▸ kalibrasyon"))
            assert "› kalibrasyon" in app.transcript.text
            listing.highlighted = 0
            listing.action_select()  # the current row: nothing happens
            await pilot.pause()
            assert app.agent.session_id == ids[1]


async def test_resume_rejects_an_invalid_session_name(tmp_path: Path) -> None:
    config = test_config(tmp_path)
    store, ids = await _seed(config, 1)
    app = _app(config, store)
    async with app.run_test(size=(80, 24)) as pilot:
        await send(pilot, "/resume ../secret")
        await pilot.pause()
        assert app.agent.session_id == SESSION_ID
        notices = [n.content.plain for n in app.transcript.query(NoticeRow)]
        assert notices and "../secret" in notices[-1]
        for fragment in PATH_FRAGMENTS:
            assert fragment not in app.transcript.text


async def test_lang_relabels_the_open_picker(tmp_path: Path) -> None:
    config = test_config(tmp_path)
    store, ids = await _seed(config, 1)
    app = _app(config, store)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press("ctrl+r")
        await wait_until(pilot, lambda: isinstance(app.screen, SessionPicker))
        app.language = "tr"
        await pilot.pause()
        assert app.screen.query_one("#title").content.plain == "◆ Oturumlar"
        assert app.screen.query_one("#picker-hint").content.plain == (
            "enter devam · n yeni · esc kapat"
        )
        await pilot.press("escape")
        await pilot.pause()
        assert app.hint.text.endswith("| ctrl+q çık")
