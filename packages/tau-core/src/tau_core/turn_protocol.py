"""The turn protocol: the JSON form of a turn for the web app (ADR 0015 §1).

The spec is ``docs/reference/turn-protocol.md``; this module is its Python half, the
TypeScript half is ``cloud/shared/turn``. Both check the same vectors
(``cloud/shared/turn/vectors.json``, written by ``packages/tau-core/scripts/make_turn_vectors.py``).

A turn streams as NDJSON: one :func:`frame` per line, ``{"v": 1, "seq": n, "type": ..., ...}``.
The bodies come from :func:`turn_event_body` (every :data:`~tau_core.agent.TurnEvent`) and the
helpers for what is not a turn event: the turn's start, approvals, the guard, widgets and
errors. A stored session renders as :func:`history_blocks`.

Pure: no I/O, no clock, no agent. Transport, buffering and re-attaching are the backends' job.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any

from strands.types.session import SessionMessage

from tau_core.agent import (
    Notice,
    ReasoningDelta,
    TextDelta,
    Throttled,
    ToolFinished,
    ToolInput,
    ToolProgress,
    ToolUseStarted,
    TurnEnd,
    TurnEvent,
)
from tau_core.approval import ApprovalRequest, Decision
from tau_core.events import AgentEvent

PROTOCOL_VERSION = 1

INPUT_LIMIT = 8192
"""Bytes of UTF-8 JSON a tool input may take in an event or a history block; a larger one is
replaced by a ``preview`` of that many characters and ``truncated: true``."""

RENDER_UI_TOOL = "render_ui"
"""The tool whose calls are widgets (ADR 0015 §3): history shows them as ``widget`` blocks."""

EVENT_TYPES = (
    "turn",
    "text",
    "reasoning",
    "tool_use",
    "tool_input",
    "tool_progress",
    "tool_result",
    "approval",
    "approval_decided",
    "widget",
    "throttled",
    "notice",
    "guard",
    "end",
    "error",
)
"""Every ``type`` a stream event can have, in the order the spec lists them."""

BLOCK_TYPES = ("user", "assistant", "reasoning", "tool", "widget", "notice")
"""Every ``type`` a history block can have."""


# -- framing -----------------------------------------------------------------------------------


def frame(body: Mapping[str, Any], seq: int) -> dict[str, Any]:
    """``body`` as one protocol event: the version and its sequence number first."""
    if body.get("type") not in EVENT_TYPES:
        raise ValueError(f"not a turn protocol event: {body.get('type')!r}")
    return {"v": PROTOCOL_VERSION, "seq": seq, **body}


def encode(event: Mapping[str, Any]) -> str:
    """One NDJSON line (compact, UTF-8 text, ``\\n`` at the end)."""
    return json.dumps(event, ensure_ascii=False, separators=(",", ":"), default=str) + "\n"


def _input_fields(value: Any) -> dict[str, Any]:
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
    if len(text.encode("utf-8")) <= INPUT_LIMIT:
        return {"input": value, "truncated": False}
    return {"input": None, "preview": text[:INPUT_LIMIT], "truncated": True}


# -- stream event bodies -------------------------------------------------------------------------


def turn_started(turn_id: str, session_id: str) -> dict[str, Any]:
    """The first event of every turn."""
    return {"type": "turn", "turn": turn_id, "session": session_id}


def turn_event_body(event: TurnEvent) -> dict[str, Any]:
    """The body of one tau-core turn event."""
    match event:
        case TextDelta(text=text):
            return {"type": "text", "delta": text}
        case ReasoningDelta(text=text):
            return {"type": "reasoning", "delta": text}
        case ToolUseStarted(tool_use_id=tool_use_id, tool=tool, tier=tier):
            return {"type": "tool_use", "id": tool_use_id, "tool": tool, "tier": tier}
        case ToolInput(tool_use_id=tool_use_id, tool=tool, input=value):
            return {"type": "tool_input", "id": tool_use_id, "tool": tool, **_input_fields(value)}
        case ToolProgress(tool_use_id=tool_use_id, tool=tool, text=text):
            return {"type": "tool_progress", "id": tool_use_id, "tool": tool, "message": text}
        case ToolFinished():
            return {
                "type": "tool_result",
                "id": event.tool_use_id,
                "tool": event.tool,
                "status": event.status,
                "summary": event.summary,
                "approval": event.approval,
            }
        case Throttled(delay_seconds=delay):
            return {"type": "throttled", "delay_seconds": delay}
        case Notice(text=text):
            return {"type": "notice", "text": text}
        case TurnEnd(stop_reason=stop_reason):
            return {"type": "end", "stop_reason": stop_reason}
    raise TypeError(f"not a turn event: {event!r}")


def approval_body(request: ApprovalRequest, *, expires_at: float | None) -> dict[str, Any]:
    """A tier-2 call waiting for the owner; ``expires_at`` is Unix seconds, or ``None``."""
    return {
        "type": "approval",
        "request": request.request_id,
        "tool": request.tool,
        "tier": int(request.tier),
        "effect": request.effect,
        **_input_fields(request.arguments),
        "expires_at": expires_at,
    }


def approval_decided(request_id: str, decision: Decision | str) -> dict[str, Any]:
    """How an approval ended: ``approved``, ``rejected`` or ``timeout``."""
    value = Decision(decision).value
    return {"type": "approval_decided", "request": request_id, "decision": value}


def guard_body(data: Mapping[str, Any]) -> dict[str, Any]:
    """A ``guard`` agent event's data (ADR 0008: refusals, challenge steps) as a stream event."""
    body = {key: value for key, value in data.items() if key != "type"}
    return {"type": "guard", **body}


def widget_body(tool_use_id: str, title: str, html: str) -> dict[str, Any]:
    """A widget the model wrote with ``render_ui``; its id is the tool use's id."""
    return {"type": "widget", "id": tool_use_id, "title": title, "html": html}


def error_body(message: str) -> dict[str, Any]:
    """The backend failed outside the agent (the turn ends after it)."""
    return {"type": "error", "message": message}


# -- history -----------------------------------------------------------------------------------


def _when(value: str | datetime) -> datetime:
    when = datetime.fromisoformat(value) if isinstance(value, str) else value
    return when if when.tzinfo is not None else when.replace(tzinfo=UTC)


def _at(created_at: str | None) -> str | None:
    if not created_at:
        return None
    try:
        return _when(created_at).isoformat()
    except ValueError:
        return None


def _result_text(result: Mapping[str, Any]) -> str:
    content = result.get("content") or []
    texts = [str(block["text"]) for block in content if isinstance(block, dict) and "text" in block]
    if texts:
        return " ".join(texts)
    if content:
        return json.dumps(content, ensure_ascii=False, default=str)
    return ""


def _widget(use: Mapping[str, Any], at: str | None) -> dict[str, Any] | None:
    value = use.get("input")
    if not isinstance(value, dict):
        return None
    html, title = value.get("html"), value.get("title")
    if not isinstance(html, str) or not isinstance(title, str):
        return None
    return {
        "type": "widget",
        "id": str(use.get("toolUseId") or ""),
        "title": title,
        "html": html,
        "at": at,
    }


def history_blocks(
    messages: Iterable[SessionMessage | Mapping[str, Any]],
    events: Iterable[AgentEvent] = (),
    *,
    tiers: Mapping[str, int | None] | None = None,
) -> list[dict[str, Any]]:
    """A stored session as display blocks, oldest first.

    ``messages`` are the store's ``SessionMessage`` records (each block then carries its
    ``at``) or plain Strands messages (``at`` is ``None``). The messages are the truth; the
    agent events overlay what the store recorded about each tool call (status, tier, approval,
    summary, duration) and add the ``notice`` blocks, which are placed by time and so appear
    only when the messages have timestamps. A ``render_ui`` call with a valid input is a
    ``widget`` block instead of a ``tool`` block. ``tiers`` names a tool's current tier for
    calls whose event did not record one.
    """
    blocks: list[dict[str, Any]] = []
    tools: dict[str, dict[str, Any]] = {}
    for item in messages:
        if isinstance(item, SessionMessage):
            message, at = item.to_message(), _at(item.created_at)
        else:
            message, at = item, None
        role = message.get("role")
        content = message.get("content") or []
        if role == "user":
            texts: list[str] = []
            for block in content:
                if not isinstance(block, dict):
                    continue
                if "text" in block and str(block["text"]).strip():
                    texts.append(str(block["text"]))
                elif "toolResult" in block:
                    result = block["toolResult"] or {}
                    tool_use_id = str(result.get("toolUseId") or "")
                    status = "ok" if result.get("status") == "success" else "error"
                    tool = tools.get(tool_use_id)
                    if tool is None:  # a result whose use this history does not hold
                        tool = {
                            "type": "tool",
                            "id": tool_use_id,
                            "tool": "?",
                            "tier": None,
                            **_input_fields({}),
                            "status": status,
                            "summary": "",
                            "approval": None,
                            "duration_ms": None,
                            "at": at,
                        }
                        blocks.append(tool)
                        if tool_use_id:
                            tools[tool_use_id] = tool
                    if tool["type"] == "tool":
                        tool["status"] = status
                        tool["summary"] = _result_text(result)
                elif "image" in block or "document" in block:
                    texts.append("[image]")
            if texts:
                blocks.append({"type": "user", "text": "\n".join(texts), "at": at})
            continue
        if role != "assistant":
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if "reasoningContent" in block:
                reasoning = block["reasoningContent"] or {}
                text = str((reasoning.get("reasoningText") or {}).get("text") or "")
                if text.strip():
                    blocks.append({"type": "reasoning", "text": text, "at": at})
            elif "text" in block:
                text = str(block["text"])
                if not text.strip():
                    continue
                last = blocks[-1] if blocks else None
                if last is not None and last["type"] == "assistant" and last["at"] == at:
                    last["text"] += "\n\n" + text
                else:
                    blocks.append({"type": "assistant", "text": text, "at": at})
            elif "toolUse" in block:
                use = block["toolUse"] or {}
                tool_use_id = str(use.get("toolUseId") or "")
                name = str(use.get("name") or "?")
                widget = _widget(use, at) if name == RENDER_UI_TOOL else None
                if widget is not None:
                    blocks.append(widget)
                    if tool_use_id:
                        tools[tool_use_id] = widget
                    continue
                tool = {
                    "type": "tool",
                    "id": tool_use_id,
                    "tool": name,
                    "tier": (tiers or {}).get(name),
                    **_input_fields(use.get("input")),
                    "status": None,
                    "summary": "",
                    "approval": None,
                    "duration_ms": None,
                    "at": at,
                }
                blocks.append(tool)
                if tool_use_id:
                    tools[tool_use_id] = tool
    notices: list[dict[str, Any]] = []
    for event in events:
        if event.kind == "notice" and event.data.get("message"):
            notices.append(
                {
                    "type": "notice",
                    "text": str(event.data["message"]),
                    "at": _when(event.at).isoformat(),
                }
            )
            continue
        if event.kind != "tool_call":
            continue
        data = event.data
        tool = tools.get(str(data.get("tool_use_id") or ""))
        if tool is None or tool["type"] != "tool":
            continue
        if data.get("tier") is not None:
            tool["tier"] = int(data["tier"])
        if data.get("duration_ms") is not None:
            tool["duration_ms"] = int(data["duration_ms"])
        if data.get("approval"):
            tool["approval"] = str(data["approval"])
        status = data.get("status")
        if status == "rejected":  # refused before it ran: the message only says "error"
            tool["status"] = "rejected"
        elif status and tool["status"] is None:
            tool["status"] = str(status)
        if not tool["summary"] and data.get("result_summary"):
            tool["summary"] = str(data["result_summary"])
    return _place_notices(blocks, notices)


def _place_notices(
    blocks: list[dict[str, Any]], notices: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Each notice after the last block recorded at or before it; none without timestamps."""
    if not notices or not blocks or any(block["at"] is None for block in blocks):
        return blocks
    out: list[dict[str, Any]] = []
    pending = sorted(notices, key=lambda notice: _when(notice["at"]))
    for block in blocks:
        while pending and _when(pending[0]["at"]) < _when(block["at"]):
            out.append(pending.pop(0))
        out.append(block)
    return out + pending
