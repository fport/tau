"""The composer (multi-line prompt with a caret), the in-flow command menu and the hint bar.

Enter sends, ``ctrl+j`` inserts a newline (shift+enter too where the terminal delivers it),
``/`` in an empty composer opens :class:`CommandMenu` above it, ``?`` in an empty composer asks
for help. The menu never takes focus: ``PromptArea._on_key`` forwards up/down/tab/enter to it
while it is open.
"""

from __future__ import annotations

import re
from collections import deque
from typing import ClassVar

from rich.text import Text
from tau_core import SLASH_COMMANDS, SlashCommand, resolve_command, t
from textual import events
from textual.containers import HorizontalGroup, Vertical
from textual.content import Content
from textual.fuzzy import Matcher
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import OptionList, Static, TextArea
from textual.widgets.option_list import Option

from tau_tui.keys import hints_for
from tau_tui.theme import glyph
from tau_tui.tools import clip

HISTORY_SIZE = 50
MENU_PATTERN = re.compile(r"^/\S*$")


def usage(command: SlashCommand) -> str:
    return f"/{command.name}" + (f" {command.argument}" if command.argument else "")


class CommandMenu(OptionList, can_focus=False):
    """Fuzzy list of the slash commands, shown while the composer holds ``/…`` alone.

    Heights are border-box: ``max-height`` is the twelve command rows plus the two border rows,
    so every row is on screen at 80x24 (the transcript keeps five rows and its bottom). In the
    ``-short`` band the list scrolls instead of eating the whole screen.
    """

    SCOPED_CSS = False  # the -short rule starts with Screen
    DEFAULT_CSS = """
    CommandMenu {
        display: none; height: auto; max-height: 14; margin: 0 1;
        border: round $primary 60%; background: $panel; padding: 0;
    }
    Screen.-short CommandMenu { max-height: 8; }
    CommandMenu.-open { display: block; }
    CommandMenu > .option-list--option { padding: 0 1; }
    CommandMenu > .option-list--option-highlighted {
        color: $block-cursor-foreground; background: $block-cursor-background;
    }
    """

    def __init__(self, language: str = "en", *, id: str | None = "menu") -> None:
        super().__init__(id=id)
        self.language = language
        self.commands: list[SlashCommand] = []
        self.open = False

    def set_query(self, query: str) -> bool:
        """Show the commands matching ``query`` (``/`` alone → all); ``False`` closes it."""
        name = query.lstrip("/")
        if name:
            matcher = Matcher(name)
            typed = name.casefold()
            scored = [
                (cmd.name != typed, -matcher.match(cmd.name), i, cmd)
                for i, cmd in enumerate(SLASH_COMMANDS)
            ]  # an exact name first, then the fuzzy score, then the table order
            ordered = [cmd for _, score, _, cmd in sorted(scored) if score < 0]
        else:
            ordered = list(SLASH_COMMANDS)
        if not ordered:
            self.close()
            return False
        self.commands = ordered
        self.clear_options()
        try:
            width = self.screen.size.width
        except Exception:
            width = 80
        help_width = max(10, width - 2 - 2 - 2 - 18)  # margin, border, padding, usage column
        self.add_options(
            [
                Option(
                    Content.assemble(
                        (usage(cmd).ljust(18), "bold"),
                        (clip(t(cmd.help_key, self.language), help_width), "dim"),
                    ),
                    id=cmd.name,
                )
                for cmd in ordered
            ]
        )
        self.highlighted = 0
        self.open = True
        self.add_class("-open")
        return True

    def close(self) -> None:
        if self.open:
            self.open = False
            self.remove_class("-open")
            self.clear_options()
            self.commands = []

    @property
    def highlighted_command(self) -> SlashCommand | None:
        if not self.open or self.highlighted is None or self.highlighted >= len(self.commands):
            return None
        return self.commands[self.highlighted]

    def relabel(self, language: str) -> None:
        self.language = language
        if self.open:
            names = [cmd.name for cmd in self.commands]
            highlighted = self.highlighted
            self.set_query("/")
            self.commands = [cmd for cmd in SLASH_COMMANDS if cmd.name in names]
            self.highlighted = highlighted


class PromptArea(TextArea):
    """The text area of the composer; Enter sends, the menu keys are forwarded."""

    SCOPED_CSS = False
    DEFAULT_CSS = """
    PromptArea { height: auto; max-height: 5; background: transparent; border: none; padding: 0; }
    Screen.-phone PromptArea { max-height: 3; }
    """

    def __init__(self, placeholder: str = "", *, id: str | None = "prompt") -> None:
        super().__init__(
            "",
            soft_wrap=True,
            tab_behavior="focus",
            compact=True,
            highlight_cursor_line=False,
            placeholder=placeholder,
            id=id,
        )
        self.max_rows = 5
        self._history: deque[str] = deque(maxlen=HISTORY_SIZE)
        self._history_index: int | None = None
        self._draft = ""
        self._help_pending = False  # a lone ``?`` showed help; the next character restores it

    @property
    def menu(self) -> CommandMenu | None:
        try:
            return self.screen.query_one(CommandMenu)
        except Exception:
            return None

    @property
    def composer(self) -> Composer:
        for node in self.ancestors:
            if isinstance(node, Composer):
                return node
        raise LookupError("PromptArea is not inside a Composer")

    def push_history(self, text: str) -> None:
        if text and (not self._history or self._history[-1] != text):
            self._history.append(text)
        self._history_index = None

    def _single_line(self) -> bool:
        return self.document.line_count <= 1

    def _recall(self, direction: int) -> bool:
        if not self._history:
            return False
        if self._history_index is None:
            if direction > 0:
                return False
            self._draft = self.text
            self._history_index = len(self._history)
        index = self._history_index + direction
        if index < 0:
            return True
        if index >= len(self._history):
            self._history_index = None
            self.load_text(self._draft)
            self.move_cursor(self.document.end)
            return True
        self._history_index = index
        self.load_text(self._history[index])
        self.move_cursor(self.document.end)
        return True

    def _complete(self, command: SlashCommand) -> None:
        self.load_text(f"/{command.name}" + (" " if command.argument else ""))
        self.move_cursor(self.document.end)

    async def _on_key(self, event: events.Key) -> None:
        key = event.key
        menu = self.menu
        menu_open = menu is not None and menu.open
        if key == "enter":
            event.stop()
            event.prevent_default()
            # A fully typed command runs as typed: the menu's highlight may lag behind a burst
            # of keys (a paste, mosh) and ``/session`` must never run ``/sessions``.
            if menu_open and resolve_command(self.text.strip()) is None:
                command = menu.highlighted_command
                if command is not None and command.argument:
                    self._complete(command)  # partial input: complete, the next Enter runs
                    return
                if command is not None:
                    menu.close()
                    self.load_text("")
                    self.post_message(Composer.Submitted(f"/{command.name}"))
                    return
            self.post_message(Composer.Submitted(self.text))
            return
        if key in ("ctrl+j", "shift+enter"):
            event.stop()
            event.prevent_default()
            self.insert("\n")
            return
        if menu_open and key in ("up", "down"):
            event.stop()
            event.prevent_default()
            if key == "up":
                menu.action_cursor_up()
            else:
                menu.action_cursor_down()
            return
        if menu_open and key == "tab":
            event.stop()
            event.prevent_default()
            command = menu.highlighted_command
            if command is not None:
                self._complete(command)
            return
        if key in ("up", "down") and self._single_line():
            if self._recall(-1 if key == "up" else 1):
                event.stop()
                event.prevent_default()
                return
        if key == "question_mark" and not self.text:
            if not self._help_pending:
                event.stop()
                event.prevent_default()
                self._help_pending = True
                self.post_message(Composer.HelpRequested())
                return
            self._help_pending = False  # a second ``?`` is typed as one
        elif self._help_pending:
            # ``?x``: the second character defeats the interception and sends ``?x``.
            self._help_pending = False
            if event.is_printable and not self.text:
                self.insert("?")
        await super()._on_key(event)

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        text = self.text
        menu = self.menu
        if menu is not None:
            if self._single_line() and MENU_PATTERN.match(text):
                menu.set_query(text)
            else:
                menu.close()
        # Guard against Textual minors: follow the document height explicitly.
        rows = max(1, min(self.max_rows, self.document.line_count))
        self.styles.height = rows
        self.post_message(Composer.Changed())


class Composer(Vertical):
    """Rounded box with a caret and the prompt area. ``state``: idle | busy | attention."""

    SCOPED_CSS = False
    DEFAULT_CSS = """
    Composer {
        border: round $primary 60%; height: auto; min-height: 3; max-height: 7;
        background: $background; padding: 0;
    }
    Composer:focus-within { border: round $primary; }
    Composer.-busy { border: round $secondary; }
    Composer.-attention { border: round $accent; }
    Composer .row { height: auto; }
    Composer .caret { width: 3; padding-left: 1; color: $primary; text-style: bold; }
    Composer.-busy .caret { color: $secondary; }
    Composer.-attention .caret { color: $accent; }
    Screen.-phone Composer {
        border: none; min-height: 1; max-height: 3; background: $surface; padding: 0;
    }
    Screen.-short Composer { max-height: 4; }
    """

    class Submitted(Message):
        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    class HelpRequested(Message):
        pass

    class Changed(Message):
        pass

    state: reactive[str] = reactive("idle", init=False)

    def __init__(self, language: str = "en", *, id: str | None = "composer") -> None:
        super().__init__(id=id)
        self.language = language

    def compose(self):
        with HorizontalGroup(classes="row"):
            yield Static(Text(glyph("caret")), classes="caret", markup=False)
            yield PromptArea(t("tui.composer.placeholder", self.language))

    @property
    def prompt(self) -> PromptArea:
        return self.query_one(PromptArea)

    @property
    def text(self) -> str:
        return self.prompt.text

    def clear(self) -> None:
        self.prompt.load_text("")

    def push_history(self, text: str) -> None:
        self.prompt.push_history(text)

    def watch_state(self, state: str) -> None:
        self.set_class(state == "busy", "-busy")
        self.set_class(state == "attention", "-attention")

    def relabel(self, language: str) -> None:
        self.language = language
        self.prompt.placeholder = t("tui.composer.placeholder", language)

    def set_max_rows(self, rows: int) -> None:
        self.prompt.max_rows = rows


class HintBar(HorizontalGroup):
    """One row of key hints; the app picks the state (idle, busy, attention, menu, events)."""

    SCOPED_CSS = False
    DEFAULT_CSS = """
    HintBar { height: 1; padding: 0 1; color: $text-muted; }
    HintBar #hint-left { width: 1fr; margin-right: 1; text-wrap: nowrap; text-overflow: ellipsis; }
    HintBar #hint-right { width: auto; dock: right; }
    Screen.-short HintBar { display: none; }
    """

    STATES: ClassVar[tuple[str, ...]] = ("idle", "busy", "attention", "menu", "events")

    def __init__(self, language: str = "en", *, id: str | None = "hint") -> None:
        super().__init__(id=id)
        self.language = language
        self.state = "idle"
        self.phone = False
        self.wide = False

    def compose(self):
        yield Static("", id="hint-left", markup=False)
        yield Static("", id="hint-right", markup=False)

    def on_mount(self) -> None:
        self.render_hints()

    def set_state(self, state: str, *, phone: bool, wide: bool) -> None:
        self.state, self.phone, self.wide = state, phone, wide
        self.render_hints()

    def render_hints(self) -> None:
        if not self.is_mounted:
            return
        left, right = hints_for(self.state, self.language, phone=self.phone, wide=self.wide)
        self.query_one("#hint-left", Static).update(Text(left))
        self.query_one("#hint-right", Static).update(Text(right))

    def relabel(self, language: str) -> None:
        self.language = language
        self.render_hints()

    @property
    def text(self) -> str:
        left, right = hints_for(self.state, self.language, phone=self.phone, wide=self.wide)
        return f"{left} | {right}"
