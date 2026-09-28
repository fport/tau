"""Render tau's brand assets into docs/brand/ as standalone SVGs.

Usage: python3 docs/brand/render.py [out_dir]

Everything is derived from one geometry (Mark) so the hero, icons, print files
and lockups always agree. The output is deterministic: edit this file, not the
SVGs. Print variants (mono, coin) are filled outlines in a single path, so CAD
tools and slicers can import and extrude them directly.
"""

from __future__ import annotations

import math
import random
import sys
from dataclasses import dataclass
from pathlib import Path

# Palette
VOID = "#05071A"
VOID_2 = "#12061A"
SIGNAL = "#FF2E63"  # neon red-pink: triangles, ring start
EMBER = "#FF7A3D"  # orange: ring end, beams
FLARE = "#FFB25C"  # warm highlight
CORE = "#FFF4E0"  # white-hot neon core
INK = "#14060D"  # one-colour dark
PAPER = "#FFF8F0"  # one-colour light


@dataclass(frozen=True)
class Mark:
    """Ring + tau, in units where the ring's centreline radius is 100."""

    ring_r: float = 100.0
    ring_w: float = 12.0
    tau_w: float = 14.0
    bar_y: float = -46.0  # bar centreline, relative to ring centre
    bar_x: float = 0.0  # bar centre; the stem sits left of it so the hook balances the glyph
    bar_half: float = 54.0
    stem_x: float = -7.0
    hook_r: float = 26.0
    hook_bottom: float = 52.0  # hook/tail centreline y
    tail: float = 16.0

    @property
    def extent(self) -> float:
        return self.ring_r + self.ring_w / 2

    def tau_stroke(self, cx: float, cy: float, s: float) -> str:
        """Centreline path for stroking (butt caps, miter joins)."""
        x0, x1 = cx + (self.bar_x - self.bar_half) * s, cx + (self.bar_x + self.bar_half) * s
        by = cy + self.bar_y * s
        sx = cx + self.stem_x * s
        ys = cy + (self.hook_bottom - self.hook_r) * s
        hr = self.hook_r * s
        return (
            f"M{x0:.2f} {by:.2f} H{x1:.2f} "
            f"M{sx:.2f} {by:.2f} V{ys:.2f} "
            f"A{hr:.2f} {hr:.2f} 0 0 0 {sx + hr:.2f} {ys + hr:.2f} H{sx + hr + self.tail * s:.2f}"
        )

    def tau_outline(self, cx: float, cy: float, s: float) -> str:
        """Closed outline of the stroked tau: one simple shape, for filling and printing."""
        h = self.tau_w / 2 * s
        xl, xr = cx + (self.bar_x - self.bar_half) * s, cx + (self.bar_x + self.bar_half) * s
        by = cy + self.bar_y * s
        sx = cx + self.stem_x * s
        hr = self.hook_r * s
        ys = cy + (self.hook_bottom - self.hook_r) * s
        yb = ys + hr  # tail centreline
        xt = sx + hr + self.tail * s
        return (
            f"M{xl:.2f} {by - h:.2f} H{xr:.2f} V{by + h:.2f} H{sx + h:.2f} V{ys:.2f} "
            f"A{hr - h:.2f} {hr - h:.2f} 0 0 0 {sx + hr:.2f} {yb - h:.2f} "
            f"H{xt:.2f} V{yb + h:.2f} H{sx + hr:.2f} "
            f"A{hr + h:.2f} {hr + h:.2f} 0 0 1 {sx - h:.2f} {ys:.2f} "
            f"V{by + h:.2f} H{xl:.2f} Z"
        )


M = Mark()


def circle_path(cx: float, cy: float, r: float, clockwise: bool = True) -> str:
    sweep = 1 if clockwise else 0
    return (
        f"M{cx - r:.2f} {cy:.2f} A{r:.2f} {r:.2f} 0 1 {sweep} {cx + r:.2f} {cy:.2f} "
        f"A{r:.2f} {r:.2f} 0 1 {sweep} {cx - r:.2f} {cy:.2f} Z"
    )


def arc(cx: float, cy: float, r: float, a0: float, a1: float) -> str:
    """Clockwise arc from angle a0 to a1 in degrees (0 = right, 90 = down)."""
    p0 = (cx + r * math.cos(math.radians(a0)), cy + r * math.sin(math.radians(a0)))
    p1 = (cx + r * math.cos(math.radians(a1)), cy + r * math.sin(math.radians(a1)))
    large = 1 if (a1 - a0) % 360 > 180 else 0
    return f"M{p0[0]:.2f} {p0[1]:.2f} A{r:.2f} {r:.2f} 0 {large} 1 {p1[0]:.2f} {p1[1]:.2f}"


def svg(w: float, h: float, body: str, label: str = "tau") -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w:g} {h:g}" width="{w:g}" height="{h:g}" '
        f'role="img" aria-label="{label}">\n  <title>{label}</title>\n{body}</svg>\n'
    )


NEON_DEFS = f"""    <linearGradient id="ring" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="{SIGNAL}"/>
      <stop offset="1" stop-color="{EMBER}"/>
    </linearGradient>
    <filter id="bloom" x="-50%" y="-50%" width="200%" height="200%">
      <feGaussianBlur stdDeviation="{{blur}}"/>
    </filter>"""


def neon_mark(cx: float, cy: float, s: float, blur: float, core: bool = True) -> str:
    """Neon tube rendering: blurred colour, solid colour, white-hot core."""
    ring = circle_path(cx, cy, M.ring_r * s)
    tau = M.tau_stroke(cx, cy, s)
    rw, tw = M.ring_w * s, M.tau_w * s
    layers = [
        f'<path d="{ring}" fill="none" stroke="url(#ring)" stroke-width="{rw * 2.4:.2f}" filter="url(#bloom)" opacity="0.75"/>',
        f'<path d="{tau}" fill="none" stroke="{FLARE}" stroke-width="{tw * 2.4:.2f}" filter="url(#bloom)" opacity="0.85"/>',
        f'<path d="{ring}" fill="none" stroke="url(#ring)" stroke-width="{rw:.2f}"/>',
        f'<path d="{tau}" fill="none" stroke="{EMBER}" stroke-width="{tw:.2f}" stroke-linejoin="miter"/>',
    ]
    if core:
        layers += [
            f'<path d="{ring}" fill="none" stroke="{CORE}" stroke-width="{rw * 0.34:.2f}" opacity="0.55"/>',
            f'<path d="{tau}" fill="none" stroke="{CORE}" stroke-width="{tw * 0.42:.2f}" stroke-linejoin="miter"/>',
        ]
    return "\n  ".join(layers)


# ---------------------------------------------------------------- marks


def mark_neon() -> str:
    S = 256
    s = 0.96
    defs = NEON_DEFS.replace("{blur}", "7")
    return svg(S, S, f"  <defs>\n{defs}\n  </defs>\n  {neon_mark(S / 2, S / 2, s, 7)}\n")


def mark_mono(color: str = "currentColor") -> str:
    S = 256
    c, s = S / 2, 1.1
    ro, ri = (M.ring_r + M.ring_w / 2) * s, (M.ring_r - M.ring_w / 2) * s
    d = f"{circle_path(c, c, ro)} {circle_path(c, c, ri)} {M.tau_outline(c, c, s)}"
    return svg(S, S, f'  <path fill="{color}" fill-rule="evenodd" d="{d}"/>\n')


def coin(color: str = "currentColor") -> str:
    """Solid disc with the tau knocked out: favicon, menu bar template icon, pendant."""
    S = 256
    c = S / 2
    s = 1.18
    d = f"{circle_path(c, c, 124)} {M.tau_outline(c, c + 2, s)}"
    return svg(S, S, f'  <path fill="{color}" fill-rule="evenodd" d="{d}"/>\n')


def app_icon() -> str:
    S = 512
    c = S / 2
    s = 1.55
    defs = NEON_DEFS.replace("{blur}", "10")
    body = f"""  <defs>
    <linearGradient id="tile" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#0A0C24"/>
      <stop offset="1" stop-color="{VOID_2}"/>
    </linearGradient>
    <radialGradient id="glow" cx="0.5" cy="0.5" r="0.5">
      <stop offset="0" stop-color="{EMBER}" stop-opacity="0.32"/>
      <stop offset="1" stop-color="{SIGNAL}" stop-opacity="0"/>
    </radialGradient>
{defs}
  </defs>
  <rect width="{S}" height="{S}" rx="112" fill="url(#tile)"/>
  <circle cx="{c}" cy="{c}" r="{S * 0.46:.0f}" fill="url(#glow)"/>
  <rect x="1" y="1" width="{S - 2}" height="{S - 2}" rx="111" fill="none" stroke="#FFFFFF" stroke-opacity="0.06" stroke-width="2"/>
  {neon_mark(c, c, s, 10)}
"""
    return svg(S, S, body)


# ---------------------------------------------------------------- wordmark


@dataclass(frozen=True)
class Word:
    x_height: float = 100.0
    w: float = 15.0
    gap: float = 34.0

    def paths(self, x: float, baseline: float) -> tuple[str, float]:
        """Stroke centrelines for 'tau' starting at x; returns (d, width)."""
        X, w, h = self.x_height, self.w, self.w / 2
        parts = []
        # t: stem with the same hook as the mark
        rh, tail = M.hook_r * 0.62, M.tail * 0.7
        tx = x + 0.30 * X
        ys = baseline - h - rh
        parts.append(f"M{tx:.2f} {baseline - 1.32 * X:.2f} V{ys:.2f} A{rh:.2f} {rh:.2f} 0 0 0 {tx + rh:.2f} {baseline - h:.2f} H{tx + rh + tail:.2f}")
        parts.append(f"M{x:.2f} {baseline - X + h:.2f} H{tx + 0.34 * X:.2f}")
        t_right = max(tx + 0.34 * X, tx + rh + tail)
        # a: round bowl + right stem
        r = X / 2 - h
        ax = t_right + self.gap + X / 2
        parts.append(circle_path(ax, baseline - X / 2, r))
        parts.append(f"M{ax + r:.2f} {baseline - X:.2f} V{baseline:.2f}")
        # u: bowl open at the top + right stem
        ux = ax + X / 2 + self.gap + X / 2
        parts.append(f"M{ux - r:.2f} {baseline - X:.2f} V{baseline - X / 2:.2f} A{r:.2f} {r:.2f} 0 0 0 {ux + r:.2f} {baseline - X / 2:.2f}")
        parts.append(f"M{ux + r:.2f} {baseline - X:.2f} V{baseline:.2f}")
        return " ".join(parts), (ux + r + h) - x


WORD = Word()


def wordmark(color: str = "currentColor") -> str:
    pad = 8
    d, width = WORD.paths(pad, 1.32 * WORD.x_height + pad)
    W, H = width + 2 * pad, 1.32 * WORD.x_height + 2 * pad
    return svg(W, H, f'  <path d="{d}" fill="none" stroke="{color}" stroke-width="{WORD.w}" stroke-linejoin="miter"/>\n')


def lockup(dark: bool) -> str:
    """Mark + wordmark, side by side. dark=True is for dark backgrounds."""
    X = WORD.x_height
    mark_d = 2 * M.extent  # mark drawn at scale 1
    H = mark_d + 40
    cy = H / 2
    mx = 20 + M.extent
    baseline = cy + X / 2 + 2
    d, width = WORD.paths(mx + M.extent + 0.62 * X, baseline)
    W = mx + M.extent + 0.62 * X + width + 24
    if dark:
        defs = NEON_DEFS.replace("{blur}", "6")
        body = f"""  <defs>
{defs}
  </defs>
  {neon_mark(mx, cy, 1, 6)}
  <path d="{d}" fill="none" stroke="{CORE}" stroke-width="{WORD.w}" stroke-linejoin="miter"/>
"""
    else:
        ro, ri = M.ring_r + M.ring_w / 2, M.ring_r - M.ring_w / 2
        md = f"{circle_path(mx, cy, ro)} {circle_path(mx, cy, ri)} {M.tau_outline(mx, cy, 1)}"
        body = f"""  <path fill="{INK}" fill-rule="evenodd" d="{md}"/>
  <path d="{d}" fill="none" stroke="{INK}" stroke-width="{WORD.w}" stroke-linejoin="miter"/>
"""
    return svg(W, H, body)


# ---------------------------------------------------------------- hero

W, H = 1280, 560
CX = W / 2
FLOOR = 468
PX, PY = CX, 322
OUTER = (40, 318)
INNER = (112, 244)
HERO_S = 0.92  # mark scale in the hero


def tri(apex_y: float, half: float) -> str:
    return f"M{CX} {apex_y} L{CX + half} {FLOOR} L{CX - half} {FLOOR} Z"


def beams():
    rng = random.Random(7)
    rects, glows, glints = [], [], []
    x = 6.0
    while x < W:
        near = 1 - abs(x - CX) / CX
        width = rng.choice([1, 1, 1.5, 2, 2.5]) * (1 + 0.6 * near)
        opacity = min(1.0, 0.18 + 0.75 * near**1.6 + rng.uniform(-0.08, 0.12))
        top = rng.uniform(0, 140)
        grad = "beamHot" if near > 0.55 and rng.random() < 0.6 else "beam"
        rects.append(f'<rect x="{x:.1f}" y="{top:.0f}" width="{width:.1f}" height="{FLOOR - top:.0f}" fill="url(#{grad})" opacity="{opacity:.2f}"/>')
        if near > 0.62 and rng.random() < 0.45:
            glows.append(f'<rect x="{x - 3:.1f}" y="{top + 60:.0f}" width="{width + 6:.1f}" height="{FLOOR - top - 60:.0f}" fill="url(#beamHot)" opacity="{0.5 + 0.4 * near:.2f}"/>')
        if abs(x - CX) < OUTER[1] + 40 and rng.random() < 0.75:
            glints.append((x + width / 2, 0.55 + 0.45 * near))
        x += rng.uniform(18, 36)
    return "\n    ".join(rects), "\n    ".join(glows), glints


def dial(r: float, ticks: int, length: float, width: float, color: str, opacity: float) -> str:
    """Evenly spaced radial ticks: a precise instrument ring."""
    lines = []
    for i in range(ticks):
        a = math.radians(360 * i / ticks)
        x0, y0 = PX + r * math.cos(a), PY + r * math.sin(a)
        x1, y1 = PX + (r + length) * math.cos(a), PY + (r + length) * math.sin(a)
        lines.append(f"M{x0:.2f} {y0:.2f} L{x1:.2f} {y1:.2f}")
    return f'<path d="{" ".join(lines)}" stroke="{color}" stroke-width="{width}" opacity="{opacity}" fill="none"/>'


def thinking_arc(r: float) -> str:
    """A comet-like arc: bright head, fading tail. Rotates while tau thinks."""
    segs = []
    n = 14
    for i in range(n):
        a0 = -90 - (i + 1) * 6
        a1 = -90 - i * 6
        op = (1 - i / n) ** 1.8
        segs.append(f'<path d="{arc(PX, PY, r, a0, a1 + 0.6)}" stroke="{FLARE if i < 3 else EMBER}" stroke-width="{3 - i * 0.12:.2f}" opacity="{op:.2f}" fill="none"/>')
    head = PX + r * math.cos(math.radians(-90)), PY + r * math.sin(math.radians(-90))
    segs.append(f'<circle cx="{head[0]:.2f}" cy="{head[1]:.2f}" r="3.2" fill="{CORE}"/>')
    return "\n    ".join(segs)


def hero() -> str:
    rng = random.Random(11)
    rects, glows, glints = beams()
    glint_svg = "\n    ".join(
        f'<ellipse cx="{gx:.1f}" cy="{FLOOR}" rx="2" ry="{16 + 22 * k:.0f}" fill="url(#glint)" opacity="{k:.2f}"/>'
        f'<rect x="{gx - 0.8:.1f}" y="{FLOOR}" width="1.6" height="{50 + 60 * k:.0f}" fill="url(#reflect)" opacity="{0.75 * k:.2f}"/>'
        for gx, k in glints
    )
    sparks = []
    for _ in range(28):
        a = rng.uniform(0, 2 * math.pi)
        r = rng.uniform(150, 205)
        sparks.append(f'<circle cx="{PX + r * math.cos(a):.1f}" cy="{PY + r * math.sin(a):.1f}" r="{rng.choice([0.8, 1, 1.2, 1.6])}" fill="{rng.choice([CORE, FLARE, EMBER])}" opacity="{rng.uniform(0.3, 0.85):.2f}"/>')
    ring_r = M.ring_r * HERO_S
    defs = NEON_DEFS.replace("{blur}", "7")
    body = f"""  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="{VOID}"/>
      <stop offset="0.65" stop-color="#0B0A1F"/>
      <stop offset="1" stop-color="{VOID_2}"/>
    </linearGradient>
    <radialGradient id="ambient" cx="{PX / W:.3f}" cy="{PY / H:.3f}" r="0.55">
      <stop offset="0" stop-color="#FF5A1F" stop-opacity="0.34"/>
      <stop offset="0.45" stop-color="#C2183C" stop-opacity="0.13"/>
      <stop offset="1" stop-color="{VOID}" stop-opacity="0"/>
    </radialGradient>
    <radialGradient id="vignette" cx="0.5" cy="0.5" r="0.75">
      <stop offset="0.6" stop-color="#000" stop-opacity="0"/>
      <stop offset="1" stop-color="#000" stop-opacity="0.65"/>
    </radialGradient>
    <linearGradient id="beam" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="{SIGNAL}" stop-opacity="0"/>
      <stop offset="0.55" stop-color="{SIGNAL}" stop-opacity="0.35"/>
      <stop offset="1" stop-color="#FF4D4D" stop-opacity="0.9"/>
    </linearGradient>
    <linearGradient id="beamHot" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="{EMBER}" stop-opacity="0"/>
      <stop offset="0.5" stop-color="{EMBER}" stop-opacity="0.45"/>
      <stop offset="1" stop-color="#FFC27A" stop-opacity="1"/>
    </linearGradient>
    <radialGradient id="glint">
      <stop offset="0" stop-color="{CORE}"/>
      <stop offset="0.4" stop-color="{FLARE}"/>
      <stop offset="1" stop-color="#FF4D4D" stop-opacity="0"/>
    </radialGradient>
    <linearGradient id="reflect" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="{FLARE}" stop-opacity="0.9"/>
      <stop offset="1" stop-color="{SIGNAL}" stop-opacity="0"/>
    </linearGradient>
    <linearGradient id="floor" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="{SIGNAL}" stop-opacity="0"/>
      <stop offset="0.5" stop-color="{FLARE}" stop-opacity="1"/>
      <stop offset="1" stop-color="{SIGNAL}" stop-opacity="0"/>
    </linearGradient>
    <radialGradient id="halo">
      <stop offset="0" stop-color="#FF8A3D" stop-opacity="0.55"/>
      <stop offset="0.5" stop-color="#FF4D2E" stop-opacity="0.2"/>
      <stop offset="1" stop-color="#C2183C" stop-opacity="0"/>
    </radialGradient>
    <radialGradient id="inner">
      <stop offset="0" stop-color="{FLARE}" stop-opacity="0.30"/>
      <stop offset="0.7" stop-color="{EMBER}" stop-opacity="0.10"/>
      <stop offset="1" stop-color="{EMBER}" stop-opacity="0"/>
    </radialGradient>
    <filter id="glow" x="-20%" y="-20%" width="140%" height="140%">
      <feGaussianBlur stdDeviation="5" result="b"/>
      <feMerge><feMergeNode in="b"/><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
    <filter id="soft" x="-50%" y="-50%" width="200%" height="200%">
      <feGaussianBlur stdDeviation="9"/>
    </filter>
{defs}
  </defs>
  <style>
    .turn {{ transform-origin: {PX}px {PY}px; animation: turn 80s linear infinite; }}
    .turn-back {{ transform-origin: {PX}px {PY}px; animation: turn 120s linear infinite reverse; }}
    .think {{ transform-origin: {PX}px {PY}px; animation: turn 7s cubic-bezier(.55,.1,.45,.9) infinite; }}
    .breathe {{ animation: breathe 5s ease-in-out infinite; }}
    @keyframes turn {{ to {{ transform: rotate(360deg); }} }}
    @keyframes breathe {{ 0%, 100% {{ opacity: .75; }} 50% {{ opacity: 1; }} }}
    @media (prefers-reduced-motion: reduce) {{ .turn, .turn-back, .think, .breathe {{ animation: none; }} }}
  </style>

  <rect width="{W}" height="{H}" fill="url(#bg)"/>
  <rect width="{W}" height="{H}" fill="url(#ambient)"/>
  <g>
    {rects}
  </g>
  <g filter="url(#soft)">
    {glows}
  </g>

  <!-- the stage: light behind the mark -->
  <circle cx="{PX}" cy="{PY}" r="230" fill="url(#halo)"/>
  <circle class="breathe" cx="{PX}" cy="{PY}" r="{ring_r + 6:.1f}" fill="url(#inner)"/>

  <!-- instrument rings -->
  <g class="turn" fill="none">
    {dial(ring_r + 22, 120, 3, 1, FLARE, 0.45)}
    {dial(ring_r + 22, 12, 9, 1.6, FLARE, 0.8)}
  </g>
  <g class="turn-back" fill="none">
    <circle cx="{PX}" cy="{PY}" r="{ring_r + 44:.1f}" stroke="{SIGNAL}" stroke-width="1" opacity="0.45"/>
    {dial(ring_r + 44, 4, -6, 1.6, SIGNAL, 0.8)}
  </g>
  <g class="think" filter="url(#glow)">
    {thinking_arc(ring_r + 32)}
  </g>
  <g class="turn-back">
    {"".join(sparks)}
  </g>

  <!-- the mark -->
  {neon_mark(PX, PY, HERO_S, 7)}

  <!-- triangles -->
  <g fill="none" stroke-linejoin="miter" filter="url(#glow)">
    <path d="{tri(*OUTER)}" stroke="{SIGNAL}" stroke-width="3"/>
    <path d="{tri(*INNER)}" stroke="#FF4D4D" stroke-width="3.5"/>
  </g>

  <!-- floor -->
  <rect x="0" y="{FLOOR}" width="{W}" height="{H - FLOOR}" fill="#05030C" opacity="0.55"/>
  <ellipse cx="{PX}" cy="{FLOOR + 22}" rx="300" ry="34" fill="url(#halo)" opacity="0.8"/>
  <g opacity="0.45" transform="translate(0 {2 * FLOOR}) scale(1 -1)">
    <path d="{tri(*OUTER)}" fill="none" stroke="{SIGNAL}" stroke-width="2" filter="url(#soft)"/>
    <circle cx="{PX}" cy="{PY}" r="{ring_r:.1f}" fill="none" stroke="{EMBER}" stroke-width="6" filter="url(#soft)"/>
  </g>
  <rect x="0" y="{FLOOR - 1}" width="{W}" height="2" fill="url(#floor)" filter="url(#glow)"/>
  <g>
    {glint_svg}
  </g>

  <text x="{CX}" y="{H - 26}" text-anchor="middle" font-family="ui-monospace, SFMono-Regular, Menlo, Consolas, monospace" font-size="13" letter-spacing="7" fill="#F6B9A6" opacity="0.75">DÜŞÜNÜR · DOKUNUR · HATIRLAR</text>
  <rect width="{W}" height="{H}" fill="url(#vignette)"/>
"""
    return svg(W, H, body)


FILES = {
    "tau-hero.svg": hero,
    "tau-mark.svg": mark_neon,
    "tau-mark-mono.svg": mark_mono,
    "tau-coin.svg": coin,
    "tau-app-icon.svg": app_icon,
    "tau-wordmark.svg": wordmark,
    "tau-lockup-dark.svg": lambda: lockup(dark=True),
    "tau-lockup-light.svg": lambda: lockup(dark=False),
}

if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).parent)
    out.mkdir(parents=True, exist_ok=True)
    for name, make in FILES.items():
        (out / name).write_text(make())
    print("\n".join(str(out / n) for n in FILES))
