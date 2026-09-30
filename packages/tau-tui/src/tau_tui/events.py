"""The events pane: every agent event of the current session, replayed and live."""

from __future__ import annotations

import json
from collections import deque
from datetime import datetime, tzinfo
from typing import Any

from rich.console import RenderableType
from rich.table import Table
from rich.text import Text
from tau_core import AgentEvent, t
from textual.containers import Vertical
from textual.widgets import RichLog, Static

from tau_tui.theme import EMBER, FLARE, SIGNAL, TEXT_DISABLED, TEXT_MUTED, glyph

DATA_LIMIT = 200
MAX_LINES = 500
STATUS_COLOUR = {"ok": FLARE, "error": SIGNAL, "rejected": EMBER}
"""Dot colour by ``tool_call`` status; running/pending (and unknown) fall back to muted Core.

Every style string here must be a literal ``rich.style.Style`` can parse: TCSS alpha suffixes
(``"#FFF4E0 55%"``) are silently dropped by Rich and the text renders unstyled.
"""


def clock_text(at: datetime, tz: tzinfo | None = None) -> str:
    """``HH:MM:SS`` in ``tz`` (``None`` → local time)."""
    if at.tzinfo is None:
        local = at
    else:
        local = at.astimezone(tz) if tz is not None else at.astimezone()
    return local.strftime("%H:%M:%S")


def _compact(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return text if len(text) <= DATA_LIMIT else text[: DATA_LIMIT - 1] + "…"


def describe_event(event: AgentEvent, language: str = "en", *, show_durations: bool = True) -> Text:
    """One agent event as text; unknown kinds show their data."""
    data = event.data
    kind = event.kind
    if kind == "tool_call":
        status = str(data.get("status") or "?")
        colour = STATUS_COLOUR.get(status, TEXT_MUTED)
        dot = glyph("tool_run") if status == "running" else glyph("tool_done")
        tier = data.get("tier")
        line = Text.assemble(
            (dot + " ", colour),
            (str(data.get("tool", "?")), "bold"),
            f" · tier {'?' if tier is None else tier} · {status}",
        )
        if data.get("approval"):
            line.append(f" · {data['approval']}")
        if show_durations and data.get("duration_ms") is not None:
            line.append(f" · {data['duration_ms']}ms", style="dim")
        if data.get("result_summary"):
            line.append(f"\n— {data['result_summary']}", style="dim")
        return line
    if kind == "approval":
        decision = str(data.get("decision") or "?")
        tier = data.get("tier")
        line = Text.assemble(
            (glyph("attention") + " ", FLARE),
            f"{t('tui.event.approval', language)} ",
            (str(data.get("tool", "?")), "bold"),
            f" · tier {'?' if tier is None else tier} → {decision}",
        )
        if data.get("channel"):
            line.append(f" ({data['channel']})", style="dim")
        return line
    if kind == "turn_limit":
        if data.get("max_total_tokens") is not None and data.get("max_turns") is None:
            label = t("tui.event.token_limit", language, n=data["max_total_tokens"])
        else:
            label = t("tui.event.turn_limit", language, n=data.get("max_turns", "?"))
        return Text.assemble((glyph("attention") + " ", FLARE), label)
    if kind == "error":
        where = f" [{data['where']}]" if data.get("where") else ""
        return Text.assemble(
            (glyph("fail") + " ", SIGNAL),
            (f"{t('tui.event.error', language)}{where}", f"bold {SIGNAL}"),
            f": {data.get('message', '')}",
        )
    if kind == "notice":
        text = data.get("message") if data.get("message") is not None else data.get("text", "")
        return Text.assemble(
            (glyph("notice") + " ", EMBER), f"{t('tui.event.notice', language)} · {text}"
        )
    if kind == "guard":
        parts = [str(data.get("action") or "?")]
        for key in ("phase", "step", "reason", "tool"):
            if data.get(key):
                parts.append(str(data[key]))
        if "ok" in data:
            parts.append(glyph("ok") if data["ok"] is True else glyph("fail"))
        return Text.assemble(
            (glyph("lock") + " ", FLARE), f"{t('tui.event.guard', language)} · {' · '.join(parts)}"
        )
    return Text.assemble(
        (glyph("bullet") + " ", "dim"), (kind, "bold"), ": ", (_compact(data), "dim")
    )


def clock_style(replayed: bool) -> str:
    """The clock column: ``$text-disabled`` for replayed events, ``$text-muted`` for live ones."""
    return TEXT_DISABLED if replayed else TEXT_MUTED


def _two_columns(label: RenderableType, body: RenderableType, *, label_width: int) -> Table:
    grid = Table.grid(padding=(0, 1))
    grid.add_column(width=label_width, no_wrap=True)
    grid.add_column()
    grid.add_row(label, body)
    return grid


class EventLog(RichLog):
    """Agent events, two columns: the clock and the description."""

    DEFAULT_CSS = """
    EventLog { height: 1fr; padding: 0 1; scrollbar-size-vertical: 1; }
    """

    def __init__(self, *, id: str | None = "events-log") -> None:
        super().__init__(
            wrap=True,
            min_width=10,
            markup=False,
            highlight=False,
            auto_scroll=True,
            max_lines=MAX_LINES,
            id=id,
        )
        self.language = "en"
        self.tz: tzinfo | None = None
        self.show_durations = True
        self.count = 0
        self._entries: deque[str] = deque(maxlen=MAX_LINES)  # what the log still shows

    def add_event(self, event: AgentEvent, *, replayed: bool = False) -> None:
        self.count += 1
        clock = Text(clock_text(event.at, self.tz), style=clock_style(replayed))
        body = describe_event(event, self.language, show_durations=self.show_durations)
        self._entries.append(f"{clock.plain} {body.plain}")
        self.write(_two_columns(clock, body, label_width=8), scroll_end=True, animate=False)

    def _rule(self, text: str) -> None:
        self._entries.append(text)
        self.write(Text(text, style="dim"))

    def replay(self, events: list[AgentEvent]) -> None:
        if not events:
            return
        self._rule(t("tui.events.replayed", self.language, n=len(events)))
        for event in events:
            self.add_event(event, replayed=True)
        self._rule(t("tui.events.live", self.language))
        self.scroll_end(animate=False)

    def clear_all(self) -> None:
        self.clear()
        self.count = 0
        self._entries.clear()

    @property
    def text(self) -> str:
        """The kept entries as unwrapped lines (independent of the pane's width or display).

        Bounded like the log itself: the oldest entries leave once ``MAX_LINES`` is reached.
        """
        return "\n".join(self._entries)


class EventsPane(Vertical):
    SCOPED_CSS = False
    DEFAULT_CSS = """
    EventsPane { display: none; width: 34; height: 1fr; border-left: solid $primary 35%; }
    EventsPane #events-title { height: 1; padding: 0 1; color: $text-muted; }
    Screen.-wide EventsPane, Screen.-ultra EventsPane { display: block; }
    Screen.-ultra EventsPane { width: 40; }
    Screen.-wide.-events-hidden EventsPane, Screen.-ultra.-events-hidden EventsPane {
        display: none;
    }
    Screen.-narrow.-tall EventsPane {
        display: block; width: 100%; height: 8; border-left: none; border-top: solid $primary 35%;
    }
    Screen.-phone.-events EventsPane, Screen.-narrow.-events EventsPane {
        display: block; width: 1fr; height: 1fr; border: none;
    }
    Screen.-phone.-events EventsPane #events-title { display: none; }
    """

    def __init__(self, language: str = "en", *, id: str | None = "events") -> None:
        super().__init__(id=id)
        self.language = language

    def compose(self):
        yield Static("", id="events-title", markup=False)
        yield EventLog()

    @property
    def log(self) -> EventLog:
        return self.query_one(EventLog)

    def on_mount(self) -> None:
        self.log.language = self.language
        self.refresh_title()

    def refresh_title(self) -> None:
        if self.is_mounted:
            title = t("tui.events.count", self.language, n=self.log.count)
            self.query_one("#events-title", Static).update(Text(title))

    def add_event(self, event: AgentEvent) -> None:
        self.log.add_event(event)
        self.refresh_title()

    def replay(self, events: list[AgentEvent]) -> None:
        self.log.replay(events)
        self.refresh_title()

    def clear_all(self) -> None:
        self.log.clear_all()
        self.refresh_title()

    def relabel(self, language: str) -> None:
        self.language = language
        self.log.language = language
        self.refresh_title()

    @property
    def text(self) -> str:
        return self.log.text
