"""The key map: one table for the app's bindings, the hint bar and the help card.

Every app binding is ``priority=True`` so it beats the focused ``TextArea``. Keys the text
area needs for editing (``ctrl+a/w/x/c/v/u/k/z/y/d/f/b``, ``home``/``end``), tmux's ``ctrl+b``,
flow control's ``ctrl+s`` and ``ctrl+z`` are never bound. ``ctrl+e`` is taken from the text
area on purpose (``end`` still moves the cursor). F-keys mirror the ctrl keys for Termius'
key bar.

The lock screen (``tau_tui.guard``) has its own keys: Enter unlocks, Esc cancels an attempt,
and :data:`TOUCH_ID_KEY` runs the Touch ID fallback while it is offered.
"""

from __future__ import annotations

from dataclasses import dataclass

from tau_core import t
from textual.binding import Binding


@dataclass(frozen=True)
class KeyBinding:
    key: str
    action: str
    description_key: str
    fkey: str | None = None  # F-key mirror
    shown: str = ""  # how the help card names the key

    priority: bool = True

    def bindings(self) -> list[Binding]:
        out = [Binding(self.key, self.action, show=False, priority=self.priority)]
        if self.fkey:
            out.append(Binding(self.fkey, self.action, show=False, priority=self.priority))
        return out


BINDINGS: tuple[KeyBinding, ...] = (
    # Esc is not priority: the approval modal and the session picker own it while on top,
    # and the text area does not bind it.
    KeyBinding("escape", "escape", "tui.key.cancel", None, "esc", priority=False),
    KeyBinding("ctrl+e", "toggle_events", "tui.key.events", "f4", "ctrl+e / F4"),
    KeyBinding("ctrl+r", "pick_session", "tui.key.sessions", "f2", "ctrl+r / F2"),
    KeyBinding("ctrl+n", "new_session", "tui.key.new", None, "ctrl+n"),
    KeyBinding("ctrl+t", "show_tools", "tui.key.tools", "f3", "ctrl+t / F3"),
    KeyBinding("ctrl+o", "toggle_cards", "tui.key.expand", "f6", "ctrl+o / F6"),
    KeyBinding("pageup", "scroll_transcript_up", "tui.key.scroll", "f7", "PageUp / F7"),
    KeyBinding("pagedown", "scroll_transcript_down", "tui.key.scroll", "f8", "PageDown / F8"),
    KeyBinding("f9", "scroll_bottom", "tui.key.bottom", None, "F9"),
    KeyBinding("f10", "settings", "tui.key.settings", None, "F10"),
    KeyBinding("f1", "help", "tui.key.help", None, "? / F1"),
    KeyBinding("ctrl+l", "lock", "tui.key.lock", "f5", "ctrl+l / F5"),
)
"""The app's own bindings; ``ctrl+q`` (quit) is Textual's default priority binding. F10 opens
the settings (``ctrl+,`` is unreliable over mosh, so there is no ctrl mirror). ``ctrl+l`` locks
the owner guard; its mirror F5 is a free key (Textual's text area binds only F6 and F7, which the
priority mirrors of ctrl+o and PageUp override)."""

HELP_KEYS: tuple[tuple[str, str], ...] = (
    ("enter", "tui.key.send"),
    ("ctrl+j", "tui.key.newline"),
    ("esc", "tui.key.cancel"),
    ("ctrl+e / F4", "tui.key.events"),
    ("ctrl+r / F2", "tui.key.sessions"),
    ("ctrl+n", "tui.key.new"),
    ("ctrl+t / F3", "tui.key.tools"),
    ("ctrl+o / F6", "tui.key.expand"),
    ("PageUp / PageDown", "tui.key.scroll"),
    ("F9", "tui.key.bottom"),
    ("F10", "tui.key.settings"),
    ("? / F1", "tui.key.help"),
    ("ctrl+l / F5", "tui.key.lock"),
    ("ctrl+q", "tui.key.quit"),
)
"""What the help card lists, in this order (``?`` and ``/`` only in an empty composer)."""


TOUCH_ID_KEY = "t"
"""The lock screen's Touch ID fallback key. It is a printable key, so it survives mosh and
Termius, and it acts only in the empty lock-screen field while the guard offers the fallback
(the way ``?`` acts only in an empty composer); anywhere else it is typed. It is not an app
binding: every app action is refused while the guard is locked."""


def app_bindings() -> list[Binding]:
    out: list[Binding] = []
    for binding in BINDINGS:
        out.extend(binding.bindings())
    return out


def hints_for(
    state: str, language: str, *, phone: bool = False, wide: bool = False
) -> tuple[str, str]:
    """``(left, right)`` hint texts for ``state``: idle, busy, attention, menu or events."""
    suffix = "_phone" if phone else ""
    quit_hint = t("tui.hint.quit", language)
    if state == "busy":
        left = t(f"tui.hint.busy{suffix}", language)
        busy = t("tui.hint.busy_word", language)
        if phone:
            right = busy
        elif wide:
            right = f"{busy} · {t('tui.hint.events_key', language)} · {quit_hint}"
        else:
            right = f"{busy} · {quit_hint}"
        return left, right
    if state == "attention":
        left = t("tui.hint.attention", language)
        word = t("tui.hint.approval_word", language)
        return left, word if phone else f"{word} · {quit_hint}"
    if state == "menu":
        return t("tui.hint.menu", language), quit_hint
    if state == "events":
        return t(f"tui.hint.events{suffix}", language), t("tui.hint.chat_key", language)
    left = t(f"tui.hint.idle{suffix}", language)
    if phone:
        right = t("tui.hint.events_key_phone", language)
    elif wide:
        right = f"{t('tui.hint.events_key', language)} · {quit_hint}"
    else:
        right = quit_hint
    return left, right


def hints_for_help(language: str) -> list[str]:
    """The key map lines of the help card (``/help``, ``?``, F1)."""
    width = max(len(key) for key, _ in HELP_KEYS)
    return [f"  {key:<{width}}  {t(desc, language)}" for key, desc in HELP_KEYS]
