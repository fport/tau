"""Turn a stored session (Strands messages plus tau's agent events) into transcript items.

Pure and unit-tested: no widgets. The messages are the truth (what the model saw); the
events overlay what the store recorded about each tool call (duration, approval, the tier at
the time, a result summary when the message has none). Nothing is dropped: an unmatched
``toolResult`` becomes a ``HTool("?", "?", ...)``; unknown blocks are skipped.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from tau_core import AgentEvent

RESULT_LIMIT = 200


@dataclass
class HUser:
    text: str


@dataclass
class HAssistant:
    markdown: str


@dataclass
class HThinking:
    text: str


@dataclass
class HTool:
    tool_use_id: str
    tool: str
    arguments: dict[str, Any]
    status: str | None
    result_text: str
    tier: int | None
    duration_ms: int | None = None
    approval: str | None = None


HistoryItem = HUser | HAssistant | HThinking | HTool


def _clip(text: str, limit: int = RESULT_LIMIT) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _result_text(result: dict[str, Any]) -> str:
    content = result.get("content") or []
    texts = [str(block["text"]) for block in content if isinstance(block, dict) and "text" in block]
    if texts:
        return _clip(" ".join(texts))
    if content:
        try:
            return _clip(json.dumps(content, ensure_ascii=False, default=str))
        except (TypeError, ValueError):
            return _clip(str(content))
    return ""


def build_history(
    messages: Iterable[dict[str, Any]],
    events: Iterable[AgentEvent],
    *,
    tier_of: Callable[[str], int | None],
) -> list[HistoryItem]:
    """Walk the messages in order, pair tool results with their uses, overlay the events."""
    items: list[HistoryItem] = []
    tools: dict[str, HTool] = {}
    for message in messages:
        role = message.get("role")
        content = message.get("content") or []
        if role == "user":
            texts: list[str] = []
            for block in content:
                if not isinstance(block, dict):
                    continue
                if "text" in block:
                    text = str(block["text"])
                    if text.strip():
                        texts.append(text)
                elif "toolResult" in block:
                    result = block["toolResult"] or {}
                    tool_use_id = str(result.get("toolUseId") or "")
                    status = "ok" if result.get("status") == "success" else "error"
                    tool = tools.get(tool_use_id)
                    if tool is None:
                        tool = HTool(
                            tool_use_id or "?", "?", {}, status, _result_text(result), None
                        )
                        items.append(tool)
                        if tool_use_id:
                            tools[tool_use_id] = tool
                    else:
                        tool.status = status
                        tool.result_text = _result_text(result)
                elif "image" in block or "document" in block:
                    texts.append("[image]")
            if texts:
                items.append(HUser("\n".join(texts)))
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
                    items.append(HThinking(text))
            elif "text" in block:
                text = str(block["text"])
                if text.strip():
                    items.append(HAssistant(text))
            elif "toolUse" in block:
                use = block["toolUse"] or {}
                tool_use_id = str(use.get("toolUseId") or "")
                name = str(use.get("name") or "?")
                raw = use.get("input")
                arguments = (
                    raw if isinstance(raw, dict) else ({} if raw is None else {"input": raw})
                )
                try:
                    tier = tier_of(name)
                except Exception:
                    tier = None
                tool = HTool(tool_use_id, name, dict(arguments), None, "", tier)
                items.append(tool)
                if tool_use_id:
                    tools[tool_use_id] = tool
    for event in events:
        if event.kind != "tool_call":
            continue
        data = event.data
        tool = tools.get(str(data.get("tool_use_id") or ""))
        if tool is None:
            continue
        if data.get("duration_ms") is not None:
            tool.duration_ms = int(data["duration_ms"])
        if data.get("approval"):
            tool.approval = str(data["approval"])
        if data.get("tier") is not None and tool.tier is None:
            tool.tier = int(data["tier"])
        status = data.get("status")
        if status == "rejected":
            tool.status = "rejected"
        elif status and tool.status is None:
            tool.status = str(status)
        if not tool.result_text and data.get("result_summary"):
            tool.result_text = _clip(str(data["result_summary"]))
    return items


def group_turns(items: Iterable[HistoryItem]) -> list[list[HistoryItem]]:
    """Split items into turns: a turn starts at each ``HUser``; leading items form turn 0."""
    turns: list[list[HistoryItem]] = []
    current: list[HistoryItem] = []
    for item in items:
        if isinstance(item, HUser) and current:
            turns.append(current)
            current = []
        current.append(item)
    if current:
        turns.append(current)
    return turns
