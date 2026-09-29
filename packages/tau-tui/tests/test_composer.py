"""Enter, ctrl+j, the busy guard, the command menu, ``?`` and the prompt history."""

from __future__ import annotations

import threading
from pathlib import Path

from helpers import finish, make_app, send, type_and_send, wait_until
from tau_core import Tier, tau_tool
from tau_core.testing import ToolCall
from tau_tui.composer import CommandMenu, PromptArea
from tau_tui.transcript import InfoCard, UserRow


async def test_enter_sends_and_ctrl_j_adds_a_newline(tmp_path: Path) -> None:
    app = make_app(tmp_path, ["one", "two"])
    async with app.run_test(size=(80, 24)) as pilot:
        await type_and_send(pilot, "hi tau")
        await finish(pilot)
        assert app.query(UserRow).first().text == "› hi tau"
        assert app.composer.text == ""
        for char in "first":
            await pilot.press(char)
        await pilot.press("ctrl+j")
        for char in "second":
            await pilot.press(char)
        assert app.composer.text == "first\nsecond"
        assert app.composer.region.height == 4  # two text rows inside the box
        await pilot.press("enter")
        await finish(pilot)
        assert "› first\nsecond" in app.transcript.text


async def test_message_while_busy_is_kept_with_a_toast(tmp_path: Path) -> None:
    release = threading.Event()

    @tau_tool(tier=Tier.READ)
    def slow_lookup() -> str:
        """A slow read tool."""
        release.wait(5)
        return "finished"

    app = make_app(tmp_path, [[ToolCall("slow_lookup", {})], "Done."], tools=[slow_lookup])
    async with app.run_test(size=(80, 24), notifications=True) as pilot:
        await send(pilot, "run the slow one")
        await wait_until(pilot, lambda: "slow_lookup" in app.transcript.text)
        assert app.busy
        assert app.composer.has_class("-busy")
        assert app.hint.text == "esc cancel · ctrl+j newline | busy · ctrl+q quit"
        await send(pilot, "second")
        assert app.composer.text == "second"  # not sent, not lost
        assert len(app.query(UserRow)) == 1
        assert any("still answering" in str(n.message) for n in app._notifications)
        release.set()
        await finish(pilot)
        assert "Done." in app.transcript.text


async def test_slash_opens_the_menu_tab_completes_enter_runs(tmp_path: Path) -> None:
    app = make_app(tmp_path, [])
    async with app.run_test(size=(80, 24)) as pilot:
        menu = app.query_one(CommandMenu)
        await pilot.press("slash")
        await pilot.pause()
        assert menu.open and menu.option_count == 13
        assert app.hint.text.startswith("↑↓ pick · tab complete · enter run · esc close")
        for char in "re":
            await pilot.press(char)
        await pilot.pause()
        assert menu.highlighted_command is not None and menu.highlighted_command.name == "resume"
        await pilot.press("tab")
        assert app.composer.text == "/resume "
        await pilot.press("escape")
        assert not menu.open
        app.query_one(PromptArea).load_text("")
        await pilot.press("slash")
        for char in "new":
            await pilot.press(char)
        await pilot.pause()
        assert menu.highlighted_command.name == "new"
        await pilot.press("enter")
        await wait_until(pilot, lambda: "New session:" in app.transcript.text)
        assert app.composer.text == "" and not menu.open
        assert app.agent.session_id != "20260929-120000-abcd"


async def test_question_mark_in_an_empty_composer_shows_help(tmp_path: Path) -> None:
    app = make_app(tmp_path, ["ok"])
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press("question_mark")
        await pilot.pause()
        card = app.query_one(InfoCard)
        text = card.content.plain
        assert text.startswith("Commands:")
        assert "/resume [n|id]" in text and "Keys:" in text and "ctrl+o / F6" in text
        assert app.composer.text == ""
        await type_and_send(pilot, "?x")
        await finish(pilot)
        assert app.query(UserRow).first().text == "› ?x"


async def test_up_recalls_the_previous_prompt(tmp_path: Path) -> None:
    app = make_app(tmp_path, ["a", "b"])
    async with app.run_test(size=(80, 24)) as pilot:
        await send(pilot, "first prompt")
        await finish(pilot)
        await send(pilot, "second prompt")
        await finish(pilot)
        await pilot.press("up")
        assert app.composer.text == "second prompt"
        await pilot.press("up")
        assert app.composer.text == "first prompt"
        await pilot.press("down")
        await pilot.press("down")
        assert app.composer.text == ""


async def test_composer_grows_to_five_rows_and_no_further(tmp_path: Path) -> None:
    app = make_app(tmp_path, [])
    async with app.run_test(size=(80, 24)) as pilot:
        assert app.composer.region.height == 3
        for _ in range(7):
            await pilot.press("x")
            await pilot.press("ctrl+j")
        await pilot.pause()
        assert app.composer.region.height == 7
        assert app.transcript.region.height == 24 - 1 - 7 - 1


async def test_menu_only_for_a_lone_slash_word(tmp_path: Path) -> None:
    app = make_app(tmp_path, [])
    async with app.run_test(size=(80, 24)) as pilot:
        menu = app.query_one(CommandMenu)
        prompt = app.query_one(PromptArea)
        for char in "hi":
            await pilot.press(char)
        await pilot.press("slash")
        await pilot.pause()
        assert not menu.open  # ``/`` after text is just a character
        prompt.load_text("")
        await pilot.press("slash")
        for char in "resume":
            await pilot.press(char)
        await pilot.pause()
        assert menu.open and menu.option_count == 1
        await pilot.press("space")
        await pilot.press("2")
        await pilot.pause()
        assert not menu.open and app.composer.text == "/resume 2"  # an argument closes it
        prompt.load_text("/zzz")
        await pilot.pause()
        assert not menu.open  # no match closes it
        prompt.load_text("/")
        await pilot.pause()
        assert menu.open
        await pilot.press("ctrl+j")
        await pilot.pause()
        assert not menu.open  # a second line closes it
        assert app.hint.text.startswith("? shortcuts")


async def test_enter_on_a_partial_command_completes_without_running(tmp_path: Path) -> None:
    app = make_app(tmp_path, [])
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press("slash")
        for char in "la":
            await pilot.press(char)
        await pilot.pause()
        assert app.query_one(CommandMenu).highlighted_command.name == "lang"
        await pilot.press("enter")
        await pilot.pause()
        assert app.composer.text == "/lang " and app.language == "en"
        assert not app.query(InfoCard) and not app.transcript.query("NoticeRow")
        await pilot.press("t")
        await pilot.press("r")
        await pilot.press("enter")
        await wait_until(pilot, lambda: app.language == "tr")


async def test_arrows_edit_a_multi_line_composer_instead_of_recalling(tmp_path: Path) -> None:
    app = make_app(tmp_path, ["a"])
    async with app.run_test(size=(80, 24)) as pilot:
        await send(pilot, "sent before")
        await finish(pilot)
        for char in "one":
            await pilot.press(char)
        await pilot.press("ctrl+j")
        for char in "two":
            await pilot.press(char)
        await pilot.press("up")
        assert app.composer.text == "one\ntwo"
        prompt = app.query_one(PromptArea)
        assert prompt.cursor_location == (0, 3)
        await pilot.press("down")
        await pilot.press("down")
        assert app.composer.text == "one\ntwo"  # down on the last line: no recall either


async def test_phone_composer_caps_at_three_rows_and_short_at_two(tmp_path: Path) -> None:
    app = make_app(tmp_path, [])
    async with app.run_test(size=(50, 24)) as pilot:
        assert app.composer.region.height == 1
        for _ in range(5):
            await pilot.press("x")
            await pilot.press("ctrl+j")
        await pilot.pause()
        assert app.composer.region.height == 3  # borderless: three text rows
        assert app.query_one(PromptArea).max_rows == 3
        await pilot.resize_terminal(80, 18)
        await pilot.pause()
        await pilot.pause()
        assert app.query_one(PromptArea).max_rows == 2
        assert app.composer.region.height == 4  # two rows inside the border


async def test_a_fully_typed_command_runs_as_typed_even_with_a_stale_menu(tmp_path: Path) -> None:
    """A key burst (paste, mosh) can reach Enter before the menu caught up: never the wrong row."""
    app = make_app(tmp_path, [])
    async with app.run_test(size=(80, 24)) as pilot:
        menu = app.query_one(CommandMenu)
        prompt = app.query_one(PromptArea)
        prompt.load_text("/session")
        await pilot.pause()
        assert menu.highlighted_command.name == "session"  # the exact name ranks first
        assert [cmd.name for cmd in menu.commands] == ["session", "sessions"]
        menu.set_query("/sess")  # the stale state of a menu that has not seen the last keys
        assert menu.highlighted_command.name == "sessions"
        await pilot.press("enter")
        await pilot.pause()
        info = app.query(InfoCard).last().content.plain
        assert info.startswith("Session: ") and "Recent sessions" not in app.transcript.text
        prompt.load_text("/devam")  # an alias typed in full runs too
        await pilot.pause()
        assert not menu.open  # aliases are never listed
        await pilot.press("enter")
        await pilot.pause()
        assert "▸ No earlier session to resume." in app.transcript.text
