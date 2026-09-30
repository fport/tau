"""State snapshots (``.raw`` SVG files under ``__snapshots__/test_snapshots``).

pytest-textual-snapshot 1.0 with syrupy 6 writes ``.raw``; the extension is pinned here (no
glob). Regenerate after an intended visual change with
``uv run pytest packages/tau-tui --snapshot-update`` and review the diff: the files must never
contain a local path. Every snapshot runs with ``motion=False``, ``show_durations=False``,
``tz=UTC``, the fixed clock, after ``steady`` and with every stream stopped, and every file
is checked for the fixed session id and against the personal path fragments.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from helpers import (
    FIXED_NOW,
    PATH_FRAGMENTS,
    PROMPT,
    REPLY_FENCE,
    REPLY_REJECTED,
    SESSION_ID,
    drive_two_tool_turn,
    finish,
    fixed_clock,
    fixed_events,
    light_tools,
    make_app,
    run_two_tool_turn,
    seed_sessions,
    send,
    steady,
    store_clock,
    two_tool_replies,
    wait_until,
)
from tau_core import AgentEvent, GuardProgress, MemorySessionStore, Tier, tau_tool
from tau_core.testing import FakeGuard, ToolCall, test_config
from tau_tui import ApprovalScreen, SettingsScreen
from tau_tui.guard import GuardScreen
from tau_tui.sessions import SessionPicker
from tau_tui.setup import SetupApp
from textual.pilot import Pilot
from textual.widgets import Input

SNAPSHOT_DIR = Path(__file__).parent / "__snapshots__" / Path(__file__).stem
EXTENSION = ".raw"
EARLIER = ["Yarın için alarm", "Kol robotu kalibrasyon", "Seyahat notları"]


def _check(name: str) -> None:
    path = SNAPSHOT_DIR / f"{name}{EXTENSION}"
    assert path.is_file(), f"{path.name} missing: run with --snapshot-update"
    assert [p.name for p in SNAPSHOT_DIR.glob(f"{name}.*")] == [path.name]  # exactly one
    svg = path.read_text(encoding="utf-8")
    assert SESSION_ID in svg
    for fragment in PATH_FRAGMENTS:
        assert fragment not in svg


def test_welcome_80x24(tmp_path: Path, snap_compare) -> None:
    app = make_app(tmp_path, [], tools=light_tools())
    assert snap_compare(app, terminal_size=(80, 24), run_before=steady)
    _check("test_welcome_80x24")


def test_welcome_50x24(tmp_path: Path, snap_compare) -> None:
    app = make_app(tmp_path, [], tools=light_tools())
    assert snap_compare(app, terminal_size=(50, 24), run_before=steady)
    _check("test_welcome_50x24")


def test_welcome_tr_80x24(tmp_path: Path, snap_compare) -> None:
    app = make_app(tmp_path, [], tools=light_tools())
    app.set_reactive(type(app).language, "tr")
    assert snap_compare(app, terminal_size=(80, 24), run_before=steady)
    _check("test_welcome_tr_80x24")


def test_chat_80x24(tmp_path: Path, snap_compare) -> None:
    """Spec §22: markdown list + fence + ok card + rejected card after ``TurnEnd``.

    The tier-2 call is rejected with ``n``: the card reads ``⎿ ✗ set_light: not approved``
    with an Ember dot, and the one-line fence costs one row plus its margins.
    """
    app = make_app(tmp_path, two_tool_replies(REPLY_REJECTED), tools=light_tools(), approve_delay=0)

    async def reject(pilot: Pilot) -> None:
        await run_two_tool_turn(pilot, decision="n")

    assert snap_compare(app, terminal_size=(80, 24), run_before=reject)
    _check("test_chat_80x24")


def test_busy_80x24(tmp_path: Path, snap_compare) -> None:
    """A tier-2 tool blocks after approval: ``○`` card, ``✻ Running…`` row, busy chrome."""
    gate = asyncio.Event()

    @tau_tool(tier=Tier.PHYSICAL, effect="turns a light on or off in the given room")
    async def set_light(room: str, on: bool) -> str:
        """Switches a light on or off."""
        await asyncio.wait_for(gate.wait(), 3)
        return "Light turned off"

    tools = [light_tools()[0], set_light]
    app = make_app(tmp_path, two_tool_replies(), tools=tools, approve_delay=0)

    async def until_running(pilot: Pilot) -> None:
        await steady(pilot)
        await send(pilot, PROMPT)
        await wait_until(pilot, lambda: isinstance(app.screen, ApprovalScreen))
        await pilot.press("y")
        await wait_until(pilot, lambda: "✻ Running set_light…" in app.transcript.text)
        await pilot.pause()

    assert snap_compare(app, terminal_size=(80, 24), run_before=until_running)
    _check("test_busy_80x24")


def test_approval_80x24(tmp_path: Path, snap_compare) -> None:
    """The dialog over the chat: the transcript stays visible behind the translucent modal."""
    app = make_app(tmp_path, two_tool_replies(), tools=light_tools(), approve_delay=0)

    async def until_modal(pilot: Pilot) -> None:
        await steady(pilot)
        await send(pilot, PROMPT)
        await wait_until(pilot, lambda: isinstance(app.screen, ApprovalScreen))
        await pilot.pause()

    assert snap_compare(app, terminal_size=(80, 24), run_before=until_modal)
    _check("test_approval_80x24")


def test_wide_100x30(tmp_path: Path, snap_compare) -> None:
    """Driven directly (fixed event clocks) so the events column is deterministic."""
    app = make_app(tmp_path, [], tools=light_tools())

    async def drive(pilot: Pilot) -> None:
        await steady(pilot)
        await drive_two_tool_turn(pilot)
        second = await app.transcript.begin_turn("Teşekkürler, bir de yarın 8'de alarm kur")
        assert second.busy_row is not None
        app.busy = True  # mockup 4.5: the second turn is thinking, so the chrome is busy too
        await pilot.pause()

    assert snap_compare(app, terminal_size=(100, 30), run_before=drive)
    _check("test_wide_100x30")


def test_ultra_160x45(tmp_path: Path, snap_compare) -> None:
    """Sidebar with dated sessions, the events column, a fence, the last turn's cards expanded."""
    config = test_config(tmp_path)
    store = MemorySessionStore()
    asyncio.run(seed_sessions(config, store, EARLIER, days_ago=[1, 2, 4]))
    with store_clock(FIXED_NOW):
        app = make_app(tmp_path, [], tools=light_tools(), config=config, session_store=store)

    async def drive(pilot: Pilot) -> None:
        with store_clock(FIXED_NOW):
            await steady(pilot)
            await drive_two_tool_turn(pilot, reply=REPLY_FENCE)
            await pilot.press("ctrl+o")
            await pilot.pause()

    assert snap_compare(app, terminal_size=(160, 45), run_before=drive)
    _check("test_ultra_160x45")


def test_menu_80x24(tmp_path: Path, snap_compare) -> None:
    app = make_app(tmp_path, ["Merhaba."], tools=light_tools())

    async def open_menu(pilot: Pilot) -> None:
        await steady(pilot)
        await send(pilot, "Merhaba tau")
        await finish(pilot)
        await pilot.press("slash")
        await pilot.pause()

    assert snap_compare(app, terminal_size=(80, 24), run_before=open_menu)
    _check("test_menu_80x24")


def test_picker_80x24(tmp_path: Path, snap_compare) -> None:
    config = test_config(tmp_path)
    store = MemorySessionStore()
    asyncio.run(seed_sessions(config, store, EARLIER, days_ago=[0, 1, 2]))
    with store_clock(FIXED_NOW):
        app = make_app(
            tmp_path, ["Merhaba."], tools=light_tools(), config=config, session_store=store
        )

    async def open_picker(pilot: Pilot) -> None:
        with store_clock(FIXED_NOW):
            await steady(pilot)
            await send(pilot, "Merhaba tau")
            await finish(pilot)
            await pilot.press("ctrl+r")
            await wait_until(pilot, lambda: isinstance(app.screen, SessionPicker))
            await pilot.pause()

    assert snap_compare(app, terminal_size=(80, 24), run_before=open_picker)
    _check("test_picker_80x24")


def test_events_50x24(tmp_path: Path, snap_compare) -> None:
    """The phone's events view: replayed events, the live rule and three live events.

    The phone header drops the session id by design, so an unknown-kind live event carries
    it for the snapshot check.
    """
    app = make_app(tmp_path, [], tools=light_tools())

    async def show_events(pilot: Pilot) -> None:
        await steady(pilot)
        app.events_pane.clear_all()
        app.events_pane.replay(fixed_events())
        for kind, data in [
            ("error", {"message": "connection reset", "where": "model"}),
            ("mesh_event", {"topic": "home/hall/temp", "value": 22}),
            ("hub", {"session": SESSION_ID, "state": "online"}),
        ]:
            app.bus.emit(AgentEvent.create(kind, data, session_id=SESSION_ID, clock=fixed_clock))
        await wait_until(pilot, lambda: app.events_pane.log.count == 7)
        await pilot.press("f4")
        await pilot.pause()

    assert snap_compare(app, terminal_size=(50, 24), run_before=show_events)
    _check("test_events_50x24")


def test_short_80x18(tmp_path: Path, snap_compare) -> None:
    """``-short``: no hint row, the composer capped at two text rows, a finished turn."""
    replies = [[ToolCall("get_light_state", {"room": "salon"})], "Salon lambası **açık**."]
    app = make_app(tmp_path, replies, tools=light_tools())

    async def chat(pilot: Pilot) -> None:
        await steady(pilot)
        await send(pilot, PROMPT)
        await finish(pilot)
        for line in ("bir", "iki", "üç"):
            app.composer.prompt.insert(line + "\n")
        await pilot.pause()

    assert snap_compare(app, terminal_size=(80, 18), run_before=chat)
    _check("test_short_80x18")


def test_settings_80x24(tmp_path: Path, snap_compare) -> None:
    """The settings screen on Model roles: the fake provider, no path anywhere (``show_paths``
    is off, the title never carries the home)."""
    app = make_app(tmp_path, [], tools=light_tools(), show_paths=False)

    async def open_settings(pilot: Pilot) -> None:
        await steady(pilot)
        await send(pilot, "/settings")
        await wait_until(pilot, lambda: isinstance(app.screen, SettingsScreen))
        await pilot.pause()

    assert snap_compare(app, terminal_size=(80, 24), run_before=open_settings)
    _check("test_settings_80x24")


def test_setup_80x24(tmp_path: Path, snap_compare) -> None:
    """The first-run screen: the home field shows the canonical ``~/.tau`` (``show_paths``
    is off; the detection reads a temp home, never the developer's) and nothing is detected."""
    app = SetupApp(default_home=tmp_path / "fresh", env={}, language="en", show_paths=False)

    async def settle(pilot: Pilot) -> None:
        await pilot.pause()

    assert snap_compare(app, terminal_size=(80, 24), run_before=settle)
    path = SNAPSHOT_DIR / f"test_setup_80x24{EXTENSION}"
    assert path.is_file()
    svg = path.read_text(encoding="utf-8")
    for fragment in PATH_FRAGMENTS + ("/private/",):
        assert fragment not in svg


# -- the owner guard (issue 113) ---------------------------------------------------------------


def _check_lock(name: str, *hidden: str) -> None:
    """The lock screen hides the session: no session id and none of ``hidden`` in the file."""
    path = SNAPSHOT_DIR / f"{name}{EXTENSION}"
    assert path.is_file(), f"{path.name} missing: run with --snapshot-update"
    assert [p.name for p in SNAPSHOT_DIR.glob(f"{name}.*")] == [path.name]
    svg = path.read_text(encoding="utf-8")
    assert "tau&#160;is&#160;locked" in svg
    for text in (SESSION_ID, *hidden, *PATH_FRAGMENTS):
        assert text not in svg, text


async def _steady_lock(pilot: Pilot) -> None:
    app = pilot.app
    await wait_until(pilot, lambda: isinstance(app.screen, GuardScreen))
    await wait_until(pilot, lambda: app.guard_status is not None)  # the watcher's first answer
    pilot.app.screen.query_one(Input).cursor_blink = False
    await pilot.pause()


def test_lock_80x24(tmp_path: Path, snap_compare) -> None:
    """The first screen with a guard: opaque, the trigger, Enter / Esc / ctrl+q; no session."""
    guard = FakeGuard("locked")
    guard.set_state("locked", trigger="idle")
    app = make_app(tmp_path, [], tools=light_tools(), guard=guard)
    assert snap_compare(app, terminal_size=(80, 24), run_before=_steady_lock)
    _check_lock("test_lock_80x24")


def test_lock_over_chat_80x24(tmp_path: Path, snap_compare) -> None:
    """A lock during a session: the transcript behind the lock screen does not show through."""
    guard = FakeGuard("unlocked")
    app = make_app(tmp_path, [REPLY_FENCE], tools=light_tools(), guard=guard)

    async def chat_then_lock(pilot: Pilot) -> None:
        await wait_until(pilot, lambda: app.agent is not None and not app.locked)
        await steady(pilot)
        await send(pilot, PROMPT)
        await finish(pilot)
        guard.set_state("locked", trigger="screen_lock")
        await _steady_lock(pilot)

    assert snap_compare(app, terminal_size=(80, 24), run_before=chat_then_lock)
    _check_lock("test_lock_over_chat_80x24", "Salon", "set_light")


class _StepUpGuard(FakeGuard):
    """A step-up that shows two challenge steps and holds (at most 3 s)."""

    def __init__(self) -> None:
        super().__init__("unlocked")
        self.release = asyncio.Event()

    async def step_up(self, request, *, client_id, on_progress=None):  # type: ignore[override]
        if on_progress is not None:
            on_progress(GuardProgress("look", 1, None))
            on_progress(GuardProgress("turn_left", 2, None))
        try:
            await asyncio.wait_for(self.release.wait(), 3)
        except TimeoutError:
            return False
        return True


def test_step_up_80x24(tmp_path: Path, snap_compare) -> None:
    """A tier-2 step-up in progress: the challenge step in the busy line, the camera glyph
    next to the lock glyph in the header."""
    guard = _StepUpGuard()
    app = make_app(tmp_path, two_tool_replies(), tools=light_tools(), approve_delay=0, guard=guard)

    async def until_step(pilot: Pilot) -> None:
        await wait_until(pilot, lambda: app.agent is not None and not app.locked)
        await steady(pilot)
        await send(pilot, PROMPT)
        await wait_until(pilot, lambda: isinstance(app.screen, ApprovalScreen))
        await pilot.press("y")
        await wait_until(pilot, lambda: "Turn your head left." in app.transcript.text)
        await pilot.pause()

    assert snap_compare(app, terminal_size=(80, 24), run_before=until_step)
    _check("test_step_up_80x24")
