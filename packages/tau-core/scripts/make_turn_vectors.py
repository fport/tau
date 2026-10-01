"""Write ``cloud/shared/turn/vectors.json``: the turn protocol as tau-core produces it.

The TypeScript half (``cloud/shared/turn``) validates every event and history block in it, so
both halves agree on the shapes (issue 177). ``test_turn_protocol.py`` fails when the file is
stale::

    uv run python packages/tau-core/scripts/make_turn_vectors.py           # write
    uv run python packages/tau-core/scripts/make_turn_vectors.py --check   # exit 1 when stale
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from strands.types.session import SessionMessage
from tau_core import (
    STOP_REASONS,
    AgentEvent,
    ApprovalRequest,
    Notice,
    ReasoningDelta,
    TextDelta,
    Throttled,
    Tier,
    ToolFinished,
    ToolInput,
    ToolProgress,
    ToolUseStarted,
    TurnEnd,
)
from tau_core.turn_protocol import (
    BLOCK_TYPES,
    EVENT_TYPES,
    INPUT_LIMIT,
    PROTOCOL_VERSION,
    approval_body,
    approval_decided,
    error_body,
    frame,
    guard_body,
    history_blocks,
    turn_event_body,
    turn_started,
    widget_body,
)

VECTORS_PATH = Path(__file__).resolve().parents[3] / "cloud" / "shared" / "turn" / "vectors.json"

WIDGET_HTML = (
    '<!doctype html><html><body><h1 style="color:var(--fire)">HOME 7 : 3 AWAY</h1>'
    "<button onclick=\"document.querySelector('h1').textContent='HOME 13 : 3 AWAY'\">TD</button>"
    "</body></html>"
)


def _stream() -> list[dict[str, Any]]:
    request = ApprovalRequest(
        request_id="a1",
        tool="lamp_set",
        tier=Tier.PHYSICAL,
        arguments={"name": "desk", "on": True},
        effect="physical",
        session_id="20261001-080000-abcd",
        channel="web",
    )
    bodies = [
        turn_started("t-1", "20261001-080000-abcd"),
        turn_event_body(ReasoningDelta(text="The owner wants the desk lamp on.")),
        turn_event_body(ToolUseStarted(tool_use_id="u1", tool="lamp_set", tier=2)),
        turn_event_body(
            ToolInput(tool_use_id="u1", tool="lamp_set", input={"name": "desk", "on": True})
        ),
        approval_body(request, expires_at=1790841900.0),
        guard_body({"action": "challenge", "step": "turn_left", "hint": "", "request_id": "a1"}),
        approval_decided("a1", "approved"),
        turn_event_body(ToolProgress(tool_use_id="u1", tool="lamp_set", text="switching")),
        turn_event_body(
            ToolFinished(
                tool_use_id="u1",
                tool="lamp_set",
                status="ok",
                summary="desk lamp is on (simulated)",
                approval="approved",
            )
        ),
        turn_event_body(ToolUseStarted(tool_use_id="u2", tool="render_ui", tier=0)),
        turn_event_body(
            ToolInput(tool_use_id="u2", tool="render_ui", input={"title": "x" * INPUT_LIMIT})
        ),
        widget_body("u2", "Scoreboard", WIDGET_HTML),
        turn_event_body(
            ToolFinished(
                tool_use_id="u2", tool="render_ui", status="ok", summary="rendered", approval=None
            )
        ),
        turn_event_body(Throttled(delay_seconds=2.0)),
        turn_event_body(TextDelta(text="The desk lamp is on, ")),
        turn_event_body(TextDelta(text="and here is the scoreboard.")),
        turn_event_body(Notice(text="brain is over its daily budget; fast answered instead")),
        error_body("the hub lost the session lock"),
        turn_event_body(TurnEnd(stop_reason="end_turn")),
    ]
    return [frame(body, seq) for seq, body in enumerate(bodies)]


def _at(second: int) -> str:
    return datetime(2026, 10, 1, 8, 0, second, tzinfo=UTC).isoformat()


def _history() -> list[dict[str, Any]]:
    messages = [
        {"role": "user", "content": [{"text": "Turn on the desk lamp and draw a scoreboard."}]},
        {
            "role": "assistant",
            "content": [
                {"reasoningContent": {"reasoningText": {"text": "Two tools."}}},
                {"text": "On it."},
                {
                    "toolUse": {
                        "toolUseId": "u1",
                        "name": "lamp_set",
                        "input": {"name": "desk", "on": True},
                    }
                },
                {
                    "toolUse": {
                        "toolUseId": "u2",
                        "name": "render_ui",
                        "input": {"title": "Scoreboard", "html": WIDGET_HTML},
                    }
                },
                {
                    "toolUse": {
                        "toolUseId": "u3",
                        "name": "lamp_set",
                        "input": {"name": "hall", "on": True},
                    }
                },
            ],
        },
        {
            "role": "user",
            "content": [
                {
                    "toolResult": {
                        "toolUseId": "u1",
                        "status": "success",
                        "content": [{"text": "desk lamp is on"}],
                    }
                },
                {
                    "toolResult": {
                        "toolUseId": "u2",
                        "status": "success",
                        "content": [{"text": "rendered"}],
                    }
                },
                {
                    "toolResult": {
                        "toolUseId": "u3",
                        "status": "error",
                        "content": [{"text": "The user rejected it."}],
                    }
                },
            ],
        },
        {"role": "assistant", "content": [{"text": "The desk lamp is on; the hall stays off."}]},
    ]
    stored = [
        SessionMessage(
            message=message,
            message_id=index,
            created_at=_at(index * 10),
            updated_at=_at(index * 10),
        )
        for index, message in enumerate(messages)
    ]
    events = [
        AgentEvent.create(
            "tool_call",
            {
                "tool": "lamp_set",
                "tier": 2,
                "status": "ok",
                "approval": "approved",
                "duration_ms": 12,
                "tool_use_id": "u1",
            },
            session_id="s",
            clock=lambda: datetime.fromisoformat(_at(21)),
        ),
        AgentEvent.create(
            "tool_call",
            {
                "tool": "lamp_set",
                "tier": 2,
                "status": "rejected",
                "approval": "rejected",
                "tool_use_id": "u3",
            },
            session_id="s",
            clock=lambda: datetime.fromisoformat(_at(22)),
        ),
        AgentEvent.create(
            "notice",
            {
                "message": "brain is over its daily budget; fast answered instead",
                "reason": "degraded",
            },
            session_id="s",
            clock=lambda: datetime.fromisoformat(_at(25)),
        ),
    ]
    return history_blocks(stored, events, tiers={"render_ui": 0})


def _invalid() -> list[dict[str, Any]]:
    """Events a validator must refuse."""
    good = frame(turn_event_body(TextDelta(text="hi")), 0)
    return [
        {**good, "v": 2},
        {**good, "seq": -1},
        {**good, "type": "telepathy"},
        {key: value for key, value in good.items() if key != "delta"},
        {**frame(turn_event_body(TurnEnd(stop_reason="end_turn")), 1), "stop_reason": 7},
        {**frame(approval_decided("a1", "approved"), 2), "decision": "maybe"},
    ]


def make_vectors() -> dict[str, Any]:
    return {
        "comment": "Written by packages/tau-core/scripts/make_turn_vectors.py; do not edit.",
        "version": PROTOCOL_VERSION,
        "input_limit": INPUT_LIMIT,
        "event_types": list(EVENT_TYPES),
        "block_types": list(BLOCK_TYPES),
        "stop_reasons": list(STOP_REASONS),
        "stream": _stream(),
        "history": _history(),
        "invalid": _invalid(),
    }


def render() -> str:
    return json.dumps(make_vectors(), ensure_ascii=False, indent=2) + "\n"


def main(argv: list[str]) -> int:
    text = render()
    if "--check" in argv:
        current = VECTORS_PATH.read_text(encoding="utf-8") if VECTORS_PATH.exists() else ""
        if current != text:
            print(f"{VECTORS_PATH} is stale: run this script without --check", file=sys.stderr)
            return 1
        return 0
    VECTORS_PATH.parent.mkdir(parents=True, exist_ok=True)
    VECTORS_PATH.write_text(text, encoding="utf-8")
    print(f"wrote {VECTORS_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
