"""Shared helpers: an offline app (FakeModel, fixed clock, UTC, no motion, no durations).

Imported as ``helpers`` (``conftest.py`` puts this directory on ``sys.path``)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

from tau_core import (
    AgentEvent,
    Config,
    MemorySessionStore,
    Tier,
    ToolFinished,
    ToolUseStarted,
    tau_tool,
)
from tau_core.testing import FakeModel, test_config
from tau_tui import ApprovalScreen, TauApp, build_app
from tau_tui.composer import PromptArea
from tau_tui.transcript import Turn
from textual.pilot import Pilot

SESSION_ID = "20260929-120000-abcd"
FIXED_NOW = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
FIXED_VERSION = "0.0.0"
"""What the welcome card shows in tests: the source-tree fallback of ``tau_core.__version__``,
so a release never changes a snapshot."""
# Split so a repository-wide search for personal paths does not flag this file.
PATH_FRAGMENTS = ("/" + "Users/", "/" + "home/", "/" + "tmp/")

PROMPT = "Salon lambası açık mı? Açıksa kapat."
REPLY = (
    "Salon lambası **kapatıldı**.\n\n- Önceki durum: açık, %80 parlaklık\n- Şimdi: kapalı\n\n"
    "Başka bir şey ister misin?"
)
FENCE = 'set_light(room="salon", on=False)'
REPLY_FENCE = (
    "Salon lambası **kapatıldı**.\n\n- Önceki durum: açık, %80 parlaklık\n- Şimdi: kapalı\n\n"
    f"Kayıt için kullandığım komut:\n\n```python\n{FENCE}\n```\n\nBaşka bir şey ister misin?"
)
REPLY_REJECTED = (
    "Kapatma onaylanmadı, lambaya dokunmadım.\n\n- Durum: açık, %80 parlaklık\n"
    f"- Onaylarsan çalıştıracağım komut:\n\n```python\n{FENCE}\n```\n\nBaşka bir şey ister misin?"
)


def fixed_clock() -> datetime:
    return FIXED_NOW


def make_app(tmp_path: Path, replies: list[Any], tools: list[Any] | None = None, **kw) -> TauApp:
    kw.setdefault("model", FakeModel(replies))
    kw.setdefault("tz", UTC)
    kw.setdefault("motion", False)
    kw.setdefault("show_durations", False)
    kw.setdefault("config", test_config(tmp_path))
    kw.setdefault("session_id", SESSION_ID)
    kw.setdefault("clock", fixed_clock)
    kw.setdefault("version", FIXED_VERSION)
    return build_app(tools=tools or [], **kw)


async def steady(pilot: Pilot) -> None:
    pilot.app.query_one(PromptArea).cursor_blink = False
    await pilot.pause()


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
    """Fill the composer and press Enter (faster than typing every key)."""
    pilot.app.query_one(PromptArea).load_text(text)
    await pilot.press("enter")


async def finish(pilot: Pilot) -> None:
    app = pilot.app
    await wait_until(pilot, lambda: not app.busy)
    await pilot.pause()


def arm_tool(calls: list[dict[str, Any]]):
    @tau_tool(tier=Tier.PHYSICAL, effect="The test arm moves to the left.")
    def move_arm(direction: str) -> str:
        """Moves the test arm."""
        calls.append({"direction": direction})
        return f"arm moved {direction}"

    return move_arm


def light_tools():
    @tau_tool(tier=Tier.READ)
    def get_light_state(room: str) -> str:
        """Reads the state of a light."""
        return '{"on": true, "brightness": 80}'

    @tau_tool(tier=Tier.PHYSICAL, effect="turns a light on or off in the given room")
    def set_light(room: str, on: bool) -> str:
        """Switches a light on or off."""
        return "Light turned off"

    return [get_light_state, set_light]


# -- sessions with fixed timestamps ---------------------------------------------------------------


@contextmanager
def store_clock(when: datetime) -> Iterator[None]:
    """Freeze the ``updated_at`` stamps of ``MemorySessionStore`` writes at ``when``."""
    with patch("tau_core.sessions.memory.utc_now_iso", lambda: when.isoformat()):
        yield


async def seed_sessions(
    config: Config,
    store: MemorySessionStore,
    prompts: list[str],
    *,
    days_ago: list[int] | None = None,
) -> list[str]:
    """One earlier session per prompt (one ``ask`` each), oldest first; ids are returned.

    ``days_ago[i]`` fixes the ``updated_at`` of session ``i`` relative to :data:`FIXED_NOW`.
    """
    from tau_core import build_agent

    ids: list[str] = []
    for n, prompt in enumerate(prompts):
        when = FIXED_NOW - timedelta(days=days_ago[n] if days_ago else 0)
        session_id = f"{when:%Y%m%d}-1200{n:02d}-{n:04d}"
        with store_clock(when):
            agent = build_agent(
                config=config,
                model=FakeModel([f"reply {n}"]),
                tools=[],
                session_store=store,
                session_id=session_id,
                channel="tui",
            )
            await agent.ask(prompt)
            agent.close()
        ids.append(session_id)
    return ids


# -- scripted turns --------------------------------------------------------------------------------


def two_tool_replies(reply: str = REPLY) -> list[Any]:
    from tau_core.testing import ToolCall

    return [
        [ToolCall("get_light_state", {"room": "salon"})],
        [ToolCall("set_light", {"room": "salon", "on": False})],
        reply,
    ]


async def run_two_tool_turn(pilot: Pilot, *, decision: str = "y") -> None:
    """Send :data:`PROMPT` through the fake model, answer the tier-2 dialog, wait for the end."""
    app = pilot.app
    await steady(pilot)
    await send(pilot, PROMPT)
    await wait_until(pilot, lambda: isinstance(app.screen, ApprovalScreen))
    await pilot.press(decision)
    await finish(pilot)


def fixed_events() -> list[AgentEvent]:
    """The bus events of the two-tool turn, stamped with the fixed clock."""
    rows: list[tuple[str, dict[str, Any]]] = [
        (
            "tool_call",
            {
                "tool": "get_light_state",
                "tier": 0,
                "status": "ok",
                "arguments": {"room": "salon"},
                "result_summary": '{"on": true, "brightness": 80}',
                "tool_use_id": "t1",
                "duration_ms": 38,
            },
        ),
        (
            "approval",
            {
                "tool": "set_light",
                "tier": 2,
                "decision": "approved",
                "channel": "tui",
                "arguments": {"room": "salon", "on": False},
            },
        ),
        (
            "tool_call",
            {
                "tool": "set_light",
                "tier": 2,
                "status": "ok",
                "approval": "approved",
                "arguments": {"room": "salon", "on": False},
                "result_summary": "Light turned off",
                "tool_use_id": "t2",
                "duration_ms": 412,
            },
        ),
        ("notice", {"message": "turn ended", "reason": "test"}),
    ]
    return [
        AgentEvent.create(kind, data, session_id=SESSION_ID, clock=fixed_clock)
        for kind, data in rows
    ]


async def drive_two_tool_turn(pilot: Pilot, *, elapsed: float = 4, reply: str = REPLY) -> Turn:
    """The same turn driven straight into the transcript with fixed event clocks."""
    app = pilot.app
    turn = await app.transcript.begin_turn(PROMPT)
    await turn.add_tool(ToolUseStarted("t1", "get_light_state", 0))
    await turn.finish_tool(
        ToolFinished("t1", "get_light_state", "ok", '{"on": true, "brightness": 80}', None)
    )
    await turn.add_tool(ToolUseStarted("t2", "set_light", 2))
    await turn.finish_tool(ToolFinished("t2", "set_light", "ok", "Light turned off", "approved"))
    before = app.events_pane.log.count
    for event in fixed_events():
        app.bus.emit(event)
    await turn.feed_text(reply)
    await turn.end("end_turn", elapsed=elapsed)
    await wait_until(pilot, lambda: app.events_pane.log.count == before + 4)
    await pilot.pause()
    return turn
