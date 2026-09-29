"""The events pane: every style string is a real Rich style and the log stays bounded."""

from __future__ import annotations

from pathlib import Path

from helpers import SESSION_ID, fixed_clock, make_app
from rich.style import Style
from tau_core import AgentEvent
from tau_tui.events import MAX_LINES, STATUS_COLOUR, clock_style, describe_event
from tau_tui.theme import TEXT_DISABLED, TEXT_MUTED

KINDS: list[tuple[str, dict]] = [
    ("tool_call", {"tool": "x", "tier": 0, "status": "running", "tool_use_id": "a"}),
    (
        "tool_call",
        {"tool": "x", "tier": 0, "status": "ok", "duration_ms": 5, "result_summary": "r"},
    ),
    ("tool_call", {"tool": "x", "tier": 2, "status": "error"}),
    ("tool_call", {"tool": "x", "tier": 2, "status": "rejected", "approval": "rejected"}),
    ("tool_call", {"tool": "x", "status": "weird"}),
    ("approval", {"tool": "x", "tier": 2, "decision": "approved", "channel": "tui"}),
    ("turn_limit", {"max_turns": 12}),
    ("turn_limit", {"max_total_tokens": 4000}),
    ("error", {"message": "boom", "where": "model"}),
    ("notice", {"message": "hub restarted"}),
    ("mesh_event", {"topic": "home/hall/temp", "value": 22}),
]


def _styles(kind: str, data: dict) -> list[str]:
    event = AgentEvent.create(kind, data, session_id=SESSION_ID, clock=fixed_clock)
    text = describe_event(event, "en", show_durations=True)
    return [span.style for span in text.spans if isinstance(span.style, str)]


def test_every_event_style_is_a_valid_rich_style() -> None:
    """``"#FFF4E0 55%"`` is TCSS, not Rich: it used to leave the running dot unstyled."""
    seen: list[str] = []
    for kind, data in KINDS:
        for style in _styles(kind, data):
            Style.parse(style)  # raises StyleSyntaxError on a TCSS alpha suffix
            seen.append(style)
    for style in (*STATUS_COLOUR.values(), clock_style(False), clock_style(True)):
        Style.parse(style)
    assert seen  # the walk saw styled spans
    running = _styles("tool_call", {"tool": "x", "status": "running"})[0]
    assert Style.parse(running).color is not None and running == TEXT_MUTED


def test_clock_column_is_muted_live_and_disabled_when_replayed() -> None:
    assert clock_style(False) == TEXT_MUTED and clock_style(True) == TEXT_DISABLED
    assert Style.parse(TEXT_MUTED).color != Style.parse(TEXT_DISABLED).color
    assert TEXT_MUTED.startswith("#") and len(TEXT_MUTED) == 7


async def test_event_log_entries_are_bounded_like_the_log(tmp_path: Path) -> None:
    app = make_app(tmp_path, [])
    async with app.run_test(size=(100, 30)) as pilot:
        log = app.events_pane.log
        extra = 20
        for i in range(MAX_LINES + extra):
            event = AgentEvent.create("hub", {"i": i}, session_id=SESSION_ID, clock=fixed_clock)
            log.add_event(event)
        await pilot.pause()
        lines = log.text.splitlines()
        assert log.count == MAX_LINES + extra
        assert len(lines) == MAX_LINES
        assert lines[0].endswith(f'"i": {extra}}}') and lines[-1].endswith(
            f'"i": {MAX_LINES + extra - 1}}}'
        )
        log.clear_all()
        assert log.text == "" and log.count == 0
