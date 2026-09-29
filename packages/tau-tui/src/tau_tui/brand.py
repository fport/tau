"""The τ mark in the terminal: a rasteriser for the welcome card and the header glyph.

The mark geometry is copied from ``docs/brand/render.py::Mark`` (tau-tui must not import
from ``docs/``); if the mark changes there, change the constants here and regenerate the
fixtures under ``tests/fixtures``. Every cell holds two square pixels (a terminal cell is
about 1:2, so one pixel is about square): ``▀`` with fg = top pixel and bg = bottom pixel,
``▀`` alone, ``▄`` alone, or a space (no background, so Void shows through). The rendering is
deterministic: no randomness, no time, palette colours only, no glow (the brand README forbids
it below 48 px), Ember τ with a Core centre line exactly as ``render.py``'s neon stack.

:class:`TauGlyph` is the one animated cell of the UI (header ``τ``): it breathes while the
welcome card is on screen, runs the comet while a turn is busy, is static otherwise.
"""

from __future__ import annotations

from functools import cache
from math import hypot, inf

from rich.style import Style
from rich.text import Text
from textual.color import Gradient
from textual.reactive import reactive
from textual.timer import Timer
from textual.widgets import Static

from tau_tui.theme import CORE, EMBER, FLARE, SIGNAL, VOID, ascii_mode, glyph, lerp

# -- geometry (docs/brand/render.py::Mark, ring centreline radius 100) ---------------------------
RING_R, RING_W, TAU_W = 100.0, 12.0, 14.0
BAR_Y, BAR_X, BAR_HALF, STEM_X, HOOK_R, HOOK_BOTTOM, TAIL = (
    -46.0,
    0.0,
    54.0,
    -7.0,
    26.0,
    52.0,
    16.0,
)
EXTENT = RING_R + RING_W / 2  # 106
CORE_W = TAU_W * 0.42  # render.py: the Core centre line is 0.42 * tau_w
COVERAGE = 0.2  # a pixel lights when >= 20 % of its samples hit
ALPHA_GAIN = 1.25  # coverage -> opacity, clamped to 1

LOGO_COLS = 24  # welcome card at >= 60 cols: 24 cells wide, 12 rows
LOGO_COLS_PHONE = 16  # -phone: 16 cells wide, 8 rows

Cell = tuple[str, str | None, str | None]
"""``(char, fg hex, bg hex)``; ``None`` means no colour (Void shows through)."""


def mid(a: str, b: str) -> str:
    return lerp(a, b, 0.5)


def tau_dist(x: float, y: float) -> float:
    """Distance to the τ centreline; ``inf`` outside the span of every segment."""
    ys = HOOK_BOTTOM - HOOK_R
    d = inf
    if BAR_X - BAR_HALF <= x <= BAR_X + BAR_HALF:  # bar
        d = min(d, abs(y - BAR_Y))
    if BAR_Y <= y <= ys:  # stem
        d = min(d, abs(x - STEM_X))
    cx, cy = STEM_X + HOOK_R, ys
    if x <= cx and y >= cy:  # hook: quarter circle, left-bottom
        d = min(d, abs(hypot(x - cx, y - cy) - HOOK_R))
    if cx <= x <= cx + TAIL:  # tail
        d = min(d, abs(y - HOOK_BOTTOM))
    return d


def ring_dist(x: float, y: float) -> float:
    return abs(hypot(x, y) - RING_R)


def ring_colour(x: float, y: float) -> str:
    """The SVG's ``x1=0,y1=0 -> x2=1,y2=1`` gradient across the bbox: Signal → Ember."""
    t = ((x + EXTENT) / (2 * EXTENT) + (y + EXTENT) / (2 * EXTENT)) / 2
    return lerp(SIGNAL, EMBER, t)


@cache
def rasterise(cols: int, *, supersample: int = 6) -> list[list[Cell]]:
    """``cols`` x ``cols`` square pixels (a cell is 1 px wide, 2 px tall) → ``cols // 2`` rows.

    Cached: the two sizes the UI uses cost about 20 k point tests each, once per process.
    The result is shared, so callers must not mutate it.
    """
    rows, unit, n = cols // 2, 2 * EXTENT / cols, supersample * supersample
    pixels: list[list[str | None]] = []
    for j in range(cols):  # pixel rows
        row: list[str | None] = []
        for i in range(cols):  # pixel columns
            c_tau = c_core = c_ring = 0
            for sj in range(supersample):
                for si in range(supersample):
                    x = -EXTENT + (i + (si + 0.5) / supersample) * unit
                    y = -EXTENT + (j + (sj + 0.5) / supersample) * unit
                    dt = tau_dist(x, y)
                    if dt <= TAU_W / 2:
                        c_tau += 1
                        if dt <= CORE_W / 2:
                            c_core += 1
                    elif ring_dist(x, y) <= RING_W / 2:
                        c_ring += 1
            cx, cy = -EXTENT + (i + 0.5) * unit, -EXTENT + (j + 0.5) * unit
            if c_tau / n >= COVERAGE:
                base = lerp(EMBER, CORE, c_core / c_tau)  # Ember τ with a Core line
                row.append(lerp(VOID, base, min(1.0, c_tau / n * ALPHA_GAIN)))
            elif c_ring / n >= COVERAGE:
                row.append(lerp(VOID, ring_colour(cx, cy), min(1.0, c_ring / n * ALPHA_GAIN)))
            else:
                row.append(None)
        pixels.append(row)
    cells: list[list[Cell]] = []
    for r in range(rows):
        line: list[Cell] = []
        for i in range(cols):
            top, bot = pixels[2 * r][i], pixels[2 * r + 1][i]
            if top and bot:
                line.append(("▀", top, bot))  # fg = top pixel, bg = bottom pixel
            elif top:
                line.append(("▀", top, None))
            elif bot:
                line.append(("▄", bot, None))
            else:
                line.append((" ", None, None))  # no background: Void shows through
        cells.append(line)
    return cells


def mark_preview(cols: int) -> list[str]:
    """The text-fixture form: both pixels lit → ``█``, top → ``▀``, bottom → ``▄``, none → space."""
    out = []
    for line in rasterise(cols):
        chars = []
        for char, _fg, bg in line:
            if char == "▀" and bg:
                chars.append("█")
            else:
                chars.append(char)
        out.append("".join(chars))
    return out


def mark_text(cols: int) -> Text:
    """One ``Text`` with a ``Style(color, bgcolor)`` per cell and ``"\\n"`` between rows.

    In ASCII mode the same grid is drawn with ``^ _ #`` in Ember only.
    """
    text = Text(no_wrap=True)
    ascii_glyphs = ascii_mode()
    for r, line in enumerate(rasterise(cols)):
        if r:
            text.append("\n")
        for char, fg, bg in line:
            if char == " ":
                text.append(" ")
            elif ascii_glyphs:
                if char == "▀" and bg:
                    text.append(glyph("block_full"), Style(color=EMBER))
                elif char == "▀":
                    text.append(glyph("block_top"), Style(color=EMBER))
                else:
                    text.append(glyph("block_bottom"), Style(color=EMBER))
            else:
                text.append(char, Style(color=fg, bgcolor=bg))
    return text


# -- header glyph -----------------------------------------------------------------------------

BREATHE = [
    Gradient.from_colors(EMBER, FLARE, EMBER, quality=10).get_color(i / 9).hex for i in range(10)
]  # 2 fps -> 5 s, the brand's idle breath
COMET = [
    EMBER,
    mid(EMBER, FLARE),
    FLARE,
    mid(FLARE, CORE),
    CORE,
    mid(FLARE, CORE),
    FLARE,
    mid(EMBER, FLARE),
]  # 4 fps -> 2 s, the brand's thinking comet

GLYPH_STATES = ("idle", "welcome", "busy", "attention")


class TauGlyph(Static):
    """The header ``τ``: one cell, the only animated region of the UI.

    Two paused timers are created once on mount, only when ``motion`` is on and the app's
    ``animation_level`` is ``full``; each state resumes at most one of them. With
    ``motion=False`` (tests) there is no timer at all and only the static states exist.
    """

    DEFAULT_CSS = """
    TauGlyph { width: 2; height: 1; }
    """

    state: reactive[str] = reactive("idle")

    def __init__(self, *, motion: bool = True, id: str | None = None) -> None:
        super().__init__(Text(glyph("tau"), style=EMBER), markup=False, id=id)
        self.motion = motion
        self._breathe: Timer | None = None
        self._comet: Timer | None = None
        self._frame = 0

    @property
    def timers(self) -> tuple[Timer | None, Timer | None]:
        return self._breathe, self._comet

    def on_mount(self) -> None:
        self.update(Text(glyph("tau"), style=EMBER))
        if self.motion and self.app.animation_level == "full":
            self._breathe = self.set_interval(0.5, self._tick_breathe, pause=True)
            self._comet = self.set_interval(0.25, self._tick_comet, pause=True)
        self._apply(self.state)

    def watch_state(self, state: str) -> None:
        if self.is_mounted:
            self._apply(state)

    def _apply(self, state: str) -> None:
        for timer in (self._breathe, self._comet):
            if timer is not None:
                timer.pause()
        if state == "welcome" and self._breathe is not None:
            self._frame = 0
            self._breathe.resume()
        elif state == "busy" and self._comet is not None:
            self._frame = 0
            self._comet.resume()
        elif state == "attention":
            self.update(Text(glyph("tau"), style=f"bold {FLARE}"))
        else:
            self.update(Text(glyph("tau"), style=EMBER))

    def _tick_breathe(self) -> None:
        self._frame = (self._frame + 1) % len(BREATHE)
        self.update(Text(glyph("tau"), style=BREATHE[self._frame]))

    def _tick_comet(self) -> None:
        self._frame = (self._frame + 1) % len(COMET)
        self.update(Text(glyph("tau"), style=COMET[self._frame]))
