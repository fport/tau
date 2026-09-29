"""Palette, themes and the glyph vocabulary of the tau TUI.

The colours are the brand palette (``docs/brand/README.md``); the two darks ``SURFACE`` and
``PANEL`` come from ``docs/brand/render.py`` (the app-icon tile's top stop and ``VOID_2``).
State colours are deliberate and documented in both READMEs: ok = Flare, error = Signal,
rejected = Ember, running/pending = Core at 55 % (``$text-muted``), attention = Flare,
notice = Ember. There is no green and no red anywhere; shapes double the colours.

Every glyph is one cell wide (``rich.cells.cell_len``) and none is an Emoji=Yes code point,
so Termius over mosh draws them at the right width. ``TAU_TUI_ASCII=1`` switches the whole
vocabulary to ASCII through :func:`glyph` and the box borders through :data:`ASCII_CSS` (the
screens carry the ``-ascii`` class, see :func:`mark_ascii`); nothing else in the package
tests for it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, fields

from textual.dom import DOMNode
from textual.theme import Theme

VOID = "#05071A"
SIGNAL = "#FF2E63"
EMBER = "#FF7A3D"
FLARE = "#FFB25C"
CORE = "#FFF4E0"
INK = "#14060D"
SURFACE = "#0A0C24"  # render.py: app-icon tile, top stop
PANEL = "#12061A"  # render.py: VOID_2

PALETTE = (VOID, SIGNAL, EMBER, FLARE, CORE)
"""The colours the rasterised mark may use (every lit cell is a blend of these)."""


def _rgb(colour: str) -> tuple[int, int, int]:
    value = colour.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def lerp(a: str, b: str, t: float) -> str:
    """Per-channel ``int(round(a + (b - a) * t))`` with ``t`` clamped to ``[0, 1]``."""
    t = max(0.0, min(1.0, t))
    ra, ga, ba = _rgb(a)
    rb, gb, bb = _rgb(b)
    r = int(round(ra + (rb - ra) * t))
    g = int(round(ga + (gb - ga) * t))
    bl = int(round(ba + (bb - ba) * t))
    return f"#{r:02X}{g:02X}{bl:02X}"


TEXT_MUTED = lerp(VOID, CORE, 0.6)
"""Core over Void at Textual's ``$text-muted`` alpha (60 %), as a literal for Rich styles.

TCSS takes ``"#FFF4E0 55%"``; ``rich.style.Style`` does not (the alpha suffix fails to parse
and the text renders unstyled), so Rich renderables use these two hexes."""
TEXT_DISABLED = lerp(VOID, CORE, 0.38)
"""Core over Void at the ``$text-disabled`` alpha (38 %)."""

TAU_THEME = Theme(
    name="tau",
    dark=True,
    primary=EMBER,  # τ, chrome borders, focus, caret, current markers   (brand: Ember)
    secondary=SIGNAL,  # busy border/caret, ring start                       (brand: Signal)
    accent=FLARE,  # attention ◆, user gutter, success                   (brand: Flare)
    warning=FLARE,
    error=SIGNAL,
    success=FLARE,
    foreground=CORE,
    background=VOID,
    surface=SURFACE,
    panel=PANEL,
    variables={
        "block-cursor-background": EMBER,
        "block-cursor-foreground": VOID,
        "block-cursor-blurred-background": f"{EMBER} 35%",
        "block-hover-background": f"{FLARE} 10%",
        "input-cursor-background": FLARE,
        "input-cursor-foreground": VOID,
        "input-selection-background": f"{SIGNAL} 35%",
        "border": EMBER,
        "border-blurred": f"{EMBER} 40%",
        "markdown-h1-color": FLARE,
        "markdown-h2-color": FLARE,
        "markdown-h3-color": EMBER,
        "markdown-h1-background": "transparent",
        "markdown-h2-background": "transparent",
        "link-color": FLARE,
        "link-color-hover": CORE,
        "scrollbar-color": f"{EMBER} 40%",
        "scrollbar-color-hover": EMBER,
        "scrollbar-background": VOID,
        "button-color-foreground": VOID,
        # tau state tokens, referenced as $tau-… in widget DEFAULT_CSS
        "tau-user": FLARE,
        "tau-ok": FLARE,
        "tau-error": SIGNAL,
        "tau-rejected": EMBER,
        "tau-running": f"{CORE} 55%",
        "tau-attention": FLARE,
        "tau-notice": EMBER,
    },
)

TAU_ANSI_THEME = Theme(
    name="tau-ansi",
    dark=True,
    ansi=True,
    primary="ansi_bright_red",
    secondary="ansi_red",
    accent="ansi_yellow",
    warning="ansi_yellow",
    error="ansi_red",
    success="ansi_yellow",
    foreground="ansi_white",
    background="ansi_black",
    surface="ansi_black",
    panel="ansi_black",
    variables={
        "tau-user": "ansi_yellow",
        "tau-ok": "ansi_yellow",
        "tau-error": "ansi_red",
        "tau-rejected": "ansi_bright_red",
        "tau-running": "ansi_bright_black",
        "tau-attention": "ansi_yellow",
        "tau-notice": "ansi_bright_red",
    },
)

STATUS_CLASS = {
    "running": "-running",
    "pending": "-pending",
    "ok": "-ok",
    "error": "-error",
    "rejected": "-rejected",
}
"""Tool-card status → the CSS class that colours its dot."""


@dataclass(frozen=True)
class Glyphs:
    """The one-cell vocabulary. ``unicode`` is the default, ``ascii`` the fallback."""

    user: str  # gutter of a user row
    tau: str  # gutter of a reply, the header mark
    tool_done: str  # finished tool call
    tool_run: str  # running / pending tool call
    result: str  # result line under a tool call
    busy: str  # busy verb, reasoning card
    ok: str  # turn footer, events
    fail: str  # turn footer, events, rejected/error results
    attention: str  # modal titles, approval lines, limits/cancel footer
    notice: str  # notices, current session marker
    caret: str  # composer prompt
    bullet: str  # unknown event kinds
    block_full: str  # preview of a cell with both pixels lit
    block_top: str  # top pixel lit
    block_bottom: str  # bottom pixel lit

    @classmethod
    def unicode(cls) -> Glyphs:
        return cls(
            user="›",
            tau="τ",
            tool_done="●",
            tool_run="○",
            result="⎿",
            busy="✻",
            ok="✓",
            fail="✗",
            attention="◆",
            notice="▸",
            caret="❯",
            bullet="•",
            block_full="█",
            block_top="▀",
            block_bottom="▄",
        )

    @classmethod
    def ascii(cls) -> Glyphs:
        return cls(
            user=">",
            tau="t",
            tool_done="*",
            tool_run="o",
            result="L",
            busy="*",
            ok="+",
            fail="x",
            attention="!",
            notice="-",
            caret=">",
            bullet="-",
            block_full="#",
            block_top="^",
            block_bottom="_",
        )

    def as_dict(self) -> dict[str, str]:
        return {f.name: getattr(self, f.name) for f in fields(self)}


GLYPHS_UNICODE = Glyphs.unicode()
GLYPHS_ASCII = Glyphs.ascii()


def ascii_mode() -> bool:
    """``TAU_TUI_ASCII=1`` (read at call time so tests can flip it)."""
    return os.environ.get("TAU_TUI_ASCII", "") not in ("", "0")


def glyphs() -> Glyphs:
    return GLYPHS_ASCII if ascii_mode() else GLYPHS_UNICODE


def glyph(name: str) -> str:
    """One glyph by its :class:`Glyphs` field name, honouring ``TAU_TUI_ASCII``."""
    return getattr(glyphs(), name)


def mark_ascii(screen: DOMNode) -> None:
    """Give a screen the ``-ascii`` class in ASCII mode (the hook :data:`ASCII_CSS` keys on).

    Every screen (the default one and the modals) calls it on mount, so a widget's borders
    follow the mode wherever it is shown.
    """
    screen.set_class(ascii_mode(), "-ascii")


ASCII_CSS = """
/* TAU_TUI_ASCII=1: every box border becomes the ``ascii`` style. App CSS beats DEFAULT_CSS
   whatever the selector, so each state and band variant of a border is restated here. */
Screen.-ascii Composer { border: ascii $primary 60%; }
Screen.-ascii Composer:focus-within { border: ascii $primary; }
Screen.-ascii Composer.-busy { border: ascii $secondary; }
Screen.-ascii Composer.-attention { border: ascii $accent; }
Screen.-ascii.-phone Composer { border: none; }
Screen.-ascii CommandMenu { border: ascii $primary 60%; }
Screen.-ascii WelcomeCard { border: ascii $primary 45%; }
Screen.-ascii ToolCard .detail-box { border: ascii $primary 35%; }
Screen.-ascii ReplyBlock MarkdownFence { border-left: ascii $primary 50%; }
Screen.-ascii EventsPane { border-left: ascii $primary 35%; }
Screen.-ascii.-narrow.-tall EventsPane { border-left: none; border-top: ascii $primary 35%; }
Screen.-ascii.-phone.-events EventsPane, Screen.-ascii.-narrow.-events EventsPane {
    border: none;
}
Screen.-ascii SessionSidebar { border-right: ascii $primary 35%; }
ApprovalScreen.-ascii > #dialog, SessionPicker.-ascii #dialog { border: ascii $accent; }
"""
"""Appended to ``TauApp.CSS``; active only on screens that carry ``-ascii``."""
