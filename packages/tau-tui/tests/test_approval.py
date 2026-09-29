"""Tier-2 approvals: explicit only, armed after a delay, reject on anything else."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from helpers import arm_tool, finish, make_app, send, wait_until
from tau_core import ApprovalRequest, Decision, Tier, t
from tau_core.testing import ToolCall
from tau_tui import ApprovalScreen, TuiApprover
from tau_tui.brand import TauGlyph


async def test_tier2_tool_opens_the_modal_and_n_rejects(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []
    replies = [[ToolCall("move_arm", {"direction": "left"})], "Fine, I did not move it."]
    app = make_app(tmp_path, replies, tools=[arm_tool(calls)])
    async with app.run_test(size=(80, 24)) as pilot:
        await send(pilot, "move the arm left")
        await wait_until(pilot, lambda: isinstance(app.screen, ApprovalScreen))
        screen = app.screen
        assert isinstance(screen, ApprovalScreen)
        shown = screen.text
        assert "◆ Approval needed (tier 2) · physical, needs approval" in shown
        assert "Tool: move_arm" in shown
        assert '"direction": "left"' in shown
        assert "Effect: The test arm moves to the left." in shown
        assert app.approver is not None and app.approver.pending is not None
        # the chrome behind the modal
        assert app.attention and app.composer.has_class("-attention")
        assert app.query_one("#glyph", TauGlyph).state == "attention"
        assert app.hint.text == (
            "waiting for your approval · y approve · n reject | approval · ctrl+q quit"
        )
        card = app.transcript.tool_cards["t1"]
        assert card.status == "pending"
        assert (
            card.text
            == '○ move_arm(direction="left") tier 2 · approval…\n⎿  ◆ waiting for your approval'
        )
        assert "✻ Waiting for your approval…" in app.transcript.text

        await pilot.press("n")
        await finish(pilot)
        assert not isinstance(app.screen, ApprovalScreen)
        assert calls == []  # the tool never ran
        assert not app.attention and not app.composer.has_class("-attention")
        assert card.status == "rejected"
        assert (
            card.text
            == '● move_arm(direction="left") tier 2 · rejected\n⎿  ✗ move_arm: not approved'
        )
        events = app.events_pane.text
        assert "move_arm · tier 2 · rejected" in events
        assert "◆ approval move_arm · tier 2 → rejected (tui)" in events
        assert "Fine, I did not move it." in app.transcript.text


async def test_approve_keys_are_ignored_until_armed(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []
    replies = [[ToolCall("move_arm", {"direction": "left"})], "Moved it left."]
    app = make_app(tmp_path, replies, tools=[arm_tool(calls)], approve_delay=0.3)
    async with app.run_test(size=(80, 24)) as pilot:
        await send(pilot, "move the arm")
        await wait_until(pilot, lambda: isinstance(app.screen, ApprovalScreen))
        assert "(arming…)" in app.screen.text
        await pilot.press("y")  # too early: must not approve
        await pilot.press("e")
        await pilot.pause()
        assert isinstance(app.screen, ApprovalScreen)
        assert calls == []

        await wait_until(pilot, lambda: app.screen.armed)  # type: ignore[attr-defined]
        assert "(arming…)" not in app.screen.text
        await pilot.press("y")
        await finish(pilot)
        assert calls == [{"direction": "left"}]
        card = app.transcript.tool_cards["t1"]
        assert card.status == "ok" and card.approval == "approved"
        assert card.text == '● move_arm(direction="left") tier 2 · approved\n⎿  arm moved left'
        assert "→ approved (tui)" in app.events_pane.text


async def test_e_approves_after_arming(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []
    app = make_app(
        tmp_path,
        [[ToolCall("move_arm", {"direction": "up"})], "Up."],
        tools=[arm_tool(calls)],
        approve_delay=0,
    )
    async with app.run_test(size=(80, 24)) as pilot:
        await send(pilot, "move")
        await wait_until(pilot, lambda: isinstance(app.screen, ApprovalScreen))
        await pilot.press("e")
        await finish(pilot)
        assert calls == [{"direction": "up"}]


@pytest.mark.parametrize("key", ["h", "escape", "enter"])
async def test_h_escape_and_enter_reject(tmp_path: Path, key: str) -> None:
    calls: list[dict[str, Any]] = []
    replies = [[ToolCall("move_arm", {"direction": "right"})], "Okay."]
    app = make_app(tmp_path, replies, tools=[arm_tool(calls)], approve_delay=0)
    async with app.run_test(size=(80, 24)) as pilot:
        await send(pilot, "move")
        await wait_until(pilot, lambda: isinstance(app.screen, ApprovalScreen))
        await pilot.press(key)  # Enter: focus starts on Reject
        await finish(pilot)
        assert calls == []
        assert app.transcript.tool_cards["t1"].status == "rejected"


async def test_tui_approver_without_running_app_rejects() -> None:
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


async def test_dialog_is_full_width_on_the_phone(tmp_path: Path) -> None:
    app = make_app(
        tmp_path,
        [[ToolCall("move_arm", {"direction": "l"})], "ok"],
        tools=[arm_tool([])],
        approve_delay=0,
    )
    async with app.run_test(size=(50, 24)) as pilot:
        await send(pilot, "move")
        await wait_until(pilot, lambda: isinstance(app.screen, ApprovalScreen))
        await pilot.pause()
        assert app.screen.query_one("#dialog").region.width == 50
        buttons = app.screen.query("Button")
        assert buttons[0].region.y != buttons[1].region.y  # stacked
        await pilot.press("n")
        await finish(pilot)


async def test_gate_timeout_cancels_the_wait_and_takes_the_dialog_down(tmp_path: Path) -> None:
    """A cancelled ``decide`` (here the gate's timeout) rejects and closes the dialog."""
    calls: list[dict[str, Any]] = []
    replies = [[ToolCall("move_arm", {"direction": "left"})], "Timed out, did nothing."]
    app = make_app(tmp_path, replies, tools=[arm_tool(calls)], approve_delay=0)
    assert app.approver is not None
    app.approver.timeout_seconds = 0.3  # type: ignore[attr-defined]  (read by the gate)
    async with app.run_test(size=(80, 24)) as pilot:
        await send(pilot, "move")
        await wait_until(pilot, lambda: isinstance(app.screen, ApprovalScreen))
        screen = app.screen
        await finish(pilot)
        assert not isinstance(app.screen, ApprovalScreen) and not screen.is_attached
        assert calls == [] and app.approver.pending is None
        assert not app.attention
        card = app.transcript.tool_cards["t1"]
        assert card.status == "rejected" and card.approval == "timeout"
        assert (
            card.text
            == '● move_arm(direction="left") tier 2 · timeout\n⎿  ✗ move_arm: not approved'
        )
        assert "→ timeout (tui)" in app.events_pane.text
        assert "Timed out, did nothing." in app.transcript.text


async def test_cancelled_decide_rejects_and_posts_done(tmp_path: Path) -> None:
    app = make_app(tmp_path, [])
    request = ApprovalRequest(
        request_id="r2",
        tool="move_arm",
        tier=Tier.PHYSICAL,
        arguments={"direction": "up"},
        effect="",
        session_id=None,
        channel="tui",
    )
    async with app.run_test(size=(80, 24)) as pilot:
        approver = app.approver
        assert approver is not None
        task = asyncio.ensure_future(approver.decide(request))
        await wait_until(pilot, lambda: isinstance(app.screen, ApprovalScreen))
        assert app.attention and approver.pending is request
        task.cancel()
        await wait_until(pilot, lambda: not isinstance(app.screen, ApprovalScreen))
        await pilot.pause()
        assert task.cancelled() and approver.pending is None
        assert not app.attention and not app.composer.has_class("-attention")


async def test_tab_reaches_approve_and_the_dialog_speaks_the_ui_language(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []
    replies = [[ToolCall("move_arm", {"direction": "up"})], "Up."]
    app = make_app(tmp_path, replies, tools=[arm_tool(calls)], approve_delay=0)
    async with app.run_test(size=(80, 24)) as pilot:
        await send(pilot, "/lang tr")
        await pilot.pause()
        await send(pilot, "move")
        await wait_until(pilot, lambda: isinstance(app.screen, ApprovalScreen))
        shown = app.screen.text
        assert f"◆ {t('approval.title', 'tr', tier=2)} · {t('tier.2', 'tr')}" in shown
        assert "Araç: move_arm" in shown and "Etki:" in shown
        assert app.hint.text == "onayın bekleniyor · y onayla · n reddet | onay · ctrl+q çık"
        assert "✻ Onayın bekleniyor…" in app.transcript.text
        assert app.screen.focused is app.screen.query_one("#reject")
        await pilot.press("tab")
        assert app.screen.focused is app.screen.query_one("#approve")
        await pilot.press("tab")
        assert app.screen.focused is app.screen.query_one("#reject")  # only the two buttons
        await pilot.press("shift+tab")
        await pilot.press("enter")
        await finish(pilot)
        assert calls == [{"direction": "up"}]
