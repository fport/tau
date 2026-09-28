"""Generate docs/assets/tau-hero.svg and tau-mark.svg: standalone SVGs, no external refs, no fonts in the art.

Usage: python3 docs/assets/render_art.py docs/assets
The output is deterministic (seeded), so edit this file rather than the SVGs.
"""
import random
import sys
from pathlib import Path

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
W, H = 1280, 560
CX = W / 2
FLOOR = 468
PORTAL = (CX, 330)

# Triangles: apex, base half-width, all sharing the floor line.
OUTER = (40, 318)
INNER = (112, 244)


def tri(apex_y, half):
    return f"M{CX} {apex_y} L{CX + half} {FLOOR} L{CX - half} {FLOOR} Z"


def tau_path(cx, cy, s):
    """Lower-case tau as two strokes, centred on (cx, cy), scale s (1 = 100px box)."""
    bar_y = cy - 0.30 * s
    x0, x1 = cx - 0.44 * s, cx + 0.44 * s
    stem_bottom = cy + 0.24 * s
    return (
        f"M{x0:.1f} {bar_y:.1f} H{x1:.1f} "
        f"M{cx:.1f} {bar_y:.1f} V{stem_bottom:.1f} "
        f"Q{cx:.1f} {cy + 0.44 * s:.1f} {cx + 0.22 * s:.1f} {cy + 0.44 * s:.1f} H{cx + 0.30 * s:.1f}"
    )


def streaks():
    rng = random.Random(7)
    out, glints, beams = [], [], []
    x = 6.0
    while x < W:
        d = abs(x - CX) / CX  # 0 at centre, 1 at edges
        near = 1 - d
        width = rng.choice([1, 1, 1.5, 2, 2.5]) * (1 + 0.6 * near)
        opacity = min(1.0, 0.18 + 0.75 * near**1.6 + rng.uniform(-0.08, 0.12))
        top = rng.uniform(0, 140)
        grad = "streakHot" if near > 0.55 and rng.random() < 0.6 else "streak"
        out.append(
            f'<rect x="{x:.1f}" y="{top:.0f}" width="{width:.1f}" height="{FLOOR - top:.0f}" '
            f'fill="url(#{grad})" opacity="{opacity:.2f}"/>'
        )
        if near > 0.62 and rng.random() < 0.45:
            beams.append(
                f'<rect x="{x - 3:.1f}" y="{top + 60:.0f}" width="{width + 6:.1f}" height="{FLOOR - top - 60:.0f}" '
                f'fill="url(#streakHot)" opacity="{0.5 + 0.4 * near:.2f}"/>'
            )
        if abs(x - CX) < OUTER[1] + 40 and rng.random() < 0.75:
            glints.append((x + width / 2, 0.55 + 0.45 * near))
        x += rng.uniform(18, 36)
    return "\n    ".join(out), glints, "\n    ".join(beams)


def ring_arcs(cx, cy, r, segments, rng, width, color, opacity):
    import math

    parts = []
    for _ in range(segments):
        a0 = rng.uniform(0, 2 * math.pi)
        span = rng.uniform(0.25, 0.9)
        a1 = a0 + span
        x0, y0 = cx + r * math.cos(a0), cy + r * math.sin(a0)
        x1, y1 = cx + r * math.cos(a1), cy + r * math.sin(a1)
        parts.append(f"M{x0:.1f} {y0:.1f} A{r} {r} 0 0 1 {x1:.1f} {y1:.1f}")
    return (
        f'<path d="{" ".join(parts)}" fill="none" stroke="{color}" stroke-width="{width}" '
        f'stroke-linecap="round" opacity="{opacity}"/>'
    )


def sparks(cx, cy, rng):
    import math

    dots = []
    for _ in range(46):
        a = rng.uniform(0, 2 * math.pi)
        r = rng.uniform(118, 200)
        size = rng.choice([0.8, 1, 1.2, 1.6, 2.2])
        color = rng.choice(["#FFF1CF", "#FFC27A", "#FF8A3D"])
        dots.append(
            f'<circle cx="{cx + r * math.cos(a):.1f}" cy="{cy + r * math.sin(a):.1f}" r="{size}" '
            f'fill="{color}" opacity="{rng.uniform(0.35, 0.95):.2f}"/>'
        )
    return "".join(dots)


def hero():
    rng = random.Random(11)
    px, py = PORTAL
    streak_rects, glints, beams = streaks()
    glint_svg = "\n    ".join(
        f'<ellipse cx="{gx:.1f}" cy="{FLOOR}" rx="2" ry="{16 + 22 * k:.0f}" fill="url(#glint)" opacity="{k:.2f}"/>'
        f'<rect x="{gx - 0.8:.1f}" y="{FLOOR}" width="1.6" height="{50 + 60 * k:.0f}" fill="url(#reflect)" opacity="{0.75 * k:.2f}"/>'
        for gx, k in glints
    )
    tau = tau_path(px, py + 8, 132)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-label="tau">
  <title>tau</title>
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#05071A"/>
      <stop offset="0.65" stop-color="#0B0A1F"/>
      <stop offset="1" stop-color="#12061A"/>
    </linearGradient>
    <radialGradient id="ambient" cx="{px / W:.3f}" cy="{py / H:.3f}" r="0.55">
      <stop offset="0" stop-color="#FF5A1F" stop-opacity="0.38"/>
      <stop offset="0.45" stop-color="#C2183C" stop-opacity="0.14"/>
      <stop offset="1" stop-color="#05071A" stop-opacity="0"/>
    </radialGradient>
    <radialGradient id="vignette" cx="0.5" cy="0.5" r="0.75">
      <stop offset="0.6" stop-color="#000" stop-opacity="0"/>
      <stop offset="1" stop-color="#000" stop-opacity="0.65"/>
    </radialGradient>
    <linearGradient id="streak" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#FF2E63" stop-opacity="0"/>
      <stop offset="0.55" stop-color="#FF2E63" stop-opacity="0.35"/>
      <stop offset="1" stop-color="#FF4D4D" stop-opacity="0.9"/>
    </linearGradient>
    <linearGradient id="streakHot" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#FF7A3D" stop-opacity="0"/>
      <stop offset="0.5" stop-color="#FF7A3D" stop-opacity="0.45"/>
      <stop offset="1" stop-color="#FFC27A" stop-opacity="1"/>
    </linearGradient>
    <radialGradient id="glint">
      <stop offset="0" stop-color="#FFF4E0"/>
      <stop offset="0.4" stop-color="#FFB25C"/>
      <stop offset="1" stop-color="#FF4D4D" stop-opacity="0"/>
    </radialGradient>
    <linearGradient id="reflect" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#FFB25C" stop-opacity="0.9"/>
      <stop offset="1" stop-color="#FF2E63" stop-opacity="0"/>
    </linearGradient>
    <linearGradient id="floor" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="#FF2E63" stop-opacity="0"/>
      <stop offset="0.5" stop-color="#FFB25C" stop-opacity="1"/>
      <stop offset="1" stop-color="#FF2E63" stop-opacity="0"/>
    </linearGradient>
    <radialGradient id="halo">
      <stop offset="0" stop-color="#FF8A3D" stop-opacity="0.75"/>
      <stop offset="0.5" stop-color="#FF4D2E" stop-opacity="0.28"/>
      <stop offset="1" stop-color="#C2183C" stop-opacity="0"/>
    </radialGradient>
    <radialGradient id="core">
      <stop offset="0" stop-color="#FFF8E6"/>
      <stop offset="0.28" stop-color="#FFE0A0"/>
      <stop offset="0.55" stop-color="#FFA640"/>
      <stop offset="0.82" stop-color="#FF5A1F"/>
      <stop offset="1" stop-color="#E0283C" stop-opacity="0.2"/>
    </radialGradient>
    <filter id="glow" x="-20%" y="-20%" width="140%" height="140%">
      <feGaussianBlur stdDeviation="5" result="b"/>
      <feMerge><feMergeNode in="b"/><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
    <filter id="soft" x="-50%" y="-50%" width="200%" height="200%">
      <feGaussianBlur stdDeviation="9"/>
    </filter>
  </defs>
  <style>
    .spin {{ transform-origin: {px}px {py}px; animation: spin 60s linear infinite; }}
    .spin-rev {{ transform-origin: {px}px {py}px; animation: spin 90s linear infinite reverse; }}
    .pulse {{ transform-origin: {px}px {py}px; animation: pulse 4.5s ease-in-out infinite; }}
    @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
    @keyframes pulse {{ 0%, 100% {{ opacity: 0.85; transform: scale(1); }} 50% {{ opacity: 1; transform: scale(1.04); }} }}
    @media (prefers-reduced-motion: reduce) {{ .spin, .spin-rev, .pulse {{ animation: none; }} }}
  </style>

  <rect width="{W}" height="{H}" fill="url(#bg)"/>
  <rect width="{W}" height="{H}" fill="url(#ambient)"/>

  <g>
    {streak_rects}
  </g>
  <g filter="url(#soft)">
    {beams}
  </g>

  <!-- portal -->
  <circle cx="{px}" cy="{py}" r="235" fill="url(#halo)"/>
  <circle cx="{px}" cy="{py}" r="150" fill="url(#halo)" filter="url(#soft)"/>
  <g class="pulse">
    <circle cx="{px}" cy="{py}" r="110" fill="url(#core)"/>
  </g>
  <g fill="none" filter="url(#glow)">
    <circle cx="{px}" cy="{py}" r="113" stroke="#FFC27A" stroke-width="2.2" opacity="0.9"/>
    <circle cx="{px}" cy="{py}" r="96" stroke="#FFF1CF" stroke-width="1.2" stroke-dasharray="1 5" opacity="0.8"/>
  </g>
  <g class="spin" fill="none" filter="url(#glow)">
    <circle cx="{px}" cy="{py}" r="126" stroke="#FF8A3D" stroke-width="1.6" stroke-dasharray="36 9 4 9" opacity="0.85"/>
    {ring_arcs(px, py, 146, 6, rng, 3, "#FF5A3D", 0.7)}
    <circle cx="{px}" cy="{py}" r="162" stroke="#FF6A3D" stroke-width="7" stroke-dasharray="1.2 13" opacity="0.35"/>
  </g>
  <g class="spin-rev" fill="none" filter="url(#glow)">
    {ring_arcs(px, py, 136, 5, rng, 1.4, "#FFD08A", 0.7)}
    {ring_arcs(px, py, 184, 4, rng, 1.2, "#FF2E63", 0.55)}
  </g>

  <g class="spin-rev" filter="url(#glow)">
    {sparks(px, py, rng)}
  </g>

  <!-- tau silhouette with rim light -->
  <path d="{tau}" fill="none" stroke="#FFE3B0" stroke-width="28" stroke-linecap="round" stroke-linejoin="round" filter="url(#soft)" opacity="1"/>
  <path d="{tau}" fill="none" stroke="#14060D" stroke-width="18" stroke-linecap="round" stroke-linejoin="round"/>

  <!-- triangles -->
  <g fill="none" stroke-linejoin="miter" filter="url(#glow)">
    <path d="{tri(*OUTER)}" stroke="#FF2E63" stroke-width="3"/>
    <path d="{tri(*INNER)}" stroke="#FF4D4D" stroke-width="3.5"/>
  </g>

  <!-- floor, glints and reflection -->
  <rect x="0" y="{FLOOR}" width="{W}" height="{H - FLOOR}" fill="#05030C" opacity="0.55"/>
  <ellipse cx="{px}" cy="{FLOOR + 22}" rx="300" ry="34" fill="url(#halo)" opacity="0.8"/>
  <g opacity="0.45" transform="translate(0 {2 * FLOOR}) scale(1 -1)">
    <path d="{tri(*OUTER)}" fill="none" stroke="#FF2E63" stroke-width="2" filter="url(#soft)"/>
    <circle cx="{px}" cy="{py}" r="120" fill="url(#halo)"/>
  </g>
  <rect x="0" y="{FLOOR - 1}" width="{W}" height="2" fill="url(#floor)" filter="url(#glow)"/>
  <g>
    {glint_svg}
  </g>

  <text x="{CX}" y="{H - 26}" text-anchor="middle" font-family="ui-monospace, SFMono-Regular, Menlo, Consolas, monospace" font-size="13" letter-spacing="7" fill="#F6B9A6" opacity="0.75">DÜŞÜNÜR · DOKUNUR · HATIRLAR</text>

  <rect width="{W}" height="{H}" fill="url(#vignette)"/>
</svg>
"""


def mark():
    S = 256
    c = S / 2
    cy = 150
    apex, base, half = 34, 214, 104
    tau = tau_path(c, cy + 2, 64)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {S} {S}" width="{S}" height="{S}" role="img" aria-label="tau">
  <title>tau</title>
  <defs>
    <linearGradient id="m-bg" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#07091D"/>
      <stop offset="1" stop-color="#13061A"/>
    </linearGradient>
    <radialGradient id="m-halo">
      <stop offset="0" stop-color="#FF8A3D" stop-opacity="0.8"/>
      <stop offset="0.55" stop-color="#FF4D2E" stop-opacity="0.25"/>
      <stop offset="1" stop-color="#C2183C" stop-opacity="0"/>
    </radialGradient>
    <radialGradient id="m-core">
      <stop offset="0" stop-color="#FFF8E6"/>
      <stop offset="0.35" stop-color="#FFD58A"/>
      <stop offset="0.7" stop-color="#FF8A30"/>
      <stop offset="1" stop-color="#FF4D2E"/>
    </radialGradient>
    <filter id="m-glow" x="-20%" y="-20%" width="140%" height="140%">
      <feGaussianBlur stdDeviation="3" result="b"/>
      <feMerge><feMergeNode in="b"/><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
    <filter id="m-soft" x="-50%" y="-50%" width="200%" height="200%">
      <feGaussianBlur stdDeviation="4"/>
    </filter>
  </defs>
  <rect width="{S}" height="{S}" rx="56" fill="url(#m-bg)"/>
  <circle cx="{c}" cy="{cy}" r="92" fill="url(#m-halo)"/>
  <circle cx="{c}" cy="{cy}" r="52" fill="url(#m-core)"/>
  <circle cx="{c}" cy="{cy}" r="60" fill="none" stroke="#FFB25C" stroke-width="2.5" stroke-dasharray="22 6 3 6" filter="url(#m-glow)" opacity="0.9"/>
  <path d="M{c} {apex} L{c + half} {base} L{c - half} {base} Z" fill="none" stroke="#FF2E63" stroke-width="7" stroke-linejoin="round" filter="url(#m-glow)"/>
  <path d="{tau}" fill="none" stroke="#FFD9A0" stroke-width="18" stroke-linecap="round" stroke-linejoin="round" filter="url(#m-soft)" opacity="0.85"/>
  <path d="{tau}" fill="none" stroke="#14060D" stroke-width="12" stroke-linecap="round" stroke-linejoin="round"/>
</svg>
"""


OUT.mkdir(parents=True, exist_ok=True)
(OUT / "tau-hero.svg").write_text(hero())
(OUT / "tau-mark.svg").write_text(mark())
print("written", OUT / "tau-hero.svg", OUT / "tau-mark.svg")
