"""Turns, reply blocks, tool cards, reasoning, notices and footers."""

from __future__ import annotations

import asyncio
import re
from datetime import timedelta
from pathlib import Path
from time import perf_counter

import pytest
from helpers import (
    FIXED_NOW,
    SESSION_ID,
    finish,
    fixed_clock,
    light_tools,
    make_app,
    send,
    wait_until,
)
from tau_core import AgentEvent, ToolFinished, ToolUseStarted
from tau_core.testing import ToolCall, Truncated
from tau_tui.tools import ReasoningCard, ToolCard
from tau_tui.transcript import BusyRow, NoticeRow, ReplyBlock, TurnFooter, UserRow, WelcomeCard
from textual.widgets._markdown import MarkdownBulletList, MarkdownFence, MarkdownParagraph


async def test_two_deltas_land_in_one_reply_block(tmp_path: Path) -> None:
    app = make_app(tmp_path, ["Hello there, I am here."])
    async with app.run_test(size=(80, 24)) as pilot:
        assert app.query(WelcomeCard)
        await send(pilot, "hello tau")
        await finish(pilot)
        blocks = list(app.query(ReplyBlock))
        assert len(blocks) == 1
        assert blocks[0].source == "Hello there, I am here."
        assert blocks[0].query(MarkdownParagraph)
        assert "› hello tau" in app.transcript.text
        assert not app.query(WelcomeCard)  # gone after the first message
        assert not app.query(BusyRow) and not app.query(TurnFooter)  # plain turn: no footer
        assert app.composer.text == ""


async def test_markdown_blocks_render(tmp_path: Path) -> None:
    app = make_app(tmp_path, ["- one\n- two", "Code:\n\n```python\nprint(1)\n```"])
    async with app.run_test(size=(80, 24)) as pilot:
        await send(pilot, "list")
        await finish(pilot)
        assert app.query(MarkdownBulletList)
        await send(pilot, "code")
        await finish(pilot)
        assert app.query(MarkdownFence)


async def test_tool_call_splits_segments_and_cards_fill_in(tmp_path: Path) -> None:
    app = make_app(
        tmp_path,
        [[ToolCall("get_light_state", {"room": "salon"})], "It is on."],
        tools=light_tools(),
    )
    async with app.run_test(size=(80, 24)) as pilot:
        await send(pilot, "is the light on?")
        await finish(pilot)
        card = app.transcript.tool_cards["t1"]
        assert card.status == "ok" and card.has_class("-ok")
        assert card.line_text == '● get_light_state(room="salon") tier 0'
        assert '⎿  {"on": true, "brightness": 80}' in card.text
        footer = app.query_one(TurnFooter)
        assert str(footer.content.plain).startswith("✓ Worked for 0s · 1 tool call · ctrl+o expand")
        assert list(app.query(ReplyBlock))[-1].source == "It is on."


async def test_segments_keep_their_order_around_a_tool_call(tmp_path: Path) -> None:
    app = make_app(tmp_path, [])
    async with app.run_test(size=(80, 24)) as pilot:
        turn = await app.transcript.begin_turn("order")
        await turn.feed_text("Before. ")
        await turn.add_tool(ToolUseStarted("t1", "probe", 0))
        await turn.finish_tool(ToolFinished("t1", "probe", "ok", "done", None))
        await turn.feed_text("After.")
        await turn.end("end_turn", elapsed=0)
        await pilot.pause()
        kinds = [type(child).__name__ for child in turn.children]
        assert kinds == ["UserRow", "ReplyBlock", "ToolCard", "ReplyBlock", "TurnFooter"]
        assert [block.source for block in turn.query(ReplyBlock)] == ["Before. ", "After."]
        assert turn.text.splitlines()[0] == "› order"


async def test_turn_events_drive_the_widgets_directly(tmp_path: Path) -> None:
    app = make_app(tmp_path, [])
    async with app.run_test(size=(80, 24)) as pilot:
        turn = await app.transcript.begin_turn("direct")
        await turn.feed_reasoning("let me think")
        await pilot.pause()
        assert app.query_one(ReasoningCard).text == "✻ Thinking…"
        await turn.feed_text("Hel")
        await turn.feed_text("lo")
        await turn.set_busy("tui.busy.throttled", seconds=4)
        assert (
            turn.busy_row is not None and turn.busy_row.text == "✻ Model is busy, retrying in 4 s…"
        )
        await turn.add_tool(ToolUseStarted("x1", "probe", 0))
        turn.tool_progress("x1", "probe", "half way\nmore")
        assert app.transcript.tool_cards["x1"].text.endswith("⎿  ○ half way")
        await turn.finish_tool(ToolFinished("orphan", "other", "error", "boom", None))
        await turn.finish_tool(ToolFinished("x1", "probe", "ok", "done", None))
        await turn.add_notice("careful")
        await turn.end("end_turn", elapsed=0)
        await pilot.pause()
        reasoning = app.query_one(ReasoningCard)
        assert reasoning.text == "✻ Thought for 0s"
        assert not reasoning.open
        blocks = list(app.query(ReplyBlock))
        assert [b.source for b in blocks] == ["Hello"]
        assert app.transcript.tool_cards["x1"].text == "● probe(…) tier 0\n⎿  done"
        orphan = app.transcript.tool_cards["orphan"]
        assert orphan.status == "error" and orphan.text == "● other(…) tier ?\n⎿  ✗ boom"
        assert app.query_one(NoticeRow).content.plain == "▸ careful"
        assert not app.query(BusyRow)
        assert "✓ Worked for 0s · 2 tool calls · ctrl+o expand" in app.transcript.text
        # ctrl+o expands every card of the last turn, again collapses them
        await pilot.press("ctrl+o")
        await pilot.pause()
        assert all(card.expanded for card in turn.cards)
        assert "ctrl+o collapse" in app.transcript.text
        assert reasoning.text == "✻ Thought for 0s\nlet me think"
        boxes = [b.content.plain for b in app.transcript.tool_cards["x1"].query(".detail-box")]
        assert boxes == ["{}", "done"]
        await pilot.press("ctrl+o")
        await pilot.pause()
        assert not any(card.expanded for card in turn.cards)


@pytest.mark.parametrize("event_first", [True, False])
async def test_tool_call_event_and_tool_finished_merge_in_either_order(
    tmp_path: Path, event_first: bool
) -> None:
    """The bus ``tool_call`` event and the turn's ``ToolFinished`` may land in any order."""
    app = make_app(tmp_path, [])
    async with app.run_test(size=(80, 24)) as pilot:
        turn = await app.transcript.begin_turn("merge")
        await turn.add_tool(ToolUseStarted("t1", "set_light", 2))
        card = app.transcript.tool_cards["t1"]
        event = AgentEvent.create(
            "tool_call",
            {
                "tool": "set_light",
                "tier": 2,
                "status": "rejected",
                "approval": "rejected",
                "arguments": {"on": False},
                "tool_use_id": "t1",
                "duration_ms": 3,
            },
            session_id=SESSION_ID,
            clock=fixed_clock,
        )
        finished = ToolFinished("t1", "set_light", "rejected", "", "rejected")
        if event_first:
            app.bus.emit(event)
            await wait_until(pilot, lambda: card.approval == "rejected")
            await turn.finish_tool(finished)
        else:
            await turn.finish_tool(finished)
            app.bus.emit(event)
            await wait_until(pilot, lambda: card.arguments == {"on": False})
        await pilot.pause()
        assert card.status == "rejected" and card.has_class("-rejected")
        assert card.text == "● set_light(on=false) tier 2 · rejected\n⎿  ✗ set_light: not approved"


async def test_a_late_running_event_never_reopens_a_finished_card(tmp_path: Path) -> None:
    app = make_app(tmp_path, [])
    async with app.run_test(size=(80, 24)) as pilot:
        turn = await app.transcript.begin_turn("late")
        await turn.add_tool(ToolUseStarted("t1", "probe", 0))
        await turn.finish_tool(ToolFinished("t1", "probe", "ok", "done", None))
        card = app.transcript.tool_cards["t1"]
        app.bus.emit(
            AgentEvent.create(
                "tool_call",
                {"tool": "probe", "tier": 0, "status": "running", "tool_use_id": "t1"},
                session_id=SESSION_ID,
                clock=fixed_clock,
            )
        )
        await wait_until(pilot, lambda: app.events_pane.log.count == 1)
        await pilot.pause()
        assert card.status == "ok" and card.text == "● probe(…) tier 0\n⎿  done"


async def test_unknown_tool_call_event_makes_a_card_above_the_busy_row(tmp_path: Path) -> None:
    app = make_app(tmp_path, [])
    async with app.run_test(size=(80, 24)) as pilot:
        turn = await app.transcript.begin_turn("event only")
        app.bus.emit(
            AgentEvent.create(
                "tool_call",
                {
                    "tool": "late",
                    "tier": 1,
                    "status": "ok",
                    "tool_use_id": "z9",
                    "result_summary": "late result",
                    "arguments": {"n": 1},
                },
                session_id=SESSION_ID,
                clock=fixed_clock,
            )
        )
        await wait_until(pilot, lambda: "z9" in app.transcript.tool_cards)
        await pilot.pause()
        card = app.transcript.tool_cards["z9"]
        assert card.text == "● late(n=1) tier 1\n⎿  late result"
        assert isinstance(turn.children[-1], BusyRow) and turn.children[-2] is card
        assert turn.tool_count == 1
        await turn.end("end_turn", elapsed=0)
        await pilot.pause()
        assert "✓ Worked for 0s · 1 tool call" in turn.text


async def test_live_and_plain_streaming_settle_identically(tmp_path: Path) -> None:
    reply = "Intro\n\n- a\n- b\n\n```py\nx = 1\n```\n\nEnd."
    sources = {}
    for mode in ("live", "plain"):
        app = make_app(tmp_path / mode, [reply], stream_mode=mode)
        async with app.run_test(size=(80, 24)) as pilot:
            await send(pilot, "go")
            await finish(pilot)
            block = app.query_one(ReplyBlock)
            assert block.draft is None and block.md.display
            sources[mode] = (
                block.source,
                [type(w).__name__ for w in block.md.query("MarkdownBlock")],
            )
    assert sources["live"] == sources["plain"]
    assert sources["live"][0] == reply


async def test_degrade_path_ends_plain_and_settles(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(ReplyBlock, "DEGRADE_MS", -1)
    monkeypatch.setattr(ReplyBlock, "DEGRADE_STRIKES", 1)
    app = make_app(tmp_path, ["A **bold** word."], stream_mode="live")
    async with app.run_test(size=(80, 24)) as pilot:
        await send(pilot, "go")
        await finish(pilot)
        block = app.query_one(ReplyBlock)
        assert block.mode == "plain" and block.draft is None
        assert block.source == "A **bold** word."
        assert block.md.query(MarkdownParagraph)


async def test_a_long_fenced_reply_streams_live_under_a_second(tmp_path: Path) -> None:
    """§20: 6 kB inside an open code fence, fed in 64-char deltas with the 80 ms coalescing."""
    body = "\n".join(f"value_{i:03d} = compute({i}, {'x' * 30})" for i in range(120))
    reply = f"Here is the script:\n\n```python\n{body}\n```\n\nDone."
    assert len(reply) > 6000
    app = make_app(tmp_path, [], stream_mode="live")
    async with app.run_test(size=(80, 24)) as pilot:
        turn = await app.transcript.begin_turn("perf")
        t0 = perf_counter()
        for i in range(0, len(reply), 64):
            await turn.feed_text(reply[i : i + 64])
            await asyncio.sleep(0.004)
        await turn.end("end_turn", elapsed=0)
        await pilot.pause()
        elapsed = perf_counter() - t0
        block = app.query_one(ReplyBlock)
        assert block.source == reply and block.closed
        assert block.query(MarkdownFence)
        assert elapsed < 1.0, f"streaming took {elapsed:.2f} s"


async def test_a_one_line_fence_costs_one_row_plus_margins(tmp_path: Path) -> None:
    """Textual pads the fence label ``1 2`` by default; mockup 4.6 shows ``┃ code`` alone."""
    from textual.widgets import Label

    reply = 'Komut:\n\n```python\nset_light(room="salon", on=False)\n```\n\nBitti.'
    app = make_app(tmp_path, [reply])
    async with app.run_test(size=(80, 24)) as pilot:
        await send(pilot, "hi")
        await finish(pilot)
        fence = app.query_one(MarkdownFence)
        assert fence.region.height == 1
        assert fence.query_one(Label).region.height == 1
        assert fence.styles.margin.top == 1 and fence.styles.margin.bottom == 1
        assert 'set_light(room="salon", on=False)' in app.transcript.text


async def test_max_tokens_keeps_the_partial_reply_and_marks_the_footer(tmp_path: Path) -> None:
    app = make_app(tmp_path, [Truncated("This reply was cut sho")])
    async with app.run_test(size=(80, 24)) as pilot:
        await send(pilot, "long story")
        await finish(pilot)
        text = app.transcript.text
        assert "This reply was cut sho" in text
        assert "▸ The reply hit the length limit; say so if you want me to continue." in text
        assert "◆ Length limit · worked for 0s" in text
        assert "▸ notice · The reply hit the length limit" in app.events_pane.text


async def test_footer_for_other_stop_reasons(tmp_path: Path) -> None:
    app = make_app(tmp_path, [])
    async with app.run_test(size=(80, 24)) as pilot:
        for reason, expected in [
            ("busy", "◆ Busy · worked for 0s"),
            ("limit_turns", "◆ Turn limit · worked for 1m 5s"),
            ("interrupt", "◆ Interrupted · worked for 0s"),
            ("mystery", "◆ mystery · worked for 0s"),
        ]:
            turn = await app.transcript.begin_turn(reason)
            await turn.end(reason, elapsed=65 if reason == "limit_turns" else 0)
            await pilot.pause()
            assert turn.footer is not None and turn.footer.content.plain == expected
        turn = await app.transcript.begin_turn("plain")
        await turn.feed_text("ok")
        await turn.end("end_turn", elapsed=4)
        await pilot.pause()
        assert turn.footer is None  # no tools, under 5 s, end_turn: no footer


async def test_a_slow_turn_gets_a_footer_from_the_app_clock(tmp_path: Path) -> None:
    ticks = iter(range(10_000))

    def ticking() -> object:
        return FIXED_NOW + timedelta(seconds=3 * next(ticks))

    app = make_app(tmp_path, ["Took a while."], clock=ticking)
    async with app.run_test(size=(80, 24)) as pilot:
        await send(pilot, "slow?")
        await finish(pilot)
        footer = app.query_one(TurnFooter).content.plain
        assert re.fullmatch(r"✓ Worked for \d+s", footer) and footer != "✓ Worked for 0s"


async def test_notice_and_error_footer(tmp_path: Path) -> None:
    def boom(messages, system_prompt):
        raise RuntimeError("provider did not answer")

    app = make_app(tmp_path, [boom])
    async with app.run_test(size=(80, 24)) as pilot:
        await send(pilot, "hello")
        await finish(pilot)
        text = app.transcript.text
        assert "▸ Model call failed: provider did not answer" in text
        assert "✗ Error · worked for 0s" in text
        assert "✗ error [model]: provider did not answer" in app.events_pane.text
        assert app.query(UserRow).first().text == "› hello"


async def test_phone_moves_the_badge_to_the_result_line(tmp_path: Path) -> None:
    app = make_app(
        tmp_path, [[ToolCall("get_light_state", {"room": "salon"})], "On."], tools=light_tools()
    )
    async with app.run_test(size=(50, 24)) as pilot:
        await send(pilot, "light?")
        await finish(pilot)
        card = app.query_one(ToolCard)
        assert card.line_text == '● get_light_state(room="salon")'
        assert card.text.splitlines()[1].startswith('⎿  tier 0 · {"on": true')
        await pilot.resize_terminal(80, 24)
        await wait_until(pilot, lambda: card.line_text.endswith("tier 0"))
