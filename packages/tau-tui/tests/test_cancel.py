"""Esc while busy cancels the turn through ``TauAgent.cancel()``."""

from __future__ import annotations

import threading
from pathlib import Path

from helpers import finish, make_app, send, wait_until
from tau_core import Tier, tau_tool
from tau_core.testing import ToolCall
from tau_tui.transcript import TurnFooter


async def test_escape_cancels_the_running_turn(tmp_path: Path) -> None:
    release = threading.Event()

    @tau_tool(tier=Tier.READ)
    def blocked() -> str:
        """Waits for the test."""
        release.wait(5)
        return "released"

    app = make_app(tmp_path, [[ToolCall("blocked", {})], "Never shown."], tools=[blocked])
    async with app.run_test(size=(80, 24)) as pilot:
        calls: list[str] = []
        real_cancel = app.agent.cancel

        def spy() -> None:
            calls.append("cancel")
            real_cancel()

        app.agent.cancel = spy  # type: ignore[method-assign]
        await send(pilot, "block")
        await wait_until(pilot, lambda: "✻ Running blocked…" in app.transcript.text)
        app.composer.prompt.load_text("draft kept")
        await pilot.press("escape")
        await pilot.pause()
        assert calls == ["cancel"]
        assert "✻ Cancelling…" in app.transcript.text
        await pilot.press("escape")  # a second Esc is a no-op
        await pilot.pause()
        assert calls == ["cancel"]
        release.set()
        await finish(pilot)
        footer = app.query_one(TurnFooter).content.plain
        assert footer.startswith("◆ Cancelled · worked for 0s · 1 tool call")
        assert "▸ Turn cancelled." in app.transcript.text
        assert "Never shown." not in app.transcript.text
        assert app.composer.text == "draft kept"
        assert not app.busy


async def test_escape_while_idle_never_reaches_the_agent(tmp_path: Path) -> None:
    app = make_app(tmp_path, [])
    async with app.run_test(size=(80, 24)) as pilot:
        calls: list[str] = []
        app.agent.cancel = lambda: calls.append("cancel")  # type: ignore[method-assign]
        app.composer.prompt.load_text("typed")
        await pilot.press("escape")
        await pilot.pause()
        assert calls == [] and app.composer.text == "typed"
        assert not app.busy and "✻" not in app.transcript.text
