"""The transcript: turns made of rows, reply blocks, tool cards, notices and footers.

Every widget owns its ``DEFAULT_CSS``, talks through reactives and methods and has a ``text``
oracle for the tests. :class:`Transcript` is a bottom-anchored ``VerticalScroll``; the app is
the only wiring point (it feeds the current :class:`Turn` from ``TauAgent.stream()`` and
enriches cards from the event bus).
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from time import perf_counter
from typing import Any, Protocol, runtime_checkable

from rich.text import Text
from tau_core import ToolFinished, ToolUseStarted, t
from textual import events
from textual.containers import HorizontalGroup, VerticalGroup, VerticalScroll
from textual.widget import Widget
from textual.widgets import Markdown, Static

from tau_tui.brand import LOGO_COLS, LOGO_COLS_PHONE, mark_text
from tau_tui.history import (
    HAssistant,
    HistoryItem,
    HThinking,
    HTool,
    HUser,
    group_turns,
)
from tau_tui.theme import glyph
from tau_tui.tools import ReasoningCard, ToolCard, format_elapsed

LIVE_TURNS = 40
PAGE_TURNS = 20
STREAM_MODES = ("auto", "live", "plain")


@runtime_checkable
class Localized(Protocol):
    def relabel(self, language: str) -> None: ...


def plain_text(content: Any) -> str:
    plain = getattr(content, "plain", None)
    return plain if isinstance(plain, str) else str(content)


def widget_text(widget: Widget) -> str:
    """The plain text of a widget subtree in DOM order (the tests' oracle)."""
    if isinstance(widget, ReplyBlock):
        return widget.source
    if isinstance(widget, ToolCard | ReasoningCard | UserRow | WelcomeCard):
        return widget.text
    if isinstance(widget, Markdown):
        return widget.source
    if isinstance(widget, Static):
        return plain_text(widget.content)
    parts = [widget_text(child) for child in widget.children]
    return "\n".join(part for part in parts if part)


def sanitise_id(tool_use_id: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in tool_use_id)


def mark_follows(widget: Widget, previous: Widget | None) -> None:
    """Consecutive tool cards sit on adjacent rows (TCSS has no ``+`` combinator)."""
    if isinstance(widget, ToolCard) and isinstance(previous, ToolCard):
        widget.add_class("-follows")


# -- rows ---------------------------------------------------------------------------------------


class UserRow(HorizontalGroup):
    DEFAULT_CSS = """
    UserRow { height: auto; margin-top: 1; }
    UserRow .gutter { width: 2; color: $tau-user; text-style: bold; }
    UserRow .body { width: 1fr; height: auto; }
    """

    def __init__(self, text: str) -> None:
        super().__init__(classes="user")
        self.body_text = text

    def compose(self):
        yield Static(Text(glyph("user")), classes="gutter", markup=False)
        yield Static(Text(self.body_text), classes="body", markup=False)

    @property
    def text(self) -> str:
        return f"{glyph('user')} {self.body_text}"


class ReplyMarkdown(Markdown):
    BULLETS = ["• ", "◦ ", "▪ ", "‣ "]  # never ●, the tool dot


class ReplyBlock(HorizontalGroup):
    """One assistant text segment. ``mode``: ``live`` (MarkdownStream) or ``plain`` (draft)."""

    DEFAULT_CSS = """
    ReplyBlock { height: auto; margin-top: 1; }
    ReplyBlock .gutter { width: 2; color: $primary; }
    ReplyBlock .body { width: 1fr; height: auto; }
    ReplyBlock Markdown { padding: 0; margin: 0; background: transparent; }
    ReplyBlock MarkdownFence {
        margin: 1 0; background: $surface; border-left: heavy $primary 50%; overflow-x: hidden;
    }
    ReplyBlock MarkdownFence > Label { padding: 0 1; }
    ReplyBlock MarkdownH1, ReplyBlock MarkdownH2 { background: transparent; text-style: bold; }
    ReplyBlock MarkdownBlock:last-child { margin-bottom: 0; }
    ReplyBlock .draft { color: $text; height: auto; }
    """

    FLUSH_S, DEGRADE_MS, DEGRADE_STRIKES = 0.08, 80, 2

    def __init__(self, *, mode: str = "live", markdown: str = "") -> None:
        super().__init__(classes="reply")
        self.mode = mode if mode in ("live", "plain") else "live"
        self._text: list[str] = [markdown] if markdown else []
        self._pending: list[str] = []
        self._flush_timer = None
        self._stream = None
        self._slow = 0
        self.md = ReplyMarkdown(markdown, open_links=False, classes="md")
        self.draft: Static | None = None
        self.closed = False

    def compose(self):
        yield Static(Text(glyph("tau")), classes="gutter", markup=False)
        with VerticalGroup(classes="body"):
            yield self.md

    @property
    def body(self) -> VerticalGroup:
        return self.query_one(".body", VerticalGroup)

    @property
    def source(self) -> str:
        return "".join(self._text)

    async def feed(self, delta: str) -> None:
        if not delta:
            return
        self._text.append(delta)
        self._pending.append(delta)
        if self._flush_timer is None:
            self._flush_timer = self.set_timer(self.FLUSH_S, self._flush)

    async def _flush(self) -> None:
        chunk, self._pending, self._flush_timer = "".join(self._pending), [], None
        if not chunk:
            return
        if self.mode == "live":
            if self._stream is None:
                self._stream = Markdown.get_stream(self.md)
            t0 = perf_counter()
            await self._stream.write(chunk)
            if (perf_counter() - t0) * 1000 > self.DEGRADE_MS:
                self._slow += 1
            else:
                self._slow = 0
            if self._slow >= self.DEGRADE_STRIKES:
                await self._degrade()
        else:
            await self._ensure_draft()
            assert self.draft is not None
            self.draft.update(Text(self.source))  # markup never parsed

    async def _ensure_draft(self) -> None:
        if self.draft is None:
            self.draft = Static(Text(self.source), classes="draft", markup=False)
            self.md.display = False
            await self.body.mount(self.draft, before=self.md)

    async def _degrade(self) -> None:
        """live → plain for the rest of this block (a long open fence made appends slow)."""
        if self._stream is not None:
            await self._stream.stop()
            self._stream = None
        self.mode = "plain"
        await self._ensure_draft()

    async def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        if self._flush_timer is not None:
            self._flush_timer.stop()
            self._flush_timer = None
        if self._pending:
            await self._flush()
        if self._stream is not None:
            await self._stream.stop()
            self._stream = None
        if self.mode == "plain":
            await self.md.update(self.source)
            self.md.display = True
            if self.draft is not None:
                await self.draft.remove()
                self.draft = None


class BusyRow(Static):
    """``✻ verb…`` — the last row of the running turn. No spinner, no ticker."""

    DEFAULT_CSS = """
    BusyRow { color: $accent; height: 1; margin-top: 1; }
    """

    def __init__(self, key: str, language: str, **kwargs: object) -> None:
        super().__init__(markup=False, classes="busy")
        self.key, self.kwargs, self.language = key, kwargs, language
        self.update(self._render_text())

    def _render_text(self) -> Text:
        return Text(f"{glyph('busy')} {t(self.key, self.language, **self.kwargs)}")

    def set_verb(self, key: str, **kwargs: object) -> None:
        self.key, self.kwargs = key, kwargs
        self.update(self._render_text())

    def relabel(self, language: str) -> None:
        self.language = language
        self.update(self._render_text())

    @property
    def text(self) -> str:
        return self._render_text().plain


class NoticeRow(Static):
    DEFAULT_CSS = """
    NoticeRow { color: $tau-notice; text-style: italic; height: auto; margin-top: 1; }
    """

    def __init__(self, text: str) -> None:
        super().__init__(Text(f"{glyph('notice')} {text}"), markup=False, classes="notice")


class InfoCard(Static):
    DEFAULT_CSS = """
    InfoCard { color: $text-muted; padding-left: 2; height: auto; margin-top: 1; }
    """

    def __init__(self, lines: Iterable[str]) -> None:
        super().__init__(Text("\n".join(lines)), markup=False, classes="info")


class TurnFooter(Static):
    DEFAULT_CSS = """
    TurnFooter { color: $text-muted; height: 1; margin-top: 1; }
    """

    def __init__(self, text: Text) -> None:
        super().__init__(text, markup=False, classes="footer")


class HistoryFold(Static):
    DEFAULT_CSS = """
    HistoryFold { color: $text-muted; text-style: italic; height: 1; }
    """

    def __init__(self, n: int, language: str) -> None:
        super().__init__(markup=False, id="fold")
        self.n, self.language = n, language
        self.update(Text(t("tui.fold", language, n=n)))

    def set_count(self, n: int) -> None:
        self.n = n
        self.update(Text(t("tui.fold", self.language, n=n)))

    def relabel(self, language: str) -> None:
        self.language = language
        self.set_count(self.n)


@dataclass
class WelcomeFacts:
    version: str
    profile: str
    session_id: str
    role: str
    provider: str
    tools: int
    approval_tools: int


class WelcomeCard(Widget):
    """The empty-session card: the rasterised mark and the facts of this run."""

    SCOPED_CSS = False  # the breakpoint rules start with Screen.-x
    DEFAULT_CSS = """
    WelcomeCard {
        border: round $primary 45%; padding: 1 1; height: auto; layout: horizontal;
    }
    WelcomeCard .mark { width: 24; height: auto; margin: 0 2 0 5; }
    WelcomeCard .mark-phone { display: none; }
    WelcomeCard .facts { width: 1fr; height: auto; }
    Screen.-phone WelcomeCard { layout: vertical; }
    Screen.-phone WelcomeCard .mark-wide { display: none; }
    Screen.-phone WelcomeCard .mark-phone { display: block; width: 16; margin: 0 0 1 0; }
    Screen.-short WelcomeCard .mark { display: none; }
    """

    def __init__(self, facts: WelcomeFacts, language: str) -> None:
        super().__init__(id="welcome")
        self.facts = facts
        self.language = language
        self._phone = False

    def compose(self):
        yield Static(mark_text(LOGO_COLS), classes="mark mark-wide", markup=False)
        yield Static(mark_text(LOGO_COLS_PHONE), classes="mark mark-phone", markup=False)
        yield Static(self._facts_text(), classes="facts", markup=False)

    def on_mount(self) -> None:
        self._refresh()

    def on_resize(self, event: events.Resize) -> None:
        self._refresh()

    def _refresh(self) -> None:
        try:
            self._phone = self.screen.has_class("-phone")
        except Exception:
            self._phone = False
        if self.is_mounted:
            self.query_one(".facts", Static).update(self._facts_text())
            # Centre the phone mark by hand: ``align`` centres the whole child group.
            mark = self.query_one(".mark-phone", Static)
            inner = max(self.content_size.width, LOGO_COLS_PHONE)
            mark.styles.margin = (0, 0, 1, (inner - LOGO_COLS_PHONE) // 2)

    def _facts_text(self) -> Text:
        f, lang = self.facts, self.language
        labels = [
            (t("tui.welcome.profile", lang), f.profile),
            (t("tui.welcome.session", lang), f.session_id),
            (t("tui.welcome.model", lang), f"{f.role} → {f.provider}"),
            (
                t("tui.welcome.tools", lang),
                t("tui.welcome.tools_value", lang, n=f.tools, approval=f.approval_tools),
            ),
        ]
        width = max(len(label) for label, _ in labels) + 4
        text = Text()
        text.append("tau ", style="bold")
        text.append(f.version, style="dim")
        text.append("\n" + t("tui.welcome.tagline", lang))
        if not self._phone:
            text.append("\n")
        for label, value in labels:
            text.append("\n")
            text.append(f"{label:<{width}}", style="dim")
            text.append(value)
        if not self._phone:
            text.append("\n\n" + t("tui.welcome.tip", lang), style="dim")
            text.append("\n" + t("tui.welcome.tier_tip", lang), style="dim")
        return text

    @property
    def text(self) -> str:
        return self._facts_text().plain

    def relabel(self, language: str) -> None:
        self.language = language
        self._refresh()


# -- turns --------------------------------------------------------------------------------------


class Turn(VerticalGroup):
    """One user turn: user row, then reply segments, tool cards, notices, busy row, footer."""

    DEFAULT_CSS = """
    Turn { height: auto; }
    """

    def __init__(self, number: int, prompt: str | None, *, children: Iterable[Widget] = ()) -> None:
        super().__init__(id=f"turn-{number}", classes="turn")
        self.number = number
        self.prompt = prompt
        self.running = False
        self.busy_row: BusyRow | None = None
        self.reply: ReplyBlock | None = None
        self.reasoning: ReasoningCard | None = None
        self._reasoning_started: datetime | None = None
        self.footer: TurnFooter | None = None
        self._footer_args: tuple[str, float] | None = None
        self.tool_count = 0
        self._initial = list(children)

    def compose(self):
        yield from self._initial

    @property
    def transcript(self) -> Transcript:
        for node in self.ancestors:
            if isinstance(node, Transcript):
                return node
        raise LookupError("Turn is not inside a Transcript")

    @property
    def language(self) -> str:
        return self.transcript.language

    async def begin(self) -> None:
        self.running = True
        if self.prompt is not None:
            await self.mount(UserRow(self.prompt))
        await self.set_busy("tui.busy.thinking")

    async def place(self, widget: Widget) -> None:
        """Mount ``widget`` above the busy row so the busy row stays last."""
        mark_follows(widget, self.last_content)
        if self.busy_row is not None and self.busy_row.is_mounted:
            await self.mount(widget, before=self.busy_row)
        else:
            await self.mount(widget)

    @property
    def last_content(self) -> Widget | None:
        """The last child that is not the busy row."""
        for child in reversed(list(self.children)):
            if child is not self.busy_row:
                return child
        return None

    async def set_busy(self, key: str, **kwargs: object) -> None:
        if self.busy_row is None or not self.busy_row.is_mounted:
            self.busy_row = BusyRow(key, self.language, **kwargs)
            await self.mount(self.busy_row)
        else:
            self.busy_row.set_verb(key, **kwargs)

    async def clear_busy(self) -> None:
        if self.busy_row is not None and self.busy_row.is_mounted:
            await self.busy_row.remove()
        self.busy_row = None

    async def _close_reasoning(self) -> None:
        if self.reasoning is not None and self.reasoning.open:
            elapsed = None
            if self._reasoning_started is not None:
                elapsed = (self.transcript.clock() - self._reasoning_started).total_seconds()
            self.reasoning.close(elapsed)

    async def _close_reply(self) -> None:
        if self.reply is not None:
            await self.reply.close()
            self.reply = None

    async def feed_text(self, text: str) -> None:
        await self._close_reasoning()
        if self.reply is None:
            self.reply = ReplyBlock(mode=self.transcript.current_stream_mode())
            await self.place(self.reply)
        await self.clear_busy()
        await self.reply.feed(text)

    async def feed_reasoning(self, text: str) -> None:
        if self.reasoning is None or not self.reasoning.open:
            self.reasoning = ReasoningCard(language=self.language)
            self._reasoning_started = self.transcript.clock()
            await self._close_reply()
            await self.place(self.reasoning)
        self.reasoning.feed(text)

    async def add_tool(self, event: ToolUseStarted) -> ToolCard:
        await self._close_reasoning()
        await self._close_reply()
        card = self.transcript.new_card(event.tool_use_id, event.tool, event.tier)
        await self.place(card)
        self.tool_count += 1
        return card

    def tool_progress(self, tool_use_id: str, tool: str, text: str) -> None:
        card = self.transcript.tool_cards.get(tool_use_id)
        if card is not None:
            card.progress(text)

    async def finish_tool(self, event: ToolFinished) -> None:
        card = self.transcript.tool_cards.get(event.tool_use_id)
        if card is None:  # orphan: a finish for a call this turn never announced
            card = await self.add_tool(ToolUseStarted(event.tool_use_id, event.tool, None))
        card.finish(event.status, event.summary, event.approval)

    async def add_notice(self, text: str) -> None:
        await self._close_reply()
        await self.place(NoticeRow(text))

    async def end(self, stop_reason: str, *, elapsed: float) -> None:
        await self._close_reply()
        await self._close_reasoning()
        await self.clear_busy()
        self.running = False
        has_cards = bool(self.cards)
        if not (has_cards or elapsed >= 5 or stop_reason != "end_turn"):
            return
        self._footer_args = (stop_reason, elapsed)
        self.footer = TurnFooter(self.footer_text(stop_reason, elapsed))
        await self.mount(self.footer)

    def footer_text(self, stop_reason: str, elapsed: float) -> Text:
        lang = self.language
        worked = t("tui.turn.worked_for", lang, s=format_elapsed(elapsed))
        parts: list[str] = []
        if stop_reason == "end_turn":
            mark, style = glyph("ok"), "tau-ok"
            parts.append(worked)
        else:
            mark = glyph("fail") if stop_reason == "error" else glyph("attention")
            style = "tau-error" if stop_reason == "error" else "tau-attention"
            key = f"tui.turn.stop.{stop_reason}"
            try:
                parts.append(t(key, lang))
            except KeyError:
                parts.append(stop_reason)
            parts.append(worked[:1].lower() + worked[1:])
        if self.tool_count == 1:
            parts.append(t("tui.turn.tools_one", lang))
        elif self.tool_count > 1:
            parts.append(t("tui.turn.tools", lang, n=self.tool_count))
        if self.cards:
            key = "tui.turn.collapse_hint" if self.expanded else "tui.turn.expand_hint"
            parts.append(t(key, lang))
        colour = {"tau-ok": "#FFB25C", "tau-error": "#FF2E63", "tau-attention": "#FFB25C"}[style]
        return Text.assemble((mark, colour), " " + " · ".join(parts))

    @property
    def cards(self) -> list[ToolCard | ReasoningCard]:
        return [c for c in self.children if isinstance(c, ToolCard | ReasoningCard)]

    @property
    def expanded(self) -> bool:
        cards = self.cards
        return bool(cards) and cards[0].expanded

    def toggle_cards(self) -> None:
        cards = self.cards
        if not cards:
            return
        target = not cards[0].expanded
        for card in cards:
            card.expanded = target
        if self.footer is not None and self.footer.is_mounted and self._footer_args:
            self.footer.update(self.footer_text(*self._footer_args))

    @property
    def text(self) -> str:
        return widget_text(self)


# -- the transcript -------------------------------------------------------------------------------


class Transcript(VerticalScroll, can_focus=False):
    """Bottom-anchored scroll of turns. ``language``, ``show_durations``, ``stream_mode`` and
    ``clock`` are set by the app; children read them through :attr:`Turn.transcript`."""

    SCOPED_CSS = False
    DEFAULT_CSS = """
    Transcript { width: 1fr; height: 1fr; padding: 0 1; scrollbar-size-vertical: 1; }
    Screen.-ultra Transcript > * { max-width: 110; }
    """

    def __init__(self, *, id: str | None = "transcript") -> None:
        super().__init__(id=id)
        self.language = "en"
        self.show_durations = True
        self.stream_mode = "auto"
        self.clock: Callable[[], datetime] = datetime.now
        self.tool_cards: dict[str, ToolCard] = {}
        self._turn_counter = 0
        self.folded = 0
        self.history_provider: Callable[[], list[HistoryItem]] | None = None
        self._history_turns: list[list[HistoryItem]] = []

    def on_mount(self) -> None:
        self.anchor()

    def arrange(self, size):  # type: ignore[override]
        # Textual 8.2.8 anchors with ``scroll_y = content bottom - container height`` without
        # clamping, so an anchored container whose content is shorter than the viewport is
        # drawn shifted down by the difference. Release the anchor while the content fits and
        # restore it (our own release, not the user's) as soon as it overflows.
        result = super().arrange(size)
        if self._anchored:
            fits = result.spatial_map.total_region.bottom <= size.height
            if fits:
                if not self._anchor_released:
                    self._anchor_released = True
                    self._fit_released = True
            elif self._fit_released:
                self._anchor_released = False
                self._fit_released = False
        return result

    _fit_released = False

    @property
    def text(self) -> str:
        return widget_text(self)

    @property
    def turns(self) -> list[Turn]:
        return [c for c in self.children if isinstance(c, Turn)]

    @property
    def current_turn(self) -> Turn | None:
        turns = self.turns
        return turns[-1] if turns and turns[-1].running else None

    @property
    def last_turn(self) -> Turn | None:
        turns = self.turns
        return turns[-1] if turns else None

    def current_stream_mode(self) -> str:
        if os.environ.get("TAU_TUI_PLAIN_STREAM", "") not in ("", "0"):
            return "plain"
        if self.stream_mode in ("live", "plain"):
            return self.stream_mode
        try:
            return "plain" if self.screen.has_class("-phone") else "live"
        except Exception:
            return "live"

    def new_card(
        self, tool_use_id: str, tool: str, tier: int | None, arguments: dict | None = None
    ) -> ToolCard:
        card = ToolCard(
            tool_use_id,
            tool,
            tier,
            arguments,
            show_durations=self.show_durations,
            language=self.language,
            id=f"tool-{sanitise_id(tool_use_id)}" if tool_use_id else None,
        )
        if tool_use_id:
            self.tool_cards[tool_use_id] = card
        return card

    def _next_turn(self, prompt: str | None) -> Turn:
        self._turn_counter += 1
        return Turn(self._turn_counter, prompt)

    async def begin_turn(self, prompt: str) -> Turn:
        await self.remove_welcome()
        turn = self._next_turn(prompt)
        await self.mount(turn)
        await turn.begin()
        return turn

    async def remove_welcome(self) -> None:
        for card in self.query(WelcomeCard):
            await card.remove()

    async def show_welcome(self, facts: WelcomeFacts) -> None:
        await self.remove_welcome()
        await self.mount(WelcomeCard(facts, self.language), before=0)

    async def add_notice(self, text: str) -> None:
        await self.mount(NoticeRow(text))

    async def add_info(self, lines: Iterable[str]) -> None:
        await self.mount(InfoCard(lines))

    async def reset(self) -> None:
        await self.remove_children()
        self.tool_cards.clear()
        self.folded = 0
        self._history_turns = []

    # -- enrichment from the event bus ---------------------------------------------------

    async def enrich(self, event: Any) -> None:
        data = event.data
        if event.kind == "tool_call":
            tool_use_id = str(data.get("tool_use_id") or "")
            card = self.tool_cards.get(tool_use_id)
            if card is None:
                if not tool_use_id:
                    return
                card = self.new_card(tool_use_id, str(data.get("tool") or "?"), data.get("tier"))
                turn = self.current_turn or self.last_turn
                if turn is not None:
                    await turn.place(card)
                    turn.tool_count += 1
                else:
                    await self.mount(card)
            card.enrich(
                duration_ms=data.get("duration_ms"),
                approval=data.get("approval"),
                summary=data.get("result_summary"),
                arguments=data.get("arguments"),
                status=data.get("status"),
                tier=data.get("tier"),
            )
        elif event.kind == "approval":
            card = self.match_pending(str(data.get("tool") or ""))
            if card is not None:
                card.enrich(arguments=data.get("arguments"), approval=data.get("decision"))
                if card.status == "pending":
                    card.status = "running"

    def match_pending(self, tool: str) -> ToolCard | None:
        """The newest running/pending card of ``tool`` (approval events carry no id)."""
        for card in reversed(list(self.tool_cards.values())):
            if card.tool == tool and card.status in ("running", "pending"):
                return card
        return None

    # -- expand / collapse ------------------------------------------------------------------

    def toggle_last_turn(self) -> None:
        turn = self.last_turn
        if turn is not None:
            turn.toggle_cards()

    # -- history ---------------------------------------------------------------------------

    async def load_history(self, items: list[HistoryItem]) -> None:
        await self.remove_welcome()  # a session with messages never shows the welcome card
        turns = group_turns(items)
        self._history_turns = turns
        live = turns[-LIVE_TURNS:]
        self.folded = len(turns) - len(live)
        if self.folded:
            await self.mount(HistoryFold(self.folded, self.language))
        for turn_items in live:
            await self.mount(self._history_turn(turn_items))
        self.scroll_end(animate=False)

    def _history_turn(self, turn_items: list[HistoryItem]) -> Turn:
        prompt = turn_items[0].text if isinstance(turn_items[0], HUser) else None
        children: list[Widget] = []
        tool_count = 0
        if prompt is not None:
            children.append(UserRow(prompt))
        for item in turn_items[1 if prompt is not None else 0 :]:
            if isinstance(item, HUser):
                children.append(UserRow(item.text))
            elif isinstance(item, HAssistant):
                children.append(ReplyBlock(mode="plain", markdown=item.markdown))
            elif isinstance(item, HThinking):
                card = ReasoningCard(
                    language=self.language,
                    text=item.text,
                    title=t("tui.turn.thought", self.language),
                )
                children.append(card)
            elif isinstance(item, HTool):
                card = self.new_card(item.tool_use_id, item.tool, item.tier, item.arguments)
                card.duration_ms = item.duration_ms
                card.approval = item.approval
                card.summary = item.result_text
                card.status = item.status or "error"
                mark_follows(card, children[-1] if children else None)
                children.append(card)
                tool_count += 1
        self._turn_counter += 1
        turn = Turn(self._turn_counter, prompt, children=children)
        turn.tool_count = tool_count
        return turn

    async def page_older(self, n: int = PAGE_TURNS) -> bool:
        """Mount ``n`` more folded turns after the fold; ``True`` when something was mounted."""
        if not self.folded:
            return False
        if self.history_provider is not None:
            self._history_turns = group_turns(self.history_provider())
        fold = self.query(HistoryFold).first() if self.query(HistoryFold) else None
        start = max(self.folded - n, 0)
        page = self._history_turns[start : self.folded]
        anchor: Widget | None = fold
        for turn_items in page:
            turn = self._history_turn(turn_items)
            if anchor is not None:
                await self.mount(turn, after=anchor)
            else:
                await self.mount(turn, before=0)
            anchor = turn
        self.folded = start
        if fold is not None:
            if self.folded:
                fold.set_count(self.folded)
            else:
                await fold.remove()
        return True

    def trim(self) -> None:
        """Keep the last ``LIVE_TURNS`` turns live; older ones join the fold."""
        turns = self.turns
        extra = len(turns) - LIVE_TURNS
        if extra <= 0:
            return
        for turn in turns[:extra]:
            for card in turn.query(ToolCard):
                self.tool_cards.pop(card.tool_use_id, None)
            turn.remove()
        self.folded += extra
        folds = list(self.query(HistoryFold))
        if folds:
            folds[0].set_count(self.folded)
        else:
            self.mount(HistoryFold(self.folded, self.language), before=0)

    def relabel(self, language: str) -> None:
        self.language = language
        for widget in self.query("*"):
            if isinstance(widget, Localized) and widget is not self:
                widget.relabel(language)
