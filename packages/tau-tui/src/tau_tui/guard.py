"""The owner guard in the TUI (issue 113, ADR 0008): the lock screen.

:class:`GuardScreen` is an opaque ``ModalScreen``: ``TauApp.CSS`` carries its
``background: $background`` rule, because App CSS beats ``DEFAULT_CSS`` and the app's
``ModalScreen`` rule is translucent, so without it the transcript would show through. The
screen only shows what the app tells it; the app owns the guard, the watcher and the unlock
attempt (``TauApp.start_unlock``, ``TauApp.cancel_unlock``):

- Enter on an empty line unlocks, and every challenge step (``on_progress``) appears in
  ``#progress`` as it arrives; Esc cancels a running attempt; ctrl+q quits.
- A line starting with ``/`` goes to the app's command path, where only
  :data:`~tau_core.guard.ALLOWED_WHILE_LOCKED` commands run; their answers appear here.
- Anything else is not sent and stays in the field.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

from rich.text import Text
from tau_core import GuardProgress, GuardStatus, t
from tau_core.guard import guard_status_line, progress_text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.css.query import NoMatches
from textual.screen import ModalScreen
from textual.widgets import Input, Static

from tau_tui.theme import glyph, mark_ascii

if TYPE_CHECKING:
    from tau_tui.app import TauApp

LOCKED = GuardStatus(state="locked")
"""What the lock screen shows before the guard's first answer."""


class GuardScreen(ModalScreen[bool]):
    """The lock screen. It is dismissed with ``True`` once the guard reports ``unlocked``."""

    DEFAULT_CSS = """
    GuardScreen { align: center middle; }
    GuardScreen > #dialog {
        width: 64; max-width: 100%; height: auto; max-height: 100%; padding: 0 1;
        border: round $accent; background: $panel;
    }
    GuardScreen #title { text-style: bold; color: $accent; }
    GuardScreen #state { color: $text-muted; margin-bottom: 1; }
    GuardScreen #progress { text-style: bold; height: auto; }
    GuardScreen #message { color: $tau-notice; height: auto; max-height: 14; }
    GuardScreen #entry { margin-top: 1; border: none; height: 1; padding: 0 1; }
    GuardScreen #entry { background: $surface; }
    GuardScreen #hint { color: $text-muted; margin-top: 1; }
    GuardScreen.-phone #dialog { width: 100%; }
    """

    BINDINGS = [Binding("escape", "cancel_attempt", show=False)]

    def __init__(self, status: GuardStatus | None = None) -> None:
        super().__init__()
        self.status = status or LOCKED
        self.attempt = False
        self.progress_line = ""
        self.message_lines: list[str] = []
        self.shown: list[str] = []
        """Every progress step and message line shown, in order (the test oracle)."""

    @property
    def tau_app(self) -> TauApp:
        return self.app  # type: ignore[return-value]

    @property
    def language(self) -> str:
        return str(getattr(self.app, "language", "en"))

    def compose(self) -> ComposeResult:
        lang = self.language
        with Vertical(id="dialog"):
            yield Static(self._title(), id="title", markup=False)
            yield Static(self._state(), id="state", markup=False)
            yield Static("", id="progress", markup=False)
            yield Static("", id="message", markup=False)
            yield Input(placeholder=t("tui.guard.placeholder", lang), id="entry")
            yield Static(Text(t("tui.guard.hint", lang)), id="hint", markup=False)

    def on_mount(self) -> None:
        mark_ascii(self)
        self._update_texts()
        entry = self.query("#entry")
        if entry:  # empty when an unlock dismissed the screen before it mounted
            entry.first(Input).focus()

    def _title(self) -> Text:
        mark = glyph("camera") if self.attempt else glyph("lock")
        return Text(f"{mark} {t('tui.guard.title', self.language)}")

    def _state(self) -> Text:
        return Text(guard_status_line(self.status, self.language))

    def _update_texts(self) -> None:
        try:
            title = self.query_one("#title", Static)
        except NoMatches:  # not composed yet: compose and on_mount use the current state
            return
        title.update(self._title())
        self.query_one("#state", Static).update(self._state())
        progress = self.query_one("#progress", Static)
        progress.update(Text(self.progress_line))
        progress.display = bool(self.progress_line)
        message = self.query_one("#message", Static)
        message.update(Text("\n".join(self.message_lines)))
        message.display = bool(self.message_lines)

    # -- what the app tells it -------------------------------------------------------------

    def set_status(self, status: GuardStatus) -> None:
        self.status = status
        self._update_texts()

    def begin_attempt(self) -> None:
        self.attempt = True
        self.progress_line = ""
        self.message_lines = []
        self._update_texts()

    def end_attempt(self) -> None:
        self.attempt = False
        self.progress_line = ""
        self._update_texts()

    def progress(self, progress: GuardProgress) -> None:
        self.progress_line = progress_text(progress, self.language)
        self.shown.append(self.progress_line)
        self._update_texts()

    def show(self, lines: Iterable[str]) -> None:
        self.message_lines = list(lines)
        self.shown.extend(self.message_lines)
        self._update_texts()

    def relabel(self, language: str) -> None:
        try:
            entry = self.query_one("#entry", Input)
        except NoMatches:
            return
        entry.placeholder = t("tui.guard.placeholder", language)
        self.query_one("#hint", Static).update(Text(t("tui.guard.hint", language)))
        self._update_texts()

    # -- input -----------------------------------------------------------------------------

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        entry = event.input
        text = event.value.strip()
        if not text:
            entry.value = ""
            self.tau_app.start_unlock()
            return
        if text.startswith("/"):
            entry.value = ""
            await self.tau_app.run_command(text)
            return
        self.show([t("guard.prompt.not_sent", self.language)])  # the text stays in the field

    def action_cancel_attempt(self) -> None:
        self.tau_app.cancel_unlock()

    @property
    def text(self) -> str:
        parts = []
        for widget in self.query(Static):
            content = widget.content
            parts.append(getattr(content, "plain", str(content)))
        return "\n".join(parts)
