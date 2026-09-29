"""The chat pane and the event pane.

Both are :class:`~textual.widgets.RichLog` widgets that keep their entries, so they can re-wrap
everything when the terminal is resized (a phone turned sideways) and the chat pane can rewrite
the reply that is still streaming. Turn events drive only the chat pane; the event pane is fed
by ``EventBus.subscribe`` and shows every agent event, unknown kinds included.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from rich.console import Group, RenderableType
from rich.table import Table
from rich.text import Text
from tau_core import (
    AgentEvent,
    EventBus,
    Notice,
    TextDelta,
    ToolFinished,
    ToolUseStarted,
    TurnEnd,
    TurnEvent,
)
from textual import events
from textual.geometry import Size
from textual.message import Message
from textual.widgets import RichLog

# Brand palette (docs/brand/render.py).
SIGNAL = "#FF2E63"
EMBER = "#FF7A3D"
FLARE = "#FFB25C"

USER_LABEL = "sen:"
TAU_LABEL = "tau:"
USER_STYLE = f"bold {FLARE}"
TAU_STYLE = f"bold {SIGNAL}"
NOTICE_STYLE = f"italic {EMBER}"
STATUS_STYLES = {"ok": "green", "error": "red", "rejected": "yellow"}
STATUS_MARKS = {"ok": "✓", "error": "✗", "rejected": "✗"}
DATA_LIMIT = 200


def _two_columns(label: RenderableType, body: RenderableType, *, label_width: int) -> Table:
    """A label column and a body column; wrapped body lines stay under the body."""
    grid = Table.grid(padding=(0, 1))
    grid.add_column(width=label_width, no_wrap=True)
    grid.add_column()
    grid.add_row(label, body)
    return grid


class TranscriptLog(RichLog):
    """A ``RichLog`` that remembers its entries.

    It re-renders them when its width changes (``RichLog`` alone wraps a line once, at write
    time) and can replace the last entry in place, which is how a reply streams.
    """

    DEFAULT_CSS = """
    TranscriptLog {
        scrollbar-size-vertical: 1;
        scrollbar-background: $surface;
        scrollbar-background-hover: $surface;
        scrollbar-background-active: $surface;
        scrollbar-color: $primary 40%;
    }
    """

    MAX_ENTRIES = 1000

    def __init__(self, *, id: str | None = None, classes: str | None = None) -> None:
        super().__init__(
            wrap=True,
            min_width=10,
            markup=False,
            highlight=False,
            auto_scroll=True,
            id=id,
            classes=classes,
        )
        self._entries: list[RenderableType] = []
        self._starts: list[int] = []  # first line of each entry; valid once rendered
        self._rendered_width: int | None = None

    @property
    def entry_count(self) -> int:
        return len(self._entries)

    @property
    def text(self) -> str:
        """What the pane shows, as plain text (one line per rendered row)."""
        return "\n".join(strip.text.rstrip() for strip in self.lines)

    def append_entry(self, entry: RenderableType) -> None:
        self._entries.append(entry)
        if len(self._entries) > self.MAX_ENTRIES:
            # Drop the oldest tenth at once so trimming stays rare.
            del self._entries[: len(self._entries) - self.MAX_ENTRIES + self.MAX_ENTRIES // 10]
            self._render_all()
            return
        if self._rendered_width is None:
            return  # rendered on the first resize, once the width is known
        self._starts.append(len(self.lines))
        self.write(entry)

    def replace_last(self, entry: RenderableType) -> None:
        if not self._entries:
            self.append_entry(entry)
            return
        self._entries[-1] = entry
        if self._rendered_width is None or len(self._starts) != len(self._entries):
            return
        del self.lines[self._starts[-1] :]
        self.virtual_size = Size(self.virtual_size.width, len(self.lines))
        self.notify_style_update()  # RichLog caches rendered lines by index; drop that cache
        self.write(entry)

    def _render_all(self) -> None:
        width = self.scrollable_content_region.width
        if width <= 0:
            self._rendered_width = None
            return
        self.clear()
        self._starts = []
        for entry in self._entries:
            self._starts.append(len(self.lines))
            self.write(entry, scroll_end=False)
        self._rendered_width = width
        if self.auto_scroll:
            self.scroll_end(animate=False)

    def on_resize(self, event: events.Resize) -> None:
        # RichLog's own resize handler runs after this one; re-render once it has.
        self.call_later(self._reflow)

    def _reflow(self) -> None:
        if self.scrollable_content_region.width != self._rendered_width:
            self._render_all()


class ChatPane(TranscriptLog):
    """``sen:`` and ``tau:`` blocks; tau's reply streams into its block."""

    def __init__(self, *, id: str | None = None, classes: str | None = None) -> None:
        super().__init__(id=id, classes=classes)
        self._reply: Text | None = None
        self._reply_index: int | None = None

    def _append(self, entry: RenderableType) -> None:
        self.end_reply()
        self.append_entry(entry)

    def add_user(self, text: str) -> None:
        block = _two_columns(Text(USER_LABEL, style=USER_STYLE), Text(text), label_width=4)
        self._append(Group(Text(""), block) if self.entry_count else block)

    def add_reply(self, text: str) -> None:
        """A complete reply (history of a resumed session)."""
        self._append(self._reply_block(Text(text)))

    def append_reply(self, delta: str) -> None:
        """Add streamed text to the current reply, starting a new ``tau:`` block if needed."""
        if self._reply is None or self._reply_index != self.entry_count - 1:
            self.end_reply()
            self._reply = Text(delta)
            self.append_entry(self._reply_block(self._reply.copy()))
            self._reply_index = self.entry_count - 1
            return
        self._reply.append(delta)
        self.replace_last(self._reply_block(self._reply.copy()))

    def end_reply(self) -> None:
        self._reply = None
        self._reply_index = None

    def add_tool_line(self, text: Text) -> None:
        self._append(_two_columns(Text(""), text, label_width=4))

    def add_notice(self, text: str) -> None:
        self.add_tool_line(Text.assemble("ℹ ", (text, NOTICE_STYLE)))

    def add_info(self, lines: Iterable[str]) -> None:
        self.add_tool_line(Text("\n".join(lines), style="dim"))

    def show_turn_event(self, event: TurnEvent) -> None:
        if isinstance(event, TextDelta):
            self.append_reply(event.text)
        elif isinstance(event, ToolUseStarted):
            tier = "?" if event.tier is None else str(event.tier)
            self.add_tool_line(Text(f"⚙ {event.tool} (tier {tier})", style="dim"))
        elif isinstance(event, ToolFinished):
            if event.status == "rejected":
                line = Text.assemble(("✗ ", "yellow"), (f"{event.tool}: onaylanmadı", "dim"))
            else:
                mark = STATUS_MARKS.get(event.status, "✗")
                style = STATUS_STYLES.get(event.status, "red")
                line = Text.assemble((f"{mark} ", style), (f"{event.tool}: {event.summary}", "dim"))
            self.add_tool_line(line)
        elif isinstance(event, Notice):
            self.add_notice(event.text)
        elif isinstance(event, TurnEnd):
            self.end_reply()

    def show_history(self, messages: Iterable[dict[str, Any]]) -> None:
        """Render a restored conversation: user and assistant text, tool uses as lines."""
        for message in messages:
            content = message.get("content") or []
            texts = [str(block["text"]) for block in content if "text" in block]
            text = "\n".join(t for t in texts if t.strip())
            if message.get("role") == "user":
                if text:
                    self.add_user(text)
                continue
            if text:
                self.add_reply(text)
            for block in content:
                if "toolUse" in block:
                    name = (block["toolUse"] or {}).get("name", "?")
                    self.add_tool_line(Text(f"⚙ {name}", style="dim"))

    @staticmethod
    def _reply_block(text: Text) -> Table:
        return _two_columns(Text(TAU_LABEL, style=TAU_STYLE), text, label_width=4)


def clock_text(at: datetime) -> str:
    """``HH:MM:SS`` in local time."""
    local = at.astimezone() if at.tzinfo is not None else at
    return local.strftime("%H:%M:%S")


def _compact(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return text if len(text) <= DATA_LIMIT else text[: DATA_LIMIT - 1] + "…"


def describe_event(event: AgentEvent) -> Text:
    """One agent event as a line of text; unknown kinds are shown with their data."""
    data = event.data
    kind = event.kind
    if kind == "tool_call":
        status = str(data.get("status") or "?")
        style = STATUS_STYLES.get(status, "")
        tier = data.get("tier")
        line = Text.assemble(
            (STATUS_MARKS.get(status, "•") + " ", style),
            (str(data.get("tool", "?")), "bold"),
            f" · tier {'?' if tier is None else tier} · ",
            (status, style),
        )
        if data.get("approval"):
            line.append(f" (onay: {data['approval']})")
        if data.get("duration_ms") is not None:
            line.append(f" · {data['duration_ms']} ms", style="dim")
        if data.get("result_summary"):
            line.append(f" — {data['result_summary']}", style="dim")
        return line
    if kind == "approval":
        decision = str(data.get("decision") or "?")
        tier = data.get("tier")
        return Text.assemble(
            ("⚠ ", FLARE),
            "onay: ",
            (str(data.get("tool", "?")), "bold"),
            f" · tier {'?' if tier is None else tier} → ",
            (decision, "green" if decision == "approved" else "yellow"),
            (f" ({data['channel']})" if data.get("channel") else "", "dim"),
        )
    if kind == "turn_limit":
        return Text.assemble(("ℹ ", EMBER), f"tur sınırı: {data.get('max_turns', '?')} tur")
    if kind == "error":
        where = f" [{data['where']}]" if data.get("where") else ""
        return Text.assemble(
            ("✗ ", "red"), (f"hata{where}", "bold red"), f": {data.get('message', '')}"
        )
    if kind == "notice":
        return Text.assemble(("ℹ ", EMBER), str(data.get("text", "")))
    return Text.assemble(("• ", "dim"), (kind, "bold"), ": ", (_compact(data), "dim"))


class EventPane(TranscriptLog):
    """Live agent events: time, tool, tier, status and approval, summary."""

    MAX_ENTRIES = 500

    class Received(Message):
        """An agent event arrived from the bus (posted, so any thread may emit)."""

        def __init__(self, event: AgentEvent) -> None:
            super().__init__()
            self.event = event

    def __init__(
        self, events: EventBus | None = None, *, id: str | None = None, classes: str | None = None
    ) -> None:
        super().__init__(id=id, classes=classes)
        self._bus = events
        self._unsubscribe = None

    def on_mount(self) -> None:
        self.border_title = "Olaylar"
        if self._bus is not None:
            self._unsubscribe = self._bus.subscribe(self._sink)

    def on_unmount(self) -> None:
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None

    def _sink(self, event: AgentEvent) -> None:
        self.post_message(self.Received(event))

    def on_event_pane_received(self, message: Received) -> None:
        message.stop()
        self.add_event(message.event)

    def add_event(self, event: AgentEvent) -> None:
        self.append_entry(
            _two_columns(
                Text(clock_text(event.at), style="dim"), describe_event(event), label_width=8
            )
        )
