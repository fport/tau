"""TauApp driven through Textual's pilot, plus one SVG snapshot of the empty app.

Everything runs offline: ``FakeModel`` scripts the replies, tools are defined here, and the
approval dialog is answered with key presses the way a user would.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from tau_core import AgentEvent, Decision, MemorySessionStore, Tier, build_agent, tau_tool
from tau_core.testing import FakeModel, ToolCall, test_config
from tau_tui import ApprovalScreen, ChatPane, EventPane, TauApp, TuiApprover, build_app
from tau_tui.app import NO_SESSION_TEXT, SessionNotFound, resolve_resume
from textual.pilot import Pilot
from textual.widgets import Input, Static

SESSION_ID = "20260929-120000-abcd"
FIXED_NOW = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
SNAPSHOT = Path(__file__).parent / "__snapshots__" / Path(__file__).stem
# Split so a repository-wide search for personal paths does not flag this file.
PATH_FRAGMENTS = ("/" + "Users/", "/" + "home/", "/" + "tmp/")


def fixed_clock() -> datetime:
    return FIXED_NOW


def make_app(tmp_path: Path, replies: list[Any], tools: list[Any] | None = None, **kw) -> TauApp:
    return build_app(
        test_config(tmp_path),
        model=FakeModel(replies),
        tools=tools or [],
        session_id=SESSION_ID,
        clock=fixed_clock,
        **kw,
    )


async def wait_until(pilot: Pilot, condition: Callable[[], bool], timeout: float = 5.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not condition():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition not met in time")
        await pilot.pause(0.02)


async def type_and_send(pilot: Pilot, text: str) -> None:
    """Type ``text`` key by key and press Enter."""
    for char in text:
        await pilot.press("space" if char == " " else char)
    await pilot.press("enter")


async def send(pilot: Pilot, text: str) -> None:
    """Fill the input and press Enter (faster than typing every key)."""
    pilot.app.query_one(Input).value = text
    await pilot.press("enter")


def arm_tool(calls: list[dict[str, Any]]):
    @tau_tool(tier=Tier.PHYSICAL, effect="Test kolu sola hareket eder.")
    def move_arm(direction: str) -> str:
        """Test kolunu hareket ettirir."""
        calls.append({"direction": direction})
        return f"kol {direction} tarafa gitti"

    return move_arm


# -- the three tests the brief asks for ---------------------------------------------------------


async def test_reply_streams_into_chat_pane(tmp_path: Path) -> None:
    app = make_app(tmp_path, ["Merhaba efendim, buradayım."])
    async with app.run_test(size=(80, 24)) as pilot:
        await type_and_send(pilot, "merhaba tau")
        await wait_until(pilot, lambda: not app.busy and "buradayım" in app.chat.text)
        text = app.chat.text
        assert "sen: merhaba tau" in text
        assert "tau: Merhaba efendim, buradayım." in text
        assert text.count("tau:") == 1  # both streamed deltas landed in one block
        assert app.prompt_input.value == ""
        assert app.event_pane.text.strip() == ""  # no tool, no event


async def test_tier2_tool_asks_in_modal_and_h_rejects(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []
    model_replies = [[ToolCall("move_arm", {"direction": "sol"})], "Peki, kolu oynatmadım."]
    app = make_app(tmp_path, model_replies, tools=[arm_tool(calls)])
    async with app.run_test(size=(80, 24)) as pilot:
        await send(pilot, "kolu sola oynat")
        await wait_until(pilot, lambda: isinstance(app.screen, ApprovalScreen))
        screen = app.screen
        assert isinstance(screen, ApprovalScreen)
        shown = " ".join(str(w.content) for w in screen.query(Static))
        assert "Onay gerekiyor (tier 2)" in shown
        assert "move_arm" in shown
        assert '"direction": "sol"' in shown
        assert "Test kolu sola hareket eder." in shown
        assert app.approver is not None and app.approver.pending is not None

        await pilot.press("h")
        await wait_until(pilot, lambda: "rejected" in app.event_pane.text and not app.busy)
        assert not isinstance(app.screen, ApprovalScreen)
        assert calls == []  # the tool never ran
        events = app.event_pane.text
        assert "move_arm · tier 2 · rejected" in events
        assert "onay: move_arm · tier 2 → rejected (tui)" in events
        chat = app.chat.text
        assert "✗ move_arm: onaylanmadı" in chat
        assert "tau: Peki, kolu oynatmadım." in chat


def test_empty_app_snapshot(tmp_path: Path, snap_compare) -> None:
    app = make_app(tmp_path, [])
    screenshots: list[str] = []

    async def steady(pilot: Pilot) -> None:
        pilot.app.query_one(Input).cursor_blink = False
        await pilot.pause()
        screenshots.append(pilot.app.export_screenshot())

    assert snap_compare(app, terminal_size=(80, 24), run_before=steady)
    # The committed snapshot (written at session end with --snapshot-update). Its suffix depends
    # on the syrupy version pytest-textual-snapshot runs with (.raw with syrupy 6), so glob.
    committed = sorted(SNAPSHOT.glob("test_empty_app_snapshot.*"))
    svgs = screenshots + [path.read_text(encoding="utf-8") for path in committed]
    for svg in svgs:
        assert SESSION_ID in svg
        for fragment in PATH_FRAGMENTS:
            assert fragment not in svg


# -- approvals ----------------------------------------------------------------------------------


async def test_approve_key_is_ignored_until_armed(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []
    replies = [[ToolCall("move_arm", {"direction": "sol"})], "Kolu sola oynattım."]
    app = make_app(tmp_path, replies, tools=[arm_tool(calls)], approve_delay=0.3)
    async with app.run_test(size=(80, 24)) as pilot:
        await send(pilot, "kolu oynat")
        await wait_until(pilot, lambda: isinstance(app.screen, ApprovalScreen))
        await pilot.press("e")  # typed too early: must not approve
        await pilot.pause()
        assert isinstance(app.screen, ApprovalScreen)
        assert calls == []

        await wait_until(pilot, lambda: app.screen.armed)  # type: ignore[attr-defined]
        await pilot.press("e")
        await wait_until(pilot, lambda: "ok (onay: approved)" in app.event_pane.text)
        await wait_until(pilot, lambda: not app.busy)
        assert calls == [{"direction": "sol"}]
        assert "✓ move_arm: kol sol tarafa gitti" in app.chat.text
        assert "→ approved (tui)" in app.event_pane.text


async def test_escape_rejects(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []
    replies = [[ToolCall("move_arm", {"direction": "sağ"})], "Tamam."]
    app = make_app(tmp_path, replies, tools=[arm_tool(calls)])
    async with app.run_test(size=(80, 24)) as pilot:
        await send(pilot, "kolu oynat")
        await wait_until(pilot, lambda: isinstance(app.screen, ApprovalScreen))
        await pilot.press("escape")
        await wait_until(pilot, lambda: "rejected" in app.event_pane.text and not app.busy)
        assert calls == []


async def test_enter_on_default_button_rejects(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []
    replies = [[ToolCall("move_arm", {"direction": "sol"})], "Tamam."]
    app = make_app(tmp_path, replies, tools=[arm_tool(calls)], approve_delay=0)
    async with app.run_test(size=(80, 24)) as pilot:
        await send(pilot, "kolu oynat")
        await wait_until(pilot, lambda: isinstance(app.screen, ApprovalScreen))
        await pilot.press("enter")  # focus starts on "Reddet"
        await wait_until(pilot, lambda: "rejected" in app.event_pane.text and not app.busy)
        assert calls == []


async def test_tui_approver_without_running_app_rejects() -> None:
    from tau_core import ApprovalRequest

    request = ApprovalRequest(
        request_id="r1",
        tool="move_arm",
        tier=Tier.PHYSICAL,
        arguments={},
        effect="",
        session_id=None,
        channel="tui",
    )
    approver = TuiApprover()
    assert approver.name == "tui"
    assert await approver.decide(request) is Decision.REJECTED


async def test_message_while_busy_is_kept_in_the_input(tmp_path: Path) -> None:
    release = threading.Event()

    @tau_tool(tier=Tier.READ)
    def slow_lookup() -> str:
        """Yavaş bir okuma aracı."""
        release.wait(5)
        return "bitti"

    app = make_app(tmp_path, [[ToolCall("slow_lookup", {})], "Tamam."], tools=[slow_lookup])
    async with app.run_test(size=(80, 24), notifications=True) as pilot:
        await send(pilot, "yavaş olanı çalıştır")
        await wait_until(pilot, lambda: "slow_lookup (tier 0)" in app.chat.text)
        assert app.busy
        await send(pilot, "ikinci")
        assert app.prompt_input.value == "ikinci"  # not sent, not lost
        assert app.chat.text.count("sen:") == 1
        release.set()
        await wait_until(pilot, lambda: not app.busy)
        assert "tau: Tamam." in app.chat.text


# -- panes, layout, commands --------------------------------------------------------------------


async def test_event_pane_renders_every_kind(tmp_path: Path) -> None:
    app = make_app(tmp_path, [])
    async with app.run_test(size=(80, 24)) as pilot:
        bus = app.agent.events
        for kind, data in [
            ("turn_limit", {"max_turns": 12}),
            ("error", {"message": "bağlantı koptu", "where": "model"}),
            ("notice", {"text": "hub yeniden başladı"}),
            ("mesh_event", {"topic": "ev/salon/sicaklik", "value": 22}),
        ]:
            bus.emit(AgentEvent.create(kind, data, session_id=SESSION_ID))
        await wait_until(pilot, lambda: app.event_pane.entry_count == 4)
        text = app.event_pane.text
        assert "tur sınırı: 12 tur" in text
        assert "hata [model]: bağlantı koptu" in text
        assert "ℹ hub yeniden başladı" in text
        assert "mesh_event:" in text and '"topic": "ev/salon/sicaklik"' in text


async def test_model_error_becomes_notice_and_error_event(tmp_path: Path) -> None:
    def boom(messages, system_prompt):
        raise RuntimeError("sağlayıcı yanıt vermedi")

    app = make_app(tmp_path, [boom])
    async with app.run_test(size=(80, 24)) as pilot:
        await send(pilot, "merhaba")
        await wait_until(pilot, lambda: not app.busy and "hata" in app.event_pane.text)
        assert "Model çağrısı başarısız oldu" in app.chat.text
        assert "hata [model]" in app.event_pane.text


async def test_layout_stacks_under_100_columns_and_splits_above(tmp_path: Path) -> None:
    app = make_app(tmp_path, [])
    async with app.run_test(size=(80, 24)) as pilot:
        header = app.query_one("#header", Static)
        chat, events, prompt = app.chat, app.event_pane, app.prompt_input
        assert header.region.height == 1 and prompt.region.height == 1
        assert chat.region.width == events.region.width == 80
        assert chat.region.bottom <= events.region.y  # chat above events
        assert chat.region.height >= 12  # most rows go to the conversation
        assert events.region.height >= 5
        assert header.region.height + chat.region.height + events.region.height + 1 == 24

        await pilot.resize_terminal(120, 30)
        await pilot.pause()
        assert app.screen.has_class("-wide")
        assert chat.region.y == events.region.y  # side by side
        assert chat.region.right <= events.region.x


async def test_header_shows_profile_and_session_id_only(tmp_path: Path) -> None:
    app = make_app(tmp_path, [])
    async with app.run_test(size=(80, 24)):
        header = str(app.query_one("#header", Static).content)
        assert header.split() == ["tau", "profil:", "ev", "oturum:", SESSION_ID]
        assert str(tmp_path) not in header


async def test_streamed_reply_repaints_in_place(tmp_path: Path) -> None:
    app = make_app(tmp_path, [])
    async with app.run_test(size=(80, 24)) as pilot:
        chat = app.chat
        chat.add_user("uzun bir soru " * 4)  # wider than the reply: the line width stays put
        chat.append_reply("Merhaba")
        await pilot.pause()
        assert chat.render_line(1).text.rstrip() == "tau: Merhaba"  # painted (and cached)
        chat.append_reply(" efendim, buyurun.")
        await pilot.pause()
        assert chat.render_line(1).text.rstrip() == "tau: Merhaba efendim, buyurun."
        chat.end_reply()
        chat.append_reply("Yeni blok.")
        await pilot.pause()
        assert chat.text.count("tau:") == 2


async def test_resize_rewraps_the_transcript(tmp_path: Path) -> None:
    long = "uzun " * 40
    app = make_app(tmp_path, [long.strip()])
    async with app.run_test(size=(60, 24)) as pilot:
        await send(pilot, "anlat")
        await wait_until(pilot, lambda: not app.busy and "uzun" in app.chat.text)
        narrow_lines = len(app.chat.lines)
        await pilot.resize_terminal(99, 24)
        await wait_until(pilot, lambda: len(app.chat.lines) < narrow_lines)
        assert all(len(line.text.rstrip()) <= 99 for line in app.chat.lines)


async def test_slash_commands(tmp_path: Path) -> None:
    app = make_app(tmp_path, [], tools=[arm_tool([])])
    async with app.run_test(size=(80, 24)) as pilot:
        await send(pilot, "/araçlar")
        await pilot.pause()
        assert "Araçlar (1):" in app.chat.text
        assert "move_arm  tier 2 · fiziksel, onay gerekir — Test kolunu hareket" in app.chat.text
        await send(pilot, "/bilinmeyen")
        await pilot.pause()
        assert "Bilinmeyen komut: /bilinmeyen. Komutlar: /araçlar, /çık" in app.chat.text
        await send(pilot, "/cik")
        await pilot.pause()
    assert not app.is_running


async def test_resumed_session_shows_history(tmp_path: Path) -> None:
    config = test_config(tmp_path)
    store = MemorySessionStore()
    first = build_agent(
        config=config,
        model=FakeModel(["İlk yanıtım."]),
        tools=[],
        session_store=store,
        session_id=SESSION_ID,
        channel="tui",
    )
    assert await first.ask("ilk mesajım") == "İlk yanıtım."
    first.close()

    session_id, notice = resolve_resume(store, "")
    assert session_id == SESSION_ID
    assert notice == f"Oturuma devam ediliyor: {SESSION_ID} (ilk mesajım)"

    app = build_app(
        config,
        model=FakeModel([]),
        tools=[],
        session_store=store,
        session_id=session_id,
        notice=notice,
    )
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        text = app.chat.text
        assert "sen: ilk mesajım" in text
        assert "tau: İlk yanıtım." in text
        assert f"Oturuma devam ediliyor: {SESSION_ID}" in text
    app.agent.close()


def test_resolve_resume_without_sessions() -> None:
    store = MemorySessionStore()
    assert resolve_resume(store, None) == (None, None)
    assert resolve_resume(store, "") == (None, NO_SESSION_TEXT)
    with pytest.raises(SessionNotFound, match="Oturum bulunamadı: yok-boyle-bir-oturum"):
        resolve_resume(store, "yok-boyle-bir-oturum")


def test_public_names() -> None:
    import tau_tui

    for cls in (TauApp, ChatPane, EventPane, ApprovalScreen, TuiApprover):
        assert cls.__name__ in tau_tui.__all__
