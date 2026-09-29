"""Sessions: the listing shared with ``/sessions``, the sidebar (≥140 cols) and the picker."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, tzinfo
from typing import Any

from rich.text import Text
from tau_core import SessionStore, t
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.content import Content
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

from tau_tui.theme import glyph, mark_ascii
from tau_tui.tools import clip

LIST_LIMIT = 10
SCAN_LIMIT = 100  # empty sessions are skipped, so look further back than the list shows
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def recent_sessions(store: SessionStore | None, current: str | None) -> list[Any]:
    """Earlier sessions with messages, newest first, without the current one (10 at most).

    Identical to the terminal channel, so ``/sessions`` numbering and ``/resume n`` agree.
    """
    if store is None:
        return []
    return [
        s
        for s in store.list_sessions(limit=SCAN_LIMIT)
        if s.session_id != current and s.message_count > 0
    ][:LIST_LIMIT]


def relative_date(iso: str, now: datetime, language: str, tz: tzinfo | None = None) -> str:
    """``today 12:00`` · ``yesterday`` · ``Sep 27`` (Turkish: ``bugün`` / ``dün`` / ``27.09``)."""
    try:
        when = datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return iso or "?"
    if when.tzinfo is not None:
        when = when.astimezone(tz) if tz is not None else when.astimezone(now.tzinfo)
    reference = now.astimezone(tz) if (tz is not None and now.tzinfo is not None) else now
    days = (reference.date() - when.date()).days
    if days <= 0:
        return t("tui.sessions.today", language, time=when.strftime("%H:%M"))
    if days == 1:
        return t("tui.sessions.yesterday", language)
    if language == "tr":
        return when.strftime("%d.%m")
    return f"{MONTHS[when.month - 1]} {when.day:02d}"


def session_title(summary: Any, language: str) -> str:
    return str(getattr(summary, "title", "") or "") or t("session.untitled", language)


def format_session(
    summary: Any,
    n: int,
    language: str,
    now: datetime,
    *,
    width: int = 60,
    tz: tzinfo | None = None,
) -> str:
    """``{n:>2}  {title}  {relative date}  {N msgs}  {profile}`` clipped to ``width``."""
    title = clip(session_title(summary, language), 28)
    when = relative_date(summary.updated_at, now, language, tz)
    msgs = t("tui.sessions.msgs", language, n=summary.message_count)
    line = f"{n:>2}  {title:<28}  {when:<12}  {msgs:>8}  {summary.profile}"
    return clip(line, width)


class SessionSidebar(Vertical):
    """Read-only list of recent sessions (≥140 cols); a click resumes."""

    SCOPED_CSS = False
    DEFAULT_CSS = """
    SessionSidebar {
        display: none; width: 28; border-right: solid $primary 35%; background: $panel;
        padding: 0 1;
    }
    Screen.-ultra SessionSidebar { display: block; }
    SessionSidebar #sidebar-title { height: 1; text-style: bold; }
    SessionSidebar #sidebar-list { height: 1fr; background: $panel; scrollbar-size-vertical: 1; }
    SessionSidebar #sidebar-hint { dock: bottom; height: 1; color: $text-muted; }
    """

    class Picked(Message):
        def __init__(self, session_id: str) -> None:
            super().__init__()
            self.session_id = session_id

    class List(OptionList, can_focus=False):
        pass

    def __init__(self, language: str = "en", *, id: str | None = "sidebar") -> None:
        super().__init__(id=id)
        self.language = language

    def compose(self) -> ComposeResult:
        yield Static(t("tui.sessions.title", self.language), id="sidebar-title", markup=False)
        yield self.List(id="sidebar-list", compact=True)
        yield Static(t("tui.sessions.sidebar_hint", self.language), id="sidebar-hint", markup=False)

    def refresh_list(
        self,
        store: SessionStore | None,
        current: str | None,
        now: datetime,
        *,
        tz: tzinfo | None = None,
    ) -> None:
        options: list[Option] = []
        listing = self.query_one("#sidebar-list", OptionList)
        if store is None:
            listing.clear_options()
            return
        try:
            current_summary = next(
                (s for s in store.list_sessions(limit=SCAN_LIMIT) if s.session_id == current), None
            )
            recent = recent_sessions(store, current)
        except Exception:
            listing.clear_options()
            return
        rows = ([current_summary] if current_summary is not None else []) + recent
        for summary in rows:
            marker = glyph("notice") if summary.session_id == current else " "
            title = clip(session_title(summary, self.language), 22)
            when = relative_date(summary.updated_at, now, self.language, tz)
            msgs = t("tui.sessions.msgs", self.language, n=summary.message_count)
            options.append(
                Option(
                    Content.assemble(
                        (f"{marker} ", "bold" if marker != " " else ""),
                        (title, "bold"),
                        "\n  ",
                        (f"{when} · {msgs}", "dim"),
                    ),
                    id=summary.session_id,
                )
            )
        listing.clear_options()
        listing.add_options(options)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        if event.option_id:
            self.post_message(self.Picked(event.option_id))

    def relabel(self, language: str) -> None:
        self.language = language
        self.query_one("#sidebar-title", Static).update(t("tui.sessions.title", language))
        self.query_one("#sidebar-hint", Static).update(t("tui.sessions.sidebar_hint", language))

    @property
    def text(self) -> str:
        listing = self.query_one("#sidebar-list", OptionList)
        rows = [str(listing.get_option_at_index(i).prompt) for i in range(listing.option_count)]
        return "\n".join(rows)


class SessionPicker(ModalScreen[str | None]):
    """``ctrl+r`` / F2: Enter resumes the highlighted session, ``n`` starts a new one."""

    DEFAULT_CSS = """
    SessionPicker { align: center middle; }
    SessionPicker #dialog {
        width: 68; max-width: 100%; height: auto; max-height: 100%; padding: 0 1;
        border: round $accent; background: $panel;
    }
    SessionPicker #title { text-style: bold; color: $accent; margin-bottom: 1; }
    SessionPicker #list { height: auto; max-height: 12; background: $panel; }
    SessionPicker #picker-hint { margin-top: 1; color: $text-muted; }
    SessionPicker.-phone #dialog { width: 100%; }
    """

    BINDINGS = [
        Binding("escape", "close", show=False),
        Binding("n", "new", show=False),
    ]

    def __init__(
        self,
        sessions: list[Any],
        *,
        language: str = "en",
        now: Callable[[], datetime] | None = None,
        tz: tzinfo | None = None,
    ) -> None:
        super().__init__()
        self.sessions = sessions
        self.language = language
        self.now = now or datetime.now
        self.tz = tz

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static(
                Text(f"{glyph('attention')} {t('tui.sessions.title', self.language)}"),
                id="title",
                markup=False,
            )
            # Titles are the user's own words: never parsed as markup (``[/x]`` would raise).
            yield OptionList(id="list", compact=True, markup=False)
            yield Static(
                Text(t("tui.sessions.hint", self.language)), id="picker-hint", markup=False
            )

    @property
    def scroll_target(self) -> OptionList:
        return self.query_one("#list", OptionList)

    def on_mount(self) -> None:
        mark_ascii(self)
        self.render_rows()
        listing = self.query_one("#list", OptionList)
        listing.focus()
        if self.sessions:
            listing.highlighted = 0

    def render_rows(self) -> None:
        listing = self.query_one("#list", OptionList)
        listing.clear_options()
        now = self.now()
        rows = []
        for n, summary in enumerate(self.sessions, start=1):
            marker = glyph("notice") if n == 1 else " "
            line = format_session(summary, n, self.language, now, width=62, tz=self.tz)
            rows.append(Option(f"{marker} {line}", id=summary.session_id))
        if not rows:
            rows.append(Option(t("session.none_earlier", self.language), disabled=True))
        listing.add_options(rows)
        self.query_one("#title", Static).update(
            Text(f"{glyph('attention')} {t('tui.sessions.title', self.language)}")
        )
        self.query_one("#picker-hint", Static).update(Text(t("tui.sessions.hint", self.language)))

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        if event.option_id:
            self.dismiss(event.option_id)

    def action_close(self) -> None:
        self.dismiss(None)

    def action_new(self) -> None:
        self.dismiss("")

    def relabel(self, language: str) -> None:
        self.language = language
        self.render_rows()
