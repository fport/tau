/**
 * Sigils: an ember sigil for every tau and sub-tau (ADR 0013 §8).
 *
 * `character(seed)` turns a seed into an SVG string. A sigil is drawn in the language of the
 * brand hero (docs/brand/tau-hero.svg): a sharp neon triangle, double-stroked from its hue's
 * first colour to its second, with a flame of layered, angular tongues burning inside it on
 * a white-hot core, and HUD accents around it: a partial τ ring with a comet head, instrument
 * ticks, square fragments, a scan line and a reflecting floor. No faces, no mascot parts.
 *
 * - **Taus and sub-taus.** A tau's sigil is the richer one: a second triangle (nested,
 *   inverted or an echo behind it) and the ring. A sub-tau's is a smaller triangle with a
 *   single flame and no ring, burning in its tau's hue, so it reads as one of the family.
 *   The kind comes from the seed (see `kindOf`) unless `opts.kind` says otherwise.
 * - **Seeds.** A tau's seed is its address (`alice.example.com`, `tau.example.com/@alice`);
 *   a sub-tau's is its address and name (`alice.example.com/coach`). The part before the last
 *   `/name` is the owner, whose hue the sub-tau inherits. The same seed always gives the same
 *   sigil, in the site and in tau-host alike.
 * - **Frozen order.** The traits are drawn from one PRNG in a fixed order (see `traits`), the
 *   same for both kinds. Adding a hue, a frame or a flame, or drawing in another order,
 *   changes every existing sigil; a golden test pins a few seeds so such a change is
 *   deliberate.
 * - **Small sizes.** Below 34 px (graph nodes of sub-taus, list icons) only the triangle, the
 *   flame and a tau's ring arc are drawn, with strokes kept at least ~1.3 px; below 64 px
 *   the fine HUD details (ticks, fragments, the scan line) are left out.
 * - **Pure and safe.** No DOM, no clock, no randomness beyond the seed. The SVG has no ids
 *   (many sigils share a page), no gradients (they would need ids), no `<style>` and no
 *   `style` attributes (the pages' CSP is `style-src 'self'`): colours are presentation
 *   attributes, and the motion is CSS classes (`ch-flame`, `ch-flame-in`, `ch-core`,
 *   `ch-ring`, `ch-ring-back`, `ch-spark`, `ch-ember`) that `cloud/shared/theme.css` animates
 *   and stops under `prefers-reduced-motion`.
 * - **Accessible.** The root is `role="img"` with an `aria-label` (the given label, or an
 *   English description of the sigil). An empty label marks it decorative instead
 *   (`aria-hidden="true"`), for places where the name is written next to it.
 */

// ---------------------------------------------------------------------------------------
// Hues and traits

/**
 * The hues: the fire family of the brand palette (Signal, Ember, Flare and a deep infra
 * crimson) and a minority of cold fires. Each has a triangle colour (`a`), the inner line of
 * the double stroke (`b`), three flame layers from the outside in (`f1`–`f3`) and a
 * white-hot core. The order is part of every sigil: append only with intent.
 */
export const HUES = [
  {
    name: "signal",
    word: "signal red",
    cold: false,
    a: "#ff2e63",
    b: "#ff7a3d",
    f1: "#ff2e63",
    f2: "#ff7a3d",
    f3: "#ffb25c",
    core: "#fff4e0",
  },
  {
    name: "ember",
    word: "ember orange",
    cold: false,
    a: "#ff7a3d",
    b: "#ffb25c",
    f1: "#ff4d2e",
    f2: "#ff9a3d",
    f3: "#ffd08a",
    core: "#fff4e0",
  },
  {
    name: "flare",
    word: "flare amber",
    cold: false,
    a: "#ffb25c",
    b: "#ffe2ad",
    f1: "#ff7a3d",
    f2: "#ffb25c",
    f3: "#ffe6b8",
    core: "#fffaf0",
  },
  {
    name: "infra",
    word: "infra crimson",
    cold: false,
    a: "#e3194c",
    b: "#ff5a3d",
    f1: "#a3123a",
    f2: "#ff2e63",
    f3: "#ff8a5c",
    core: "#ffe1d2",
  },
  {
    name: "ion",
    word: "ion blue",
    cold: true,
    a: "#3d8bff",
    b: "#5ce1ff",
    f1: "#2f5fff",
    f2: "#3db8ff",
    f3: "#9be9ff",
    core: "#eefaff",
  },
  {
    name: "plasma",
    word: "plasma violet",
    cold: true,
    a: "#a259ff",
    b: "#ff4fd8",
    f1: "#7b3dff",
    f2: "#c05cff",
    f3: "#f5a3ff",
    core: "#fcf0ff",
  },
  {
    name: "toxic",
    word: "toxic green",
    cold: true,
    a: "#2ee886",
    b: "#c6ff3d",
    f1: "#0fae55",
    f2: "#4dff6a",
    f3: "#d8ff8a",
    core: "#f4ffe6",
  },
] as const;

export type Hue = (typeof HUES)[number];
export type HueName = Hue["name"];
/** How often each hue is drawn: the fire family about four times in five. */
const HUE_WEIGHTS = [5, 4, 3, 3, 1.6, 1.6, 1.2];

/** The shape of the triangle. */
export const FRAMES = ["equilateral", "tall", "split", "broken", "notched", "chamfered"] as const;
export type FrameKind = (typeof FRAMES)[number];

/** A tau's second triangle: inside it, inverted inside it, or a larger echo behind it. */
export const SECONDS = ["nested", "inverted", "echo"] as const;
export type SecondKind = (typeof SECONDS)[number];

export type Kind = "tau" | "sub";

/** Everything that makes one sigil; `traits(seed)` draws it. */
export interface Traits {
  kind: Kind;
  hue: HueName;
  frame: FrameKind;
  /** A tau's second triangle; a sub-tau has none. */
  second: SecondKind | "none";
  /** Flame tongues: 1–3 for a tau, always 1 for a sub-tau. */
  tongues: 1 | 2 | 3;
  /** How high the flame burns, 0 (low) … 3 (up to the apex). */
  height: 0 | 1 | 2 | 3;
  /** Where the flame leans: -1 (left) … 1 (right). */
  lean: number;
  /** Sparks over the flame, 0–4. */
  sparks: number;
  /** Two ember fragments floating beside the flame. */
  embers: boolean;
  /** The τ ring's arc in degrees (0: none, a sub-tau) and where it starts. */
  ringSpan: number;
  ringStart: number;
  /** Instrument ticks around the ring (0: none). */
  ticks: number;
  /** A scan line at this fraction of the triangle's height, or null. */
  scan: number | null;
  /** Small square HUD fragments, 0–3. */
  frags: number;
  /** A reflecting floor line under the triangle. */
  floor: boolean;
  /** The phase of the motion, 0..7, so a row of sigils never flickers in step. */
  phase: number;
}

export interface CharacterOptions {
  /** Width and height in CSS pixels (default 96). */
  size?: number;
  /** Motion classes (default true). */
  animated?: boolean;
  /** The accessible name; "" makes the sigil decorative (default: a description). */
  label?: string;
  /** A tau or a sub-tau (default: from the seed, see `kindOf`). */
  kind?: Kind;
}

/** FNV-1a, 32 bits, over the UTF-16 code units of the seed. */
export function fnv1a(text: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return h >>> 0;
}

/** xorshift32 seeded from the hash; returns numbers in [0, 1). */
function prng(seed: string): () => number {
  let x = fnv1a(seed) || 0x9e3779b9;
  // A few rounds so that seeds differing in their last character spread out at once.
  const next = () => {
    x ^= x << 13;
    x >>>= 0;
    x ^= x >>> 17;
    x ^= x << 5;
    x >>>= 0;
    return x / 4294967296;
  };
  for (let i = 0; i < 4; i++) next();
  return next;
}

function pick<T>(rnd: () => number, list: readonly T[]): T {
  return list[Math.floor(rnd() * list.length)] as T;
}

/** A weighted pick: `weights[i]` for `list[i]`. */
function weighted<T>(rnd: () => number, list: readonly T[], weights: readonly number[]): T {
  const total = weights.reduce((sum, weight) => sum + weight, 0);
  let roll = rnd() * total;
  for (let i = 0; i < list.length; i++) {
    roll -= weights[i] ?? 0;
    if (roll < 0) return list[i] as T;
  }
  return list[list.length - 1] as T;
}

const HUE_NAMES: readonly HueName[] = HUES.map((hue) => hue.name);

/**
 * The owner of a sub-tau's seed: everything before its last `/name`. A tau's seed (an
 * address, or `host/@handle`) has none.
 */
export function ownerOf(seed: string): string | null {
  const slash = seed.lastIndexOf("/");
  if (slash <= 0 || slash === seed.length - 1) return null;
  return seed[slash + 1] === "@" ? null : seed.slice(0, slash);
}

/** A seed's kind: a sub-tau when it ends in `/name` after an address, else a tau. */
export function kindOf(seed: string): Kind {
  return ownerOf(seed) === null ? "tau" : "sub";
}

/** The hue a seed draws for itself: always the first draw. */
function ownHue(seed: string): HueName {
  return weighted(prng(seed), HUE_NAMES, HUE_WEIGHTS);
}

/**
 * The sigil of a seed. Every trait is drawn for both kinds in the same frozen order; a
 * sub-tau then takes its owner's hue, one tongue, and no second triangle, ring or ticks.
 */
export function traits(seed: string, kind: Kind = kindOf(seed)): Traits {
  const rnd = prng(seed);
  const hue = weighted(rnd, HUE_NAMES, HUE_WEIGHTS);
  const frame = weighted(rnd, FRAMES, [3, 2.5, 2, 2, 2, 2]);
  const second = weighted(rnd, SECONDS, [3, 2, 2]);
  const tongues = weighted(rnd, [1, 2, 3] as const, [3, 4, 2]);
  const height = pick(rnd, [0, 1, 2, 3] as const);
  const lean = weighted(rnd, [-1, -0.5, 0, 0.5, 1], [1, 1.5, 2, 1.5, 1]);
  const sparks = weighted(rnd, [0, 1, 2, 3, 4], [1.5, 2, 2, 1.5, 1]);
  const embers = rnd() < 0.45;
  const ringSpan = pick(rnd, [150, 210, 270, 320]);
  const ringStart = Math.floor(rnd() * 12) * 30;
  const ticks = weighted(rnd, [0, 12, 24, 36], [1, 2, 2, 1.5]);
  const scanOn = rnd() < 0.4;
  const scanAt = pick(rnd, [0.36, 0.5, 0.64]);
  const frags = weighted(rnd, [0, 1, 2, 3], [1, 2, 2, 1]);
  const floor = rnd() < 0.55;
  const phase = Math.floor(rnd() * 8);
  const sub = kind === "sub";
  const owner = sub ? ownerOf(seed) : null;
  return {
    kind,
    hue: owner !== null ? ownHue(owner) : hue,
    frame,
    second: sub ? "none" : second,
    tongues: sub ? 1 : tongues,
    height,
    lean,
    sparks,
    embers,
    ringSpan: sub ? 0 : ringSpan,
    ringStart,
    ticks: sub ? 0 : ticks,
    scan: scanOn ? scanAt : null,
    frags,
    floor,
    phase,
  };
}

// ---------------------------------------------------------------------------------------
// Geometry

type Pt = readonly [number, number];

/** The triangle's base line, the floor under it and the ring's centre and radius. */
const BASE_Y = 84;
const FLOOR_Y = 90;
const RING: Pt = [50, 52];
const RING_R = 45;
/** A sub-tau's sigil is drawn this much smaller, standing on the same base line. */
const SUB_SCALE = 0.84;

/** Numbers as short as SVG allows: one decimal, no trailing ".0". */
function n(value: number): string {
  const rounded = Math.round(value * 10) / 10;
  return Object.is(rounded, -0) ? "0" : String(rounded);
}

function lerp(a: Pt, b: Pt, t: number): Pt {
  return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
}

function toward(from: Pt, to: Pt, distance: number): Pt {
  const dx = to[0] - from[0];
  const dy = to[1] - from[1];
  const length = Math.hypot(dx, dy) || 1;
  return [from[0] + (dx / length) * distance, from[1] + (dy / length) * distance];
}

/** `point` scaled by `sx`, `sy` about `origin`. */
function scaled(point: Pt, origin: Pt, sx: number, sy = sx): Pt {
  return [origin[0] + (point[0] - origin[0]) * sx, origin[1] + (point[1] - origin[1]) * sy];
}

function clamp(value: number, low: number, high: number): number {
  return Math.min(high, Math.max(low, value));
}

/** A path through `points`, closed or open. */
function d(points: readonly Pt[], closed = true): string {
  const body = points.map((point, i) => `${i === 0 ? "M" : "L"}${n(point[0])} ${n(point[1])}`);
  return `${body.join("")}${closed ? "Z" : ""}`;
}

function polar(center: Pt, radius: number, degrees: number): Pt {
  const angle = (degrees * Math.PI) / 180;
  return [center[0] + Math.cos(angle) * radius, center[1] + Math.sin(angle) * radius];
}

/** An arc of the circle around `center`, clockwise from `from` to `to` degrees. */
function arc(center: Pt, radius: number, from: number, to: number): string {
  const start = polar(center, radius, from);
  const end = polar(center, radius, to);
  const large = to - from > 180 ? 1 : 0;
  return `M${n(start[0])} ${n(start[1])}A${n(radius)} ${n(radius)} 0 ${large} 1 ${n(end[0])} ${n(end[1])}`;
}

interface Stroke {
  points: Pt[];
  closed: boolean;
}

interface Frame {
  apex: Pt;
  left: Pt;
  right: Pt;
  /** The outline: one closed stroke, or open strokes for a broken apex. */
  strokes: Stroke[];
  /** The broken-off tip of a broken apex, floating above it. */
  shard: Stroke | null;
}

/** The apex height and half base of each frame, before a sub-tau's scale. */
const FRAME_SPECS: Record<FrameKind, readonly [number, number]> = {
  equilateral: [20, 37],
  tall: [10, 27],
  split: [17, 38],
  broken: [17, 37],
  notched: [20, 37],
  chamfered: [19, 38],
};

function frameOf(kind: FrameKind, k: number): Frame {
  const [apexY, half] = FRAME_SPECS[kind];
  const apex: Pt = [50, BASE_Y - (BASE_Y - apexY) * k];
  const left: Pt = [50 - half * k, BASE_Y];
  const right: Pt = [50 + half * k, BASE_Y];
  const base = { apex, left, right, shard: null };
  switch (kind) {
    case "equilateral":
    case "tall":
      return { ...base, strokes: [{ points: [apex, right, left], closed: true }] };
    case "split": {
      const notch: Pt = [50, apex[1] + (BASE_Y - apex[1]) * 0.2];
      return {
        ...base,
        strokes: [
          {
            points: [notch, lerp(apex, right, 0.11), right, left, lerp(apex, left, 0.11)],
            closed: true,
          },
        ],
      };
    }
    case "broken": {
      const lift = 3.5 * k;
      const up = (point: Pt): Pt => [point[0], point[1] - lift];
      return {
        ...base,
        strokes: [
          { points: [lerp(apex, left, 0.17), left, right, lerp(apex, right, 0.25)], closed: false },
        ],
        shard: {
          points: [up(lerp(apex, left, 0.1)), up(apex), up(lerp(apex, right, 0.1))],
          closed: false,
        },
      };
    }
    case "notched": {
      const centroid: Pt = [50, (apex[1] + 2 * BASE_Y) / 3];
      const notch = (from: Pt, to: Pt, t: number): Pt[] => {
        const middle = lerp(from, to, t);
        return [lerp(from, to, t - 0.06), toward(middle, centroid, 5 * k), lerp(from, to, t + 0.06)];
      };
      return {
        ...base,
        strokes: [
          {
            points: [apex, ...notch(apex, right, 0.4), right, left, ...notch(left, apex, 0.46)],
            closed: true,
          },
        ],
      };
    }
    case "chamfered": {
      const cut = 8.5 * k;
      return {
        ...base,
        strokes: [
          {
            points: [
              apex,
              toward(right, apex, cut),
              toward(right, left, cut),
              toward(left, right, cut),
              toward(left, apex, cut),
            ],
            closed: true,
          },
        ],
      };
    }
  }
}

/** The incentre and inradius of the frame's triangle. */
function incircle(frame: Frame): { center: Pt; r: number } {
  const half = frame.right[0] - 50;
  const height = BASE_Y - frame.apex[1];
  const r = (half * height) / (half + Math.hypot(half, height));
  return { center: [50, BASE_Y - r], r };
}

/** The half width of the frame's triangle at height `y`. */
function halfAt(frame: Frame, y: number): number {
  const height = BASE_Y - frame.apex[1];
  return (frame.right[0] - 50) * clamp((y - frame.apex[1]) / height, 0, 1);
}

/**
 * One flame tongue in unit space: x in -1…1 across its widest part, v in 0…1 up to its tip.
 * It bulges above its base, tapers to a sharp tip and throws one lick up from each side: an
 * angular flame, not a blob.
 */
const TONGUE: readonly Pt[] = [
  [-0.74, 0],
  [-1, 0.2],
  [-0.8, 0.42],
  [-0.74, 0.64],
  [-0.44, 0.5],
  [-0.3, 0.76],
  [0, 1],
  [0.2, 0.7],
  [0.42, 0.82],
  [0.5, 0.52],
  [0.8, 0.44],
  [1, 0.22],
  [0.76, 0],
];

interface Tongue {
  /** The middle of its base. */
  base: Pt;
  width: number;
  height: number;
  lean: number;
  /** Mirror the template, so a tongue leaning left has its notches on the other side. */
  mirror: boolean;
}

function tonguePoints(tongue: Tongue, sx = 1, sy = 1): Pt[] {
  return TONGUE.map(([x, v]) => {
    const u = (tongue.mirror ? -x : x) + tongue.lean * 0.4 * v ** 1.4;
    const point: Pt = [tongue.base[0] + u * tongue.width, tongue.base[1] - v * tongue.height];
    return scaled(point, tongue.base, sx, sy);
  });
}

function tipOf(tongue: Tongue): Pt {
  return [tongue.base[0] + tongue.lean * 0.4 * tongue.width, tongue.base[1] - tongue.height];
}

/** The flame heights, as fractions of the room from the flame's base to the apex. */
const HEIGHTS = [0.56, 0.68, 0.8, 0.94] as const;

function tonguesOf(frame: Frame, tr: Traits, k: number): { main: Tongue; sides: Tongue[] } {
  const baseY = BASE_Y - 3.5 * k;
  const room = baseY - frame.apex[1];
  const height = room * HEIGHTS[tr.height];
  const width = halfAt(frame, baseY) * (tr.tongues === 1 ? 0.46 : 0.38);
  const mirror = tr.lean < 0;
  const side = mirror ? -1 : 1;
  if (tr.tongues === 2) {
    const main: Tongue = { base: [50 - side * width * 0.3, baseY], width, height, lean: tr.lean, mirror };
    const twin: Tongue = {
      base: [50 + side * width * 0.72, baseY],
      width: width * 0.72,
      height: height * 0.7,
      lean: side * 0.7,
      mirror: !mirror,
    };
    return { main, sides: [twin] };
  }
  const main: Tongue = { base: [50, baseY], width, height, lean: tr.lean, mirror };
  if (tr.tongues === 1) return { main, sides: [] };
  const flank = (sign: number, scale: number): Tongue => ({
    base: [50 + sign * width * 0.9, baseY],
    width: width * 0.62,
    height: height * scale,
    lean: sign * 0.65,
    mirror: sign < 0,
  });
  return { main, sides: [flank(-1, mirror ? 0.64 : 0.54), flank(1, mirror ? 0.54 : 0.64)] };
}

/** A small diamond: a spark. */
function diamond(center: Pt, size: number): Pt[] {
  const [x, y] = center;
  return [
    [x, y - size],
    [x + size * 0.62, y],
    [x, y + size],
    [x - size * 0.62, y],
  ];
}

function escapeXml(text: string): string {
  return text
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&apos;");
}

// ---------------------------------------------------------------------------------------
// Drawing

/** How much the sigil draws at a size: 0 below 34 px, 1 below 64 px, 2 from there. */
function levelOf(size: number): 0 | 1 | 2 {
  return size < 34 ? 0 : size < 64 ? 1 : 2;
}

interface Pen {
  level: 0 | 1 | 2;
  /** A stroke width in viewBox units, never thinner than `minPx` on screen. */
  width(units: number, minPx?: number): string;
}

function penFor(size: number): Pen {
  return {
    level: levelOf(size),
    width: (units, minPx = 0.9) => n(Math.max(units, (minPx * 100) / size)),
  };
}

function strokeSvg(stroke: Stroke, attributes: string): string {
  return `<path d="${d(stroke.points, stroke.closed)}" ${attributes}/>`;
}

function frameSvg(frame: Frame, hue: Hue, pen: Pen): string {
  const all = frame.shard === null ? frame.strokes : [...frame.strokes, frame.shard];
  const main = `fill="none" stroke="${hue.a}" stroke-width="${pen.width(2.2, 1.3)}" stroke-linejoin="miter" stroke-miterlimit="12"`;
  let out = "";
  if (pen.level > 0) {
    // The neon's bloom: a wide, faint stroke under the line (a filter would need an id).
    const bloom = `fill="none" stroke="${hue.a}" stroke-opacity=".16" stroke-width="${pen.width(6.5)}" stroke-linejoin="miter" stroke-miterlimit="12"`;
    out += all.map((stroke) => strokeSvg(stroke, bloom)).join("");
  }
  out += all.map((stroke) => strokeSvg(stroke, main)).join("");
  if (pen.level > 0) {
    // The double stroke: the same outline, inset toward the incentre, in the second colour.
    const { center, r } = incircle(frame);
    const factor = (r - (pen.level === 2 ? 3.4 : 4.2)) / r;
    const inset = frame.strokes.map((stroke) => ({
      points: stroke.points.map((point) => scaled(point, center, factor)),
      closed: stroke.closed,
    }));
    const line = `fill="none" stroke="${hue.b}" stroke-opacity=".9" stroke-width="${pen.width(0.9, 0.7)}" stroke-linejoin="miter" stroke-miterlimit="12"`;
    out += inset.map((stroke) => strokeSvg(stroke, line)).join("");
  }
  return out;
}

/** A tau's second triangle, drawn behind the flame. `echo` goes behind everything. */
function secondSvg(frame: Frame, tr: Traits, hue: Hue, pen: Pen): string {
  if (tr.second === "none" || pen.level === 0) return "";
  const { apex, left, right } = frame;
  switch (tr.second) {
    case "nested": {
      const { center } = incircle(frame);
      const points = [apex, right, left].map((point) => scaled(point, center, 0.5));
      return `<path d="${d(points)}" fill="none" stroke="${hue.b}" stroke-opacity=".85" stroke-width="${pen.width(1.3, 0.8)}" stroke-linejoin="miter"/>`;
    }
    case "inverted": {
      const centroid: Pt = [50, (apex[1] + 2 * BASE_Y) / 3];
      const points = [lerp(apex, left, 0.5), lerp(apex, right, 0.5), [50, BASE_Y] as Pt].map(
        (point) => scaled(point, centroid, 0.82),
      );
      return `<path d="${d(points)}" fill="${hue.a}" fill-opacity=".07" stroke="${hue.b}" stroke-opacity=".8" stroke-width="${pen.width(1.1, 0.8)}" stroke-linejoin="miter"/>`;
    }
    case "echo": {
      const grow = Math.min(1.16, (BASE_Y - 3) / (BASE_Y - apex[1]));
      const origin: Pt = [50, BASE_Y];
      const points = [apex, right, left].map((point) => scaled(point, origin, grow));
      return `<path d="${d(points)}" fill="none" stroke="${hue.a}" stroke-opacity=".42" stroke-width="${pen.width(1, 0.8)}" stroke-linejoin="miter"/>`;
    }
  }
}

function flameSvg(frame: Frame, tr: Traits, hue: Hue, pen: Pen, k: number): string {
  const { main, sides } = tonguesOf(frame, tr, k);
  const layer = (tongue: Tongue, sx: number, sy: number, fill: string, opacity = 1) =>
    `<path d="${d(tonguePoints(tongue, sx, sy))}" fill="${fill}"${opacity < 1 ? ` fill-opacity="${opacity}"` : ""}/>`;
  const glow = pen.level > 0 ? layer(main, 1.3, 1.12, hue.f1, 0.14) : "";
  const flanks = sides.map((tongue) => layer(tongue, 1, 1, hue.f1, 0.9) + layer(tongue, 0.62, 0.7, hue.f2)).join("");
  const outer = layer(main, 1, 1, hue.f1) + layer(main, 0.7, 0.76, hue.f2);
  const inner = pen.level > 0 ? `<g class="ch-flame-in">${layer(main, 0.44, 0.52, hue.f3)}</g>` : "";
  const [bx, by] = main.base;
  const burner =
    pen.level > 0
      ? `<path d="M${n(bx - main.width * 0.7)} ${n(by)}H${n(bx + main.width * 0.7)}" stroke="${hue.core}" stroke-opacity=".8" stroke-width="${pen.width(0.8, 0.6)}"/>`
      : "";
  const core = `<g class="ch-core">${layer(main, 0.22, 0.3, hue.core)}${burner}</g>`;
  return `<g class="ch-flame">${glow}${flanks}${outer}${inner}${core}</g>`;
}

function sparksSvg(frame: Frame, tr: Traits, hue: Hue, pen: Pen, k: number): string {
  if (pen.level === 0 || tr.sparks === 0) return "";
  const count = pen.level === 1 ? Math.min(2, tr.sparks) : tr.sparks;
  const tip = tipOf(tonguesOf(frame, tr, k).main);
  const offsets: readonly Pt[] = [
    [-5, 6],
    [6, 10],
    [-9, 15],
    [10, 19],
  ];
  let out = "";
  for (let i = 0; i < count; i++) {
    const [dx, dy] = offsets[i]!;
    const center: Pt = [tip[0] + (dx + tr.lean * 3) * k, Math.max(3 + i * 2.5, tip[1] - dy * k)];
    const size = [2.3, 1.9, 1.6, 1.3][i]! * k * (pen.level === 1 ? 1.3 : 1);
    out += `<path class="ch-spark ch-s${i}" d="${d(diamond(center, size))}" fill="${i % 2 === 0 ? hue.f3 : hue.core}"/>`;
  }
  return out;
}

function embersSvg(frame: Frame, tr: Traits, hue: Hue, pen: Pen, k: number): string {
  if (pen.level === 0 || !tr.embers) return "";
  const shard = (x: number, y: number, s: number, tilt: number) =>
    `<path class="ch-ember" d="${d([
      [x + tilt, y - s],
      [x + s * 0.7, y + s * 0.6],
      [x - s * 0.7, y + s * 0.4],
    ])}" fill="${hue.f2}" fill-opacity=".85"/>`;
  const yLeft = BASE_Y - (BASE_Y - frame.apex[1]) * 0.42;
  const yRight = BASE_Y - (BASE_Y - frame.apex[1]) * 0.3;
  return (
    shard(50 - halfAt(frame, yLeft) * 0.62, yLeft, 1.9 * k, -0.8) +
    shard(50 + halfAt(frame, yRight) * 0.66, yRight, 1.5 * k, 0.6)
  );
}

function ringSvg(tr: Traits, hue: Hue, pen: Pen): string {
  if (tr.ringSpan === 0) return "";
  const from = tr.ringStart - 90;
  const to = from + tr.ringSpan;
  const line = `fill="none" stroke="${hue.a}" stroke-width="${pen.width(0.9, 1.1)}"`;
  let ring = `<path d="${arc(RING, RING_R, from, to)}" ${line} stroke-opacity="${pen.level === 0 ? ".8" : ".5"}"/>`;
  // The comet: a bright head at the arc's end, its tail brighter toward it.
  const tail = Math.min(26, tr.ringSpan * 0.18);
  ring += `<path d="${arc(RING, RING_R, to - tail, to)}" fill="none" stroke="${hue.f3}" stroke-width="${pen.width(1.8, 1.4)}"/>`;
  if (pen.level > 0) {
    const head = polar(RING, RING_R, to);
    const s = 1.8;
    ring += `<rect x="${n(head[0] - s)}" y="${n(head[1] - s)}" width="${n(2 * s)}" height="${n(2 * s)}" fill="${hue.core}"/>`;
  }
  if (pen.level === 2) {
    for (let i = 0; i < tr.frags; i++) {
      const at = polar(RING, RING_R, to + 40 + i * 47);
      const wide = i % 2 === 0;
      const w = wide ? 5 : 2.4;
      const h = wide ? 1.4 : 2.4;
      ring += `<rect x="${n(at[0] - w / 2)}" y="${n(at[1] - h / 2)}" width="${n(w)}" height="${n(h)}" fill="${hue.b}" fill-opacity=".75"/>`;
    }
  }
  let ticks = "";
  if (pen.level === 2 && tr.ticks > 0) {
    let path = "";
    for (let i = 0; i < tr.ticks; i++) {
      const angle = (i * 360) / tr.ticks;
      const major = i % (tr.ticks / 4) === 0;
      const a = polar(RING, RING_R + 2.5, angle);
      const b = polar(RING, RING_R + (major ? 6.5 : 4.5), angle);
      path += `M${n(a[0])} ${n(a[1])}L${n(b[0])} ${n(b[1])}`;
    }
    ticks = `<g class="ch-ring-back"><path d="${path}" fill="none" stroke="${hue.a}" stroke-opacity=".45" stroke-width="${pen.width(0.6, 0.6)}"/></g>`;
  }
  return `${ticks}<g class="ch-ring">${ring}</g>`;
}

/** A sub-tau has no ring; its fragments mark the floor's ends instead. */
function subFragsSvg(tr: Traits, frame: Frame, hue: Hue, pen: Pen): string {
  if (tr.kind !== "sub" || pen.level < 2 || tr.frags === 0) return "";
  const half = frame.right[0] - 50;
  const spots: readonly Pt[] = [
    [50 - half - 7, BASE_Y - 2],
    [50 + half + 5, BASE_Y - 9],
    [50 + half + 8, BASE_Y - 3],
  ];
  return spots
    .slice(0, tr.frags)
    .map(([x, y], i) => {
      const w = i === 0 ? 4.5 : 2.2;
      const h = i === 0 ? 1.3 : 2.2;
      return `<rect x="${n(x - w / 2)}" y="${n(y - h / 2)}" width="${n(w)}" height="${n(h)}" fill="${hue.b}" fill-opacity=".7"/>`;
    })
    .join("");
}

/** The reflecting floor: a line brightest under the flame, and the triangle's reflection. */
function floorSvg(tr: Traits, frame: Frame, hue: Hue, pen: Pen): string {
  if (!tr.floor || pen.level === 0) return "";
  const half = frame.right[0] - 50;
  const width = pen.width(0.8, 0.7);
  const segment = (x1: number, x2: number, color: string, opacity: string) =>
    `<path d="M${n(x1)} ${FLOOR_Y}H${n(x2)}" stroke="${color}" stroke-opacity="${opacity}" stroke-width="${width}"/>`;
  let out =
    segment(50 - half - 10, 50 - half * 0.45, hue.a, ".3") +
    segment(50 - half * 0.45, 50 + half * 0.45, hue.f3, ".8") +
    segment(50 + half * 0.45, 50 + half + 10, hue.a, ".3");
  if (pen.level === 2) {
    const drop = (BASE_Y - frame.apex[1]) * 0.12;
    out +=
      `<path d="M${n(50 - half * 0.5)} ${FLOOR_Y + 1.5}L${n(50 + half * 0.5)} ${FLOOR_Y + 1.5}L50 ${n(FLOOR_Y + 1.5 + drop)}Z" fill="${hue.a}" fill-opacity=".06" stroke="${hue.a}" stroke-opacity=".22" stroke-width="${pen.width(0.7, 0.6)}"/>`;
  }
  return out;
}

function scanSvg(tr: Traits, frame: Frame, hue: Hue, pen: Pen): string {
  if (tr.scan === null || pen.level < 2) return "";
  const y = frame.apex[1] + (BASE_Y - frame.apex[1]) * tr.scan;
  const reach = halfAt(frame, y) + 9;
  const x1 = 50 - reach;
  const x2 = 50 + reach;
  return (
    `<path d="M${n(x1)} ${n(y)}H${n(x2)}M${n(x1)} ${n(y - 1.6)}V${n(y + 1.6)}M${n(x2)} ${n(y - 1.6)}V${n(y + 1.6)}" ` +
    `fill="none" stroke="${hue.b}" stroke-opacity=".32" stroke-width="${pen.width(0.5, 0.5)}"/>`
  );
}

const FRAME_WORDS: Record<FrameKind, string> = {
  equilateral: "equilateral",
  tall: "tall",
  split: "split-apex",
  broken: "broken-apex",
  notched: "notched",
  chamfered: "chamfered",
};

const SECOND_WORDS: Record<SecondKind | "none", string> = {
  none: "",
  nested: " with a nested triangle",
  inverted: " with an inverted inner triangle",
  echo: " with an echo triangle",
};

const TONGUE_WORDS = { 1: "single", 2: "twin", 3: "triple" } as const;

export function hueOf(name: HueName): Hue {
  return HUES.find((hue) => hue.name === name) ?? HUES[0];
}

/** An English description of a sigil, the default accessible name. */
export function describe(tr: Traits): string {
  const what = tr.kind === "sub" ? "ember sub-sigil" : "ember sigil";
  const frame = `${FRAME_WORDS[tr.frame]} triangle${SECOND_WORDS[tr.second]}`;
  return `${what}: ${frame}, ${TONGUE_WORDS[tr.tongues]} flame, ${hueOf(tr.hue).word}`;
}

/**
 * The sigil of `seed` as an SVG string (viewBox 0 0 100 100). A tau's ring is centred at
 * (50, 52); a sub-tau's triangle stands on the same base line, smaller.
 *
 * @param seed a tau's address, or `<address>/<name>` for a sub-tau
 * @param opts `size` in CSS pixels (96), `animated` motion (true), `label` its accessible
 *   name (a description; "" makes it decorative), `kind` (from the seed)
 */
export function character(seed: string, opts: CharacterOptions = {}): string {
  const size = opts.size ?? 96;
  const animated = opts.animated ?? true;
  const tr = traits(seed, opts.kind ?? kindOf(seed));
  const hue = hueOf(tr.hue);
  const pen = penFor(size);
  const k = tr.kind === "sub" ? SUB_SCALE : 1;
  const frame = frameOf(tr.frame, k);
  const behind = tr.second === "echo" ? secondSvg(frame, tr, hue, pen) : "";
  const inside = tr.second === "echo" ? "" : secondSvg(frame, tr, hue, pen);

  const parts = [
    ringSvg(tr, hue, pen),
    behind,
    floorSvg(tr, frame, hue, pen),
    subFragsSvg(tr, frame, hue, pen),
    inside,
    flameSvg(frame, tr, hue, pen, k),
    frameSvg(frame, hue, pen),
    embersSvg(frame, tr, hue, pen, k),
    sparksSvg(frame, tr, hue, pen, k),
    scanSvg(tr, frame, hue, pen),
  ].join("");

  const label = opts.label ?? describe(tr);
  const a11y =
    label === ""
      ? `aria-hidden="true" focusable="false"`
      : `role="img" aria-label="${escapeXml(label)}"`;
  const classes = [
    "ch",
    `ch-${tr.kind}`,
    `ch-l${pen.level}`,
    ...(animated ? ["ch-anim", `ch-p${tr.phase}`] : []),
  ].join(" ");
  return (
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" width="${n(size)}" height="${n(size)}" ` +
    `class="${classes}" data-hue="${tr.hue}" ${a11y}>${parts}</svg>`
  );
}
