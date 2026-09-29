"""``build_history`` (pure) and the transcript's history loading, folding and paging."""

from __future__ import annotations

from datetime import UTC
from pathlib import Path

from helpers import SESSION_ID, fixed_clock, wait_until
from tau_core import AgentEvent, MemorySessionStore, build_agent
from tau_core.testing import FakeModel, test_config
from tau_tui import build_app
from tau_tui.history import HAssistant, HThinking, HTool, HUser, build_history, group_turns
from tau_tui.tools import ReasoningCard, ToolCard
from tau_tui.transcript import LIVE_TURNS, HistoryFold, ReplyBlock, Turn, UserRow


def _tier(name: str) -> int | None:
    return {"set_light": 2, "read": 0}.get(name)


def test_build_history_pairs_tool_uses_with_results_and_overlays_events() -> None:
    messages = [
        {"role": "user", "content": [{"text": "turn it off"}]},
        {
            "role": "assistant",
            "content": [
                {"reasoningContent": {"reasoningText": {"text": "hmm"}}},
                {"text": ""},
                {"toolUse": {"toolUseId": "t1", "name": "set_light", "input": {"on": False}}},
            ],
        },
        {
            "role": "user",
            "content": [
                {
                    "toolResult": {
                        "toolUseId": "t1",
                        "status": "success",
                        "content": [{"text": "off"}],
                    }
                },
                {
                    "toolResult": {
                        "toolUseId": "zz",
                        "status": "error",
                        "content": [{"json": {"a": 1}}],
                    }
                },
            ],
        },
        {"role": "assistant", "content": [{"text": "Done."}]},
        {"role": "user", "content": [{"image": {}}]},
    ]
    events = [
        AgentEvent.create(
            "tool_call",
            {"tool_use_id": "t1", "duration_ms": 412, "approval": "approved", "status": "rejected"},
            session_id=SESSION_ID,
        )
    ]
    items = build_history(messages, events, tier_of=_tier)
    assert items[0] == HUser("turn it off")
    assert items[1] == HThinking("hmm")
    tool = items[2]
    assert isinstance(tool, HTool)
    assert tool == HTool("t1", "set_light", {"on": False}, "rejected", "off", 2, 412, "approved")
    orphan = items[3]
    assert isinstance(orphan, HTool) and orphan.tool == "?" and orphan.status == "error"
    assert '"a": 1' in orphan.result_text
    assert items[4] == HAssistant("Done.")
    assert items[5] == HUser("[image]")
    assert [len(turn) for turn in group_turns(items)] == [5, 1]


async def test_load_history_shows_a_resumed_session_with_replayed_events(tmp_path: Path) -> None:
    config = test_config(tmp_path)
    store = MemorySessionStore()
    first = build_agent(
        config=config,
        model=FakeModel(["My first reply."]),
        tools=[],
        session_store=store,
        session_id=SESSION_ID,
        channel="tui",
    )
    assert await first.ask("my first message") == "My first reply."
    first.close()
    store.append_event(
        store.list_sessions()[0].session_id,
        AgentEvent.create(
            "tool_call",
            {
                "tool": "probe",
                "tier": 0,
                "status": "ok",
                "tool_use_id": "p1",
                "result_summary": "x",
            },
            session_id=SESSION_ID,
            clock=fixed_clock,
        ),
    )
    app = build_app(
        config,
        model=FakeModel([]),
        tools=[],
        session_store=store,
        session_id=SESSION_ID,
        clock=fixed_clock,
        tz=UTC,
        motion=False,
    )
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        text = app.transcript.text
        assert "› my first message" in text
        assert app.query_one(ReplyBlock).source == "My first reply."
        assert f"Resuming: my first message · {SESSION_ID} (2 messages loaded)." in text
        assert not app.query("#welcome")
        events = app.events_pane.text
        assert "· replayed 1 events ·" in events and "── live ──" in events
        assert "12:00:00 ● probe · tier 0 · ok" in events
        await wait_until(pilot, lambda: SESSION_ID in app.header.text)
    app.agent.close()


async def test_hundred_turns_fold_and_pageup_mounts_more(tmp_path: Path) -> None:
    config = test_config(tmp_path)
    store = MemorySessionStore()
    messages = []
    for n in range(100):
        messages.append({"role": "user", "content": [{"text": f"question {n}"}]})
        messages.append({"role": "assistant", "content": [{"text": f"answer {n}"}]})
    app = build_app(
        config,
        model=FakeModel([]),
        tools=[],
        session_store=store,
        session_id=SESSION_ID,
        clock=fixed_clock,
        tz=UTC,
        motion=False,
    )
    async with app.run_test(size=(80, 24)) as pilot:
        items = build_history(messages, [], tier_of=_tier)
        await app.transcript.load_history(items)
        await pilot.pause()
        assert len(app.query(Turn)) == LIVE_TURNS
        fold = app.query_one(HistoryFold)
        assert fold.content.plain == "… 60 earlier turns · PageUp at the top shows more"
        assert app.query(UserRow).first().text == "› question 60"
        app.transcript.history_provider = lambda: items
        app.transcript.scroll_home(animate=False)
        await pilot.pause()
        await pilot.press("pageup")
        await pilot.pause()
        assert len(app.query(Turn)) == LIVE_TURNS + 20
        assert fold.content.plain.startswith("… 40 earlier turns")
        assert app.query(UserRow).first().text == "› question 40"


async def test_history_tool_cards_keep_their_status(tmp_path: Path) -> None:
    app = build_app(
        test_config(tmp_path),
        model=FakeModel([]),
        tools=[],
        session_id=SESSION_ID,
        clock=fixed_clock,
        tz=UTC,
        motion=False,
        show_durations=True,
    )
    async with app.run_test(size=(80, 24)) as pilot:
        items = [
            HUser("go"),
            HTool("t1", "set_light", {"on": False}, "ok", "off", 2, 412, "approved"),
            HTool("t2", "read", {}, "rejected", "", 0),
            HAssistant("ok"),
        ]
        await app.transcript.load_history(items)
        await pilot.pause()
        cards = list(app.query(ToolCard))
        assert cards[0].text == "● set_light(on=false) tier 2 · approved · 412ms\n⎿  off"
        assert cards[1].text == "● read() tier 0\n⎿  ✗ read: not approved"
        assert cards[1].has_class("-follows")
        assert app.transcript.tool_cards["t1"] is cards[0]


def test_build_history_edge_blocks() -> None:
    messages = [
        {"role": "user", "content": [{"text": "   "}]},
        {"role": "system", "content": [{"text": "ignored"}]},
        {
            "role": "assistant",
            "content": [
                "not a block",
                {"toolUse": {"toolUseId": "r1", "name": "raw", "input": "just text"}},
                {"toolUse": {"toolUseId": "", "name": "unnamed"}},
            ],
        },
        {"role": "user", "content": [{"toolResult": {"toolUseId": "r1", "status": "success"}}]},
    ]
    items = build_history(messages, [], tier_of=lambda name: 1 / 0)  # tier lookup may fail
    assert all(not isinstance(item, HUser) for item in items)  # whitespace-only text dropped
    assert items[0] == HTool("r1", "raw", {"input": "just text"}, "ok", "", None)
    assert items[1] == HTool("", "unnamed", {}, None, "", None)
    assert group_turns(items) == [items]  # no user row: everything is turn 0
    assert group_turns([]) == []


async def test_history_reasoning_card_and_dangling_tool_use(tmp_path: Path) -> None:
    app = build_app(
        test_config(tmp_path),
        model=FakeModel([]),
        tools=[],
        session_id=SESSION_ID,
        clock=fixed_clock,
        tz=UTC,
        motion=False,
        show_durations=False,
    )
    async with app.run_test(size=(80, 24)) as pilot:
        items = [
            HUser("go"),
            HThinking("deep thought"),
            HTool("t1", "probe", {"q": "x"}, None, "", 0),  # a call that never returned
            HAssistant("ok"),
        ]
        await app.transcript.load_history(items)
        await pilot.pause()
        reasoning = app.query_one(ReasoningCard)
        assert reasoning.text == "✻ Thought" and not reasoning.open
        card = app.query_one(ToolCard)
        assert card.status == "error" and card.text == '● probe(q="x") tier 0\n⎿  ✗'
        turn = app.query_one(Turn)
        assert turn.tool_count == 1 and not turn.running
        await pilot.press("ctrl+o")
        await pilot.pause()
        assert reasoning.text == "✻ Thought\ndeep thought"
        assert app.query_one(ReplyBlock).source == "ok"
        assert app.transcript.text.startswith("› go\n✻ Thought\ndeep thought")
