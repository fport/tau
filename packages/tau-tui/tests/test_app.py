"""Layout bands, the events pane, language, Esc precedence and privacy of the chrome."""

from __future__ import annotations

from pathlib import Path

import pytest
from helpers import PATH_FRAGMENTS, SESSION_ID, finish, fixed_clock, make_app, send, wait_until
from tau_core import AgentEvent
from tau_core.i18n import MESSAGES
from tau_tui.composer import PromptArea
from tau_tui.events import describe_event
from tau_tui.strings import TUI_MESSAGES
from tau_tui.transcript import NoticeRow


async def test_regions_at_80x24(tmp_path: Path) -> None:
    app = make_app(tmp_path, [])
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        assert app.screen.has_class("-narrow") and app.screen.has_class("-mid")
        assert app.header.region.height == 1
        assert app.transcript.region.height == 19 and app.transcript.region.y == 1
        assert app.composer.region.height == 3
        assert app.hint.region.height == 1 and app.hint.region.y == 23
        assert not app.events_pane.display
        assert not app.sidebar.display
        assert app.focused is app.query_one(PromptArea)
        assert app.header.text == f"τ tau  home · {SESSION_ID}  brain · en"
        assert app.hint.text == "? shortcuts · / commands · ctrl+j newline | ctrl+q quit"


async def test_phone_50x24(tmp_path: Path) -> None:
    app = make_app(tmp_path, [])
    async with app.run_test(size=(50, 24)) as pilot:
        await pilot.pause()
        assert app.screen.has_class("-phone")
        assert app.header.text == "τ tau · home  en"
        assert app.composer.region.height == 1
        assert app.transcript.region.height == 21
        assert app.hint.text == "? keys · / cmds · ^j newline | F4 events"
        await pilot.press("f4")
        await pilot.pause()
        assert app.screen.has_class("-events") and app.events_pane.display
        assert not app.transcript.display
        assert app.header.text == "τ tau · home  events"
        assert app.hint.text == "esc chat · ^j newline | F4 chat"
        assert app.focused is app.query_one(PromptArea)
        await pilot.press("escape")
        await pilot.pause()
        assert not app.screen.has_class("-events") and app.transcript.display


async def test_wide_and_ultra_and_tall(tmp_path: Path) -> None:
    app = make_app(tmp_path, [])
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        assert app.screen.has_class("-wide") and app.screen.has_class("-tall")
        assert app.events_pane.display and app.events_pane.region.width == 34
        assert app.transcript.region.height == 25
        assert app.header.text.endswith("brain · 0 tools · en")
        assert app.hint.text.endswith("| ctrl+e events · ctrl+q quit")
        await pilot.press("ctrl+e")
        await pilot.pause()
        assert app.screen.has_class("-events-hidden") and not app.events_pane.display
        await pilot.press("ctrl+e")
        await pilot.pause()
        assert app.events_pane.display

        await pilot.resize_terminal(160, 45)
        await pilot.pause()
        assert app.screen.has_class("-ultra")
        assert app.sidebar.display and app.sidebar.region.width == 28
        assert app.events_pane.region.width == 40
        assert app.transcript.region.height == 40
        assert app.header.text.endswith("brain → fake · 0 tools · en")

        await pilot.resize_terminal(80, 30)
        await pilot.pause()
        assert app.screen.has_class("-narrow") and app.screen.has_class("-tall")
        assert app.events_pane.display and app.events_pane.region.height == 8
        assert app.events_pane.region.width == 80
        assert app.transcript.region.bottom <= app.events_pane.region.y

        await pilot.resize_terminal(80, 18)
        await pilot.pause()
        assert app.screen.has_class("-short")
        assert not app.hint.display
        assert app.transcript.region.height == 14


async def test_events_pane_renders_every_kind(tmp_path: Path) -> None:
    app = make_app(tmp_path, [])
    async with app.run_test(size=(100, 30)) as pilot:
        bus = app.bus
        for kind, data in [
            ("turn_limit", {"max_turns": 12}),
            ("turn_limit", {"max_total_tokens": 4000}),
            ("error", {"message": "connection reset", "where": "model"}),
            ("notice", {"message": "hub restarted", "reason": "restart"}),
            ("notice", {"text": "old style"}),
            (
                "approval",
                {"tool": "set_light", "tier": 2, "decision": "approved", "channel": "tui"},
            ),
            (
                "tool_call",
                {
                    "tool": "set_light",
                    "tier": 2,
                    "status": "ok",
                    "approval": "approved",
                    "duration_ms": 412,
                    "result_summary": "Light turned off",
                    "tool_use_id": "q",
                },
            ),
            ("mesh_event", {"topic": "home/hall/temp", "value": 22}),
        ]:
            bus.emit(AgentEvent.create(kind, data, session_id=SESSION_ID, clock=fixed_clock))
        await wait_until(pilot, lambda: app.events_pane.log.count == 8)
        await pilot.pause()
        text = app.events_pane.text
        flat = text
        assert text.startswith("12:00:00 ◆ turn limit: 12 turns")
        assert "◆ token limit: 4000 tokens" in flat
        assert "✗ error [model]: connection reset" in flat
        assert "▸ notice · hub restarted" in flat and "▸ notice · old style" in flat
        assert "◆ approval set_light · tier 2 → approved (tui)" in flat
        assert "● set_light · tier 2 · ok · approved" in flat and "412ms" not in flat
        assert "— Light turned off" in flat
        assert '• mesh_event: {"topic": "home/hall/temp", "value": 22}' in flat
        assert "Events · 8" in app.query_one("#events-title").content.plain
        described = describe_event(
            AgentEvent.create(
                "tool_call", {"tool": "x", "status": "ok", "duration_ms": 5}, clock=fixed_clock
            ),
            "en",
            show_durations=True,
        )
        assert "5ms" in described.plain


async def test_lang_relabels_the_chrome(tmp_path: Path) -> None:
    app = make_app(tmp_path, [], tools=[])
    async with app.run_test(size=(80, 24), notifications=True) as pilot:
        await send(pilot, "/lang tr")
        await pilot.pause()
        assert app.language == "tr"
        assert app.query_one(PromptArea).placeholder == "Bir mesaj yaz…"
        assert app.hint.text == "? kısayollar · / komutlar · ctrl+j yeni satır | ctrl+q çık"
        assert app.query_one("#events-title").content.plain == "Olaylar · 0"
        assert "τ = 2π, tam bir tur." in app.transcript.text
        assert app.header.text.endswith("brain · tr")
        await send(pilot, "/xyz")
        await pilot.pause()
        assert "Bilinmeyen komut: /xyz. Komutlar: /help, /tools" in app.transcript.text
        await send(pilot, "/lang xx")
        await pilot.pause()
        assert "Bilinmeyen dil: xx." in app.transcript.text
        await send(pilot, "/lang")  # typed in full: Enter runs it although it takes an argument
        await pilot.pause()
        assert "Kullanım: /lang en|tr (şu an: tr)." in app.transcript.text
        await send(pilot, "/dil en")
        await pilot.pause()
        assert app.language == "en"


def test_tui_messages_have_both_languages_and_no_collisions() -> None:
    for key, templates in TUI_MESSAGES.items():
        assert key.startswith("tui."), key
        assert set(templates) == {"en", "tr"}, key
        assert templates["en"] and templates["tr"]
    assert set(TUI_MESSAGES) <= set(MESSAGES)


async def test_header_and_screenshot_never_contain_a_path(tmp_path: Path) -> None:
    app = make_app(tmp_path, ["ok"])
    async with app.run_test(size=(80, 24)) as pilot:
        await send(pilot, "/session")
        await pilot.pause()
        assert str(tmp_path) not in app.header.text
        svg = app.export_screenshot()
        assert SESSION_ID in svg
        for fragment in PATH_FRAGMENTS:
            assert fragment not in svg
            assert fragment not in app.transcript.text


async def test_help_and_tools_commands_and_aliases(tmp_path: Path) -> None:
    from helpers import arm_tool

    app = make_app(tmp_path, [], tools=[arm_tool([])])
    async with app.run_test(size=(80, 24)) as pilot:
        await send(pilot, "/araçlar")
        await pilot.pause()
        text = app.transcript.text
        assert "Tools (1):" in text
        assert "move_arm  tier 2 · physical, needs approval — Moves the test arm." in text
        await pilot.press("f3")
        await pilot.pause()
        assert app.transcript.text.count("Tools (1):") == 2
        await send(pilot, "/help")
        await pilot.pause()
        assert "Commands:" in app.transcript.text and "/quit" in app.transcript.text
        await send(pilot, "/unknown")
        await pilot.pause()
        assert (
            "Unknown command: /unknown. Commands: /help, /tools, /sessions, /resume, /new, "
            "/session, /compact, /clear, /status, /model, /lang, /settings, /quit"
        ) in app.query(NoticeRow).last().content.plain
        await send(pilot, "/çık")
        await pilot.pause()
    assert not app.is_running


@pytest.mark.parametrize("case", ["menu", "events", "scroll", "nothing"])
async def test_escape_precedence(tmp_path: Path, case: str) -> None:
    app = make_app(tmp_path, ["line\n\n" * 30])
    size = (50, 24) if case == "events" else (80, 24)
    async with app.run_test(size=size) as pilot:
        await pilot.pause()
        if case == "menu":
            await pilot.press("slash")
            await pilot.pause()
            assert app.menu.open
            await pilot.press("escape")
            assert not app.menu.open and app.composer.text == "/"
        elif case == "events":
            await pilot.press("f4")
            await pilot.pause()
            assert app.screen.has_class("-events")
            await pilot.press("escape")
            assert not app.screen.has_class("-events")
        elif case == "scroll":
            await send(pilot, "long")
            await finish(pilot)
            transcript = app.transcript
            assert transcript.is_vertical_scroll_end
            await pilot.press("pageup")
            await pilot.pause()
            assert not transcript.is_vertical_scroll_end
            await pilot.press("escape")
            await pilot.pause()
            assert transcript.is_vertical_scroll_end
            await pilot.press("pageup")
            await pilot.pause()
            await pilot.press("f9")
            await pilot.pause()
            assert transcript.is_vertical_scroll_end
        else:
            app.query_one(PromptArea).load_text("typed")
            await pilot.press("escape")
            assert app.composer.text == "typed"  # Esc never clears typed text


async def test_lang_while_busy_relabels_the_busy_row_and_hints(tmp_path: Path) -> None:
    import threading

    from tau_core import Tier, tau_tool
    from tau_core.testing import ToolCall
    from tau_tui.transcript import BusyRow

    release = threading.Event()

    @tau_tool(tier=Tier.READ)
    def blocked() -> str:
        """Waits for the test."""
        release.wait(5)
        return "released"

    app = make_app(tmp_path, [[ToolCall("blocked", {})], "Bitti."], tools=[blocked])
    async with app.run_test(size=(80, 24)) as pilot:
        await send(pilot, "block")
        await wait_until(pilot, lambda: "✻ Running blocked…" in app.transcript.text)
        await send(pilot, "/lang tr")  # read-only commands run while busy
        await pilot.pause()
        assert app.query_one(BusyRow).text == "✻ blocked çalışıyor…"
        assert app.hint.text == "esc iptal · ctrl+j yeni satır | meşgul · ctrl+q çık"
        assert app.query_one(PromptArea).placeholder == "Bir mesaj yaz…"
        release.set()
        await finish(pilot)
        assert "✓ 0s çalıştı · 1 araç çağrısı · ctrl+o aç" in app.transcript.text


async def test_ctrl_c_never_quits(tmp_path: Path) -> None:
    """With a selection ctrl+c copies; otherwise it only says how to quit (Textual's rule)."""
    app = make_app(tmp_path, [])
    async with app.run_test(size=(80, 24), notifications=True) as pilot:
        prompt = app.query_one(PromptArea)
        prompt.load_text("kept")
        prompt.select_all()
        await pilot.press("ctrl+c")
        await pilot.pause()
        assert app.is_running and app.composer.text == "kept"
        assert not list(app._notifications)  # the text area's copy, no toast
        prompt.move_cursor(prompt.document.end)  # no selection
        await pilot.press("ctrl+c")
        await pilot.pause()
        assert app.is_running and app.composer.text == "kept"
        assert any("ctrl+q" in str(n.message).lower() for n in app._notifications)


async def test_ascii_mode_swaps_the_vocabulary(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("TAU_TUI_ASCII", "1")
    app = make_app(tmp_path, ["fine"])
    async with app.run_test(size=(80, 24)) as pilot:
        assert app.header.text.startswith("t tau  home")
        await send(pilot, "hi")
        await finish(pilot)
        assert "> hi" in app.transcript.text
        assert app.query_one("#glyph").content.plain == "t"
        svg = app.export_screenshot()
        assert "τ" not in svg and "›" not in svg and "❯" not in svg


BOX_DRAWING = "╭╮╰╯│─┃┏┓┗┛━┃"


def _no_boxes(app, where: str) -> None:
    svg = app.export_screenshot()
    found = sorted({ch for ch in BOX_DRAWING if ch in svg})
    assert not found, f"{where}: box-drawing characters {found} in ASCII mode"


async def test_ascii_mode_switches_every_box_border(tmp_path: Path, monkeypatch) -> None:
    """Spec §2: with ``TAU_TUI_ASCII=1`` the boxes use the ``ascii`` border style.

    160x45 shows every bordered widget at once: the welcome card, the composer, the events
    column, the sidebar, the menu, the approval dialog, the expanded detail boxes and a fence.
    """
    from helpers import PROMPT, light_tools, steady
    from tau_core.testing import ToolCall
    from tau_tui import ApprovalScreen
    from tau_tui.sessions import SessionPicker

    monkeypatch.setenv("TAU_TUI_ASCII", "1")
    reply = 'Komut:\n\n```python\nset_light(room="salon", on=False)\n```\n'
    replies = [[ToolCall("set_light", {"room": "salon", "on": False})], reply]
    app = make_app(tmp_path, replies, tools=light_tools(), approve_delay=0)
    async with app.run_test(size=(160, 45)) as pilot:
        await steady(pilot)
        assert app.screen.has_class("-ascii") and app.query_one("#welcome").display
        _no_boxes(app, "welcome")
        assert app.composer.styles.border_top[0] == "ascii"
        await pilot.press("slash")
        await pilot.pause()
        assert app.menu.open
        _no_boxes(app, "menu")
        await pilot.press("escape")
        await send(pilot, PROMPT)
        await wait_until(pilot, lambda: isinstance(app.screen, ApprovalScreen))
        await pilot.pause()
        assert app.screen.has_class("-ascii")
        _no_boxes(app, "approval dialog")
        await pilot.press("y")
        await finish(pilot)
        await pilot.press("ctrl+o")
        await pilot.pause()
        assert app.query(".detail-box") and app.query("MarkdownFence")
        _no_boxes(app, "expanded cards and fence")
        await pilot.press("ctrl+r")
        await wait_until(pilot, lambda: isinstance(app.screen, SessionPicker))
        await pilot.pause()
        assert app.screen.has_class("-ascii")
        _no_boxes(app, "session picker")


async def test_a_modal_never_changes_the_chrome_bands(tmp_path: Path) -> None:
    """While a modal is on top ``app.screen`` has no breakpoint classes: the bands still come
    from the default screen, so the phone hint reads ``approval`` and the composer cap stays."""
    from helpers import PROMPT, light_tools, steady
    from tau_core.testing import ToolCall
    from tau_tui import ApprovalScreen

    def app_for(tmp: Path):
        replies = [[ToolCall("set_light", {"room": "salon", "on": False})], "Tamam."]
        return make_app(tmp, replies, tools=light_tools(), approve_delay=0)

    app = app_for(tmp_path)
    async with app.run_test(size=(50, 24)) as pilot:
        await steady(pilot)
        await send(pilot, PROMPT)
        await wait_until(pilot, lambda: isinstance(app.screen, ApprovalScreen))
        await pilot.pause()
        assert app.chrome_screen is not app.screen and app.chrome_screen.has_class("-phone")
        # The hints were refreshed on ``ApprovalPending``, before the modal had any band class.
        assert app.hint.phone and not app.hint.wide
        assert app.hint.text == "waiting for your approval · y approve · n reject | approval"
        assert app.query_one(PromptArea).max_rows == 3
        left = app.hint.query_one("#hint-left")
        right = app.hint.query_one("#hint-right")
        assert left.region.right < right.region.x  # a clipped left hint never touches the label
        await pilot.press("n")
        await finish(pilot)
        assert app.hint.text == "? keys · / cmds · ^j newline | F4 events"

    app = app_for(tmp_path)
    async with app.run_test(size=(100, 30)) as pilot:
        await steady(pilot)
        await send(pilot, PROMPT)
        await wait_until(pilot, lambda: isinstance(app.screen, ApprovalScreen))
        await pilot.pause()
        assert app.hint.wide and app.hint.text.endswith("| approval · ctrl+q quit")
        assert app.query_one(PromptArea).max_rows == 5
        # ctrl+e is a priority binding: with a modal on top it still acts on the chrome screen.
        await pilot.press("ctrl+e")
        await pilot.pause()
        assert app.chrome_screen.has_class("-events-hidden")
        assert not app.screen.has_class("-events-hidden") and not app.events_pane.display
        await pilot.press("n")
        await finish(pilot)


async def test_short_band_hides_the_welcome_mark_and_the_hint(tmp_path: Path) -> None:
    app = make_app(tmp_path, [])
    async with app.run_test(size=(80, 18)) as pilot:
        await pilot.pause()
        assert app.screen.has_class("-short") and not app.hint.display
        assert not app.query_one("#welcome .mark-wide").display
        assert app.transcript.region.height == 18 - 1 - 3
        assert app.query_one("#welcome").region.height == 14  # the facts fit the whole band
        assert app.query_one(PromptArea).max_rows == 2
        await pilot.resize_terminal(80, 24)
        await pilot.pause()
        await pilot.pause()
        assert app.hint.display and app.query_one("#welcome .mark-wide").display
        assert app.query_one(PromptArea).max_rows == 5


async def test_resize_between_bands_refreshes_the_hints(tmp_path: Path) -> None:
    app = make_app(tmp_path, [])
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        assert app.hint.text.endswith("| ctrl+q quit")
        await pilot.resize_terminal(50, 24)
        await wait_until(pilot, lambda: app.hint.text == "? keys · / cmds · ^j newline | F4 events")
        assert app.query_one(PromptArea).max_rows == 3
        await pilot.resize_terminal(120, 30)
        await wait_until(pilot, lambda: app.hint.text.endswith("| ctrl+e events · ctrl+q quit"))
        assert app.query_one(PromptArea).max_rows == 5


async def test_pageup_pagedown_scroll_a_modal_dialog(tmp_path: Path) -> None:
    from helpers import arm_tool
    from tau_core.testing import ToolCall
    from tau_tui import ApprovalScreen

    long_argument = {"direction": "left", "path": [f"point {i}" for i in range(40)]}
    app = make_app(
        tmp_path,
        [[ToolCall("move_arm", long_argument)], "ok"],
        tools=[arm_tool([])],
        approve_delay=0,
    )
    async with app.run_test(size=(80, 24)) as pilot:
        await send(pilot, "move")
        await wait_until(pilot, lambda: isinstance(app.screen, ApprovalScreen))
        await pilot.pause()
        box = app.screen.query_one("#arguments")
        assert box.scroll_y == 0 and box.max_scroll_y > 0
        await pilot.press("pagedown")
        await pilot.pause()
        assert box.scroll_y > 0
        await pilot.press("pageup")
        await pilot.pause()
        assert box.scroll_y == 0
        await pilot.press("n")
        await finish(pilot)
