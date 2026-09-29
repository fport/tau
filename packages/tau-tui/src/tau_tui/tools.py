"""Tool-call cards and the reasoning card.

A :class:`ToolCard` is one line (dot, ``tool(args)``, badge), an optional result line under
it and a lazily mounted detail (arguments and full result in two rounded boxes). It is keyed
by ``tool_use_id`` in ``Transcript.tool_cards`` and filled from three sources that may arrive
in any order: ``ToolUseStarted``/``ToolFinished`` turn events, ``ApprovalPending`` (tier 2,
before the run) and the ``tool_call``/``approval`` agent events. ``enrich`` merges and never
downgrades a ``rejected`` status.
"""

from __future__ import annotations

import json
from typing import Any

from rich.cells import cell_len
from rich.text import Text
from tau_core import t
from textual import events
from textual.containers import HorizontalGroup, VerticalGroup
from textual.reactive import reactive
from textual.timer import Timer
from textual.widgets import Static

from tau_tui.theme import STATUS_CLASS, glyph

CALL_LIMIT = 60
DETAIL_LIMIT = 2000
FLUSH_S = 0.08
FINAL_STATUSES = frozenset({"ok", "error", "rejected"})


def clip(text: str, limit: int) -> str:
    """Clip ``text`` to ``limit`` cells with a trailing ``…``."""
    if cell_len(text) <= limit:
        return text
    out = ""
    for char in text:
        if cell_len(out + char) > limit - 1:
            break
        out += char
    return out + "…"


def format_args(arguments: dict[str, Any]) -> str:
    return ", ".join(
        f"{key}={json.dumps(value, ensure_ascii=False, default=str)}"
        for key, value in arguments.items()
    )


def call_text(tool: str, arguments: dict[str, Any] | None, *, limit: int = CALL_LIMIT) -> str:
    """``name(k=v, …)`` clipped to ``limit`` cells; ``name(…)`` while the arguments are unknown."""
    inner = "…" if arguments is None else format_args(arguments)
    return clip(f"{tool}({inner})", limit)


def detail_json(arguments: dict[str, Any] | None) -> str:
    """The expanded card's arguments: sorted, compact JSON (as the mockups and the dialog)."""
    return json.dumps(arguments or {}, ensure_ascii=False, sort_keys=True, default=str)


def first_line(text: str) -> str:
    for line in text.splitlines():
        if line.strip():
            return line.strip()
    return ""


def _plain(content: Any) -> str:
    plain = getattr(content, "plain", None)
    return plain if isinstance(plain, str) else str(content)


class ToolCard(VerticalGroup):
    """One tool call. ``status``: running | pending | ok | error | rejected."""

    DEFAULT_CSS = """
    ToolCard { height: auto; margin-top: 1; }
    ToolCard.-follows { margin-top: 0; }
    ToolCard .line { height: auto; }
    ToolCard .dot { width: 2; }
    ToolCard .call { width: 1fr; text-wrap: nowrap; text-overflow: ellipsis; }
    ToolCard .badge { width: auto; color: $text-muted; padding-left: 1; }
    ToolCard.-phone .badge { display: none; }
    ToolCard.-running .dot { color: $tau-running; }
    ToolCard.-pending .dot { color: $tau-attention; }
    ToolCard.-ok .dot { color: $tau-ok; }
    ToolCard.-error .dot { color: $tau-error; }
    ToolCard.-rejected .dot { color: $tau-rejected; }
    ToolCard .result {
        display: none; color: $text-muted; padding-left: 2; height: auto;
        text-wrap: nowrap; text-overflow: ellipsis;
    }
    ToolCard.-has-result .result { display: block; }
    ToolCard .detail { display: none; margin-left: 5; height: auto; }
    ToolCard.-expanded .detail { display: block; }
    ToolCard .detail-box { border: round $primary 35%; padding: 0 1; height: auto; }
    """

    status: reactive[str] = reactive("running", init=False)
    expanded: reactive[bool] = reactive(False, init=False)

    def __init__(
        self,
        tool_use_id: str,
        tool: str,
        tier: int | None,
        arguments: dict[str, Any] | None = None,
        *,
        show_durations: bool = True,
        language: str = "en",
        id: str | None = None,
    ) -> None:
        super().__init__(id=id, classes=STATUS_CLASS["running"])
        self.tool_use_id = tool_use_id
        self.tool = tool
        self.tier = tier
        self.arguments = dict(arguments) if arguments is not None else None
        self.show_durations = show_durations
        self.language = language
        self.approval: str | None = None
        self.duration_ms: int | None = None
        self.summary: str = ""
        self.progress_text: str = ""
        self._phone = False
        self._detail: VerticalGroup | None = None

    def compose(self):
        with HorizontalGroup(classes="line"):
            yield Static(classes="dot", markup=False)
            yield Static(classes="call", markup=False)
            yield Static(classes="badge", markup=False)
        yield Static(classes="result", markup=False)

    def on_mount(self) -> None:
        self.refresh_layout()

    def on_resize(self, event: events.Resize) -> None:
        self.refresh_layout()

    def on_click(self, event: events.Click) -> None:
        self.toggle()

    def refresh_layout(self) -> None:
        """Read the phone breakpoint from the screen and re-render the line and result."""
        try:
            phone = self.screen.has_class("-phone")
        except Exception:
            phone = False
        self._phone = phone
        self.set_class(phone, "-phone")
        self._repaint()

    # -- data --------------------------------------------------------------------------------

    def set_arguments(self, arguments: dict[str, Any] | None) -> None:
        if arguments is None:
            return
        self.arguments = dict(arguments)
        self._repaint()

    def set_pending(self) -> None:
        self.status = "pending"

    def progress(self, text: str) -> None:
        self.progress_text = first_line(text)
        self._repaint()

    def finish(self, status: str, summary: str, approval: str | None) -> None:
        if approval:
            self.approval = approval
        if summary:
            self.summary = summary
        if self.status != "rejected" or status == "rejected":
            self.status = status or "error"
        self.progress_text = ""
        self._repaint()

    def enrich(
        self,
        *,
        duration_ms: int | None = None,
        approval: str | None = None,
        summary: str | None = None,
        arguments: dict[str, Any] | None = None,
        status: str | None = None,
        tier: int | None = None,
    ) -> None:
        if duration_ms is not None:
            self.duration_ms = int(duration_ms)
        if approval:
            self.approval = approval
        if summary and not self.summary:
            self.summary = summary
        if arguments is not None:
            self.arguments = dict(arguments)
        if tier is not None and self.tier is None:
            self.tier = int(tier)
        if status and self.status != "rejected":
            # The bus relay may deliver ``running`` after the turn's ``ToolFinished`` (the
            # relay is a posted message, the turn event is consumed directly): a finished
            # card never goes back to running.
            if status in FINAL_STATUSES or self.status not in FINAL_STATUSES:
                self.status = status
        self._repaint()

    def toggle(self) -> None:
        self.expanded = not self.expanded

    # -- rendering ---------------------------------------------------------------------------

    def watch_status(self, status: str) -> None:
        for css in STATUS_CLASS.values():
            self.remove_class(css)
        self.add_class(STATUS_CLASS.get(status, STATUS_CLASS["error"]))
        if status != "pending":
            self.progress_text = ""
        self._repaint()

    def watch_expanded(self, expanded: bool) -> None:
        self.set_class(expanded, "-expanded")
        if expanded and self._detail is None and self.is_mounted:
            self._detail = VerticalGroup(classes="detail")
            self.mount(self._detail)
            self._detail.mount(
                Static(
                    Text(detail_json(self.arguments)), classes="detail-box arguments", markup=False
                ),
                Static(
                    Text(self.summary[:DETAIL_LIMIT]), classes="detail-box result-box", markup=False
                ),
            )
            self._retitle_detail()
        elif expanded and self._detail is not None:
            self._refresh_detail()

    def _retitle_detail(self) -> None:
        if self._detail is None:
            return
        boxes = list(self._detail.query(".detail-box"))
        if len(boxes) == 2:
            boxes[0].border_title = t("approval.arguments", self.language).lower()
            boxes[1].border_title = "result"

    def _refresh_detail(self) -> None:
        if self._detail is None or not self._detail.is_mounted:
            return
        boxes = list(self._detail.query(".detail-box"))
        if len(boxes) == 2:
            boxes[0].update(Text(detail_json(self.arguments)))
            boxes[1].update(Text(self.summary[:DETAIL_LIMIT]))

    @property
    def dot(self) -> str:
        return glyph("tool_run") if self.status in ("running", "pending") else glyph("tool_done")

    @property
    def call(self) -> str:
        return call_text(self.tool, self.arguments)

    @property
    def badge(self) -> str:
        parts = [f"tier {'?' if self.tier is None else self.tier}"]
        if self.approval:
            parts.append(str(self.approval))
        if self.status == "running":
            parts.append("running")
        elif self.status == "pending":
            parts.append("approval…")
        elif self.show_durations and self.duration_ms is not None:
            parts.append(f"{self.duration_ms}ms")
        return " · ".join(parts)

    @property
    def result_body(self) -> str:
        """The result line without the ``⎿`` prefix and without the phone badge."""
        if self.status == "pending":
            return f"{glyph('attention')} {t('tui.tool.waiting', self.language)}"
        if self.status == "running":
            return f"{glyph('tool_run')} {self.progress_text}" if self.progress_text else ""
        if self.status == "rejected":
            return f"{glyph('fail')} {t('tool.rejected', self.language, tool=self.tool)}"
        if self.status == "error":
            return f"{glyph('fail')} {first_line(self.summary)}".rstrip()
        return first_line(self.summary)

    @property
    def result_line(self) -> str:
        body = self.result_body
        if self._phone:
            return f"{self.badge} · {body}" if body else self.badge
        return body

    @property
    def line_text(self) -> str:
        if self._phone:
            return f"{self.dot} {self.call}"
        return f"{self.dot} {self.call} {self.badge}"

    @property
    def text(self) -> str:
        result = self.result_line
        return self.line_text + (f"\n{glyph('result')}  {result}" if result else "")

    def _repaint(self) -> None:
        if not self.is_mounted:
            return
        try:
            dot = self.query_one(".dot", Static)
            call = self.query_one(".call", Static)
            badge = self.query_one(".badge", Static)
            result = self.query_one(".result", Static)
        except Exception:
            return
        dot.update(Text(self.dot))
        call_body = self.call
        name = self.tool if call_body.startswith(self.tool) else ""
        call.update(Text.assemble((name, "bold"), (call_body[len(name) :], "dim")))
        badge.update(Text(self.badge))
        line = self.result_line
        self.set_class(bool(line), "-has-result")
        result.update(Text(f"{glyph('result')}  {line}") if line else Text(""))
        self._refresh_detail()

    def relabel(self, language: str) -> None:
        self.language = language
        self._retitle_detail()
        self._repaint()


class ReasoningCard(VerticalGroup):
    """The model's extended thinking, folded to one line: ``✻ Thought for 3s``."""

    DEFAULT_CSS = """
    ReasoningCard { height: auto; margin-top: 1; color: $text-muted; }
    ReasoningCard .detail { display: none; padding-left: 2; height: auto; }
    ReasoningCard.-expanded .detail { display: block; }
    """

    expanded: reactive[bool] = reactive(False, init=False)

    def __init__(self, *, language: str = "en", text: str = "", title: str | None = None) -> None:
        super().__init__()
        self.language = language
        self._parts: list[str] = [text] if text else []
        self._pending = False
        self._timer: Timer | None = None
        self._title = title
        self.open = title is None

    def compose(self):
        yield Static(self._line(), classes="line", markup=False)
        yield Static(Text(self.source), classes="detail", markup=False)

    def _line(self) -> Text:
        if self._title is not None:
            return Text(f"{glyph('busy')} {self._title}")
        return Text(f"{glyph('busy')} {t('tui.busy.thinking', self.language)}")

    @property
    def source(self) -> str:
        return "".join(self._parts)

    @property
    def text(self) -> str:
        line = self._line().plain
        return f"{line}\n{self.source}" if self.expanded and self.source else line

    def feed(self, text: str) -> None:
        self._parts.append(text)
        if self._timer is None and self.is_mounted:
            self._timer = self.set_timer(FLUSH_S, self._flush)

    def _flush(self) -> None:
        self._timer = None
        if self.is_mounted:
            self.query_one(".detail", Static).update(Text(self.source))

    def close(self, elapsed_s: float | None) -> None:
        """Retitle to ``Thought for Ns`` and stay collapsed."""
        if not self.open:
            return
        self.open = False
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
        if elapsed_s is None:
            self._title = t("tui.turn.thought", self.language)
        else:
            self._title = t("tui.turn.thought_for", self.language, s=format_elapsed(elapsed_s))
        if self.is_mounted:
            self.query_one(".line", Static).update(self._line())
            self.query_one(".detail", Static).update(Text(self.source))

    def toggle(self) -> None:
        self.expanded = not self.expanded

    def on_click(self, event: events.Click) -> None:
        self.toggle()

    def watch_expanded(self, expanded: bool) -> None:
        self.set_class(expanded, "-expanded")

    def relabel(self, language: str) -> None:
        self.language = language
        if self.is_mounted and self.open:
            self.query_one(".line", Static).update(self._line())


def format_elapsed(seconds: float) -> str:
    """``4s`` below a minute, else ``1m 5s``."""
    whole = max(0, int(seconds))
    if whole < 60:
        return f"{whole}s"
    return f"{whole // 60}m {whole % 60}s"
