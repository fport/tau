/**
 * Characters: a small creature for every tau and sub-tau (ADR 0013 §8).
 *
 * `character(seed)` turns a seed into an SVG string. The creature is built on the tau
 * triangle: a triangle body (sharp, rounded, tall, squat, notched, leaning or cut flat),
 * split into a lit and a shaded facet, in one colour of a fixed neon palette, with eyes, a
 * mouth, sometimes a mark, cheeks, feet or a neon glow, and at most one accessory.
 *
 * - **Seeds.** A tau's seed is its address (`alice.example.com`,
 *   `tau.example.com/@alice`); a sub-tau's is its address and name
 *   (`alice.example.com/coach`). The same seed always gives the same creature, in the site
 *   and in tau-host alike.
 * - **Frozen order.** The traits are drawn from one PRNG in a fixed order (see `traits`).
 *   Adding a palette colour, a body or an accessory, or drawing in another order, changes
 *   every existing creature; a golden test pins a few seeds so such a change is deliberate.
 * - **Pure and safe.** No DOM, no clock, no randomness beyond the seed. The SVG has no ids
 *   (many creatures share a page), no `<style>` and no `style` attributes (the pages'
 *   CSP is `style-src 'self'`): colours are presentation attributes, and the idle motion is
 *   CSS classes (`ch-body`, `ch-eyes`, `ch-wiggle`, `ch-bob`, `ch-shadow`) that
 *   `cloud/shared/theme.css` animates and stops under `prefers-reduced-motion`.
 * - **Accessible.** The root is `role="img"` with an `aria-label` (the given label, or an
 *   English description of the creature). An empty label marks it decorative instead
 *   (`aria-hidden="true"`), for places where the name is written next to it.
 */

// ---------------------------------------------------------------------------------------
// Palette and traits

/** The neon palette. The order is part of every creature: append only with intent. */
export const PALETTE = [
  { name: "red", hex: "#ff2e3e" },
  { name: "magenta", hex: "#ff2bd6" },
  { name: "pink", hex: "#ff6b9a" },
  { name: "orange", hex: "#ff7a3d" },
  { name: "amber", hex: "#ffb020" },
  { name: "yellow", hex: "#ffe14d" },
  { name: "lime", hex: "#b6ff2e" },
  { name: "teal", hex: "#2effc0" },
  { name: "cyan", hex: "#22e4ff" },
  { name: "blue", hex: "#3d7bff" },
  { name: "violet", hex: "#9b6bff" },
  { name: "white", hex: "#e8ecf1" },
] as const;

export type ColorName = (typeof PALETTE)[number]["name"];

export const BODIES = ["sharp", "rounded", "tall", "squat", "notched", "lean", "cut"] as const;
export type BodyKind = (typeof BODIES)[number];

export const EYES = ["round", "big", "dots", "pixel", "happy", "sleepy", "mono", "wink"] as const;
export type EyeKind = (typeof EYES)[number];

export const MOUTHS = ["none", "smile", "grin", "o", "flat", "fang", "cat"] as const;
export type MouthKind = (typeof MOUTHS)[number];

export const ACCESSORIES = [
  "none",
  "beret",
  "glasses",
  "sunglasses",
  "visor",
  "antenna",
  "horns",
  "halo",
  "headphones",
  "crown",
  "sprout",
  "scarf",
  "monocle",
  "bow",
] as const;
export type AccessoryKind = (typeof ACCESSORIES)[number];

export const MARKS = ["none", "core", "stripe", "dots", "chevron", "circuit"] as const;
export type MarkKind = (typeof MARKS)[number];

export const FEET = ["none", "stubs", "points"] as const;
export type FeetKind = (typeof FEET)[number];

/** Everything that makes one creature; `traits(seed)` draws it. */
export interface Traits {
  color: ColorName;
  body: BodyKind;
  /** The corner radius choice of the body (0 is its sharp variant, 1 its soft one). */
  soft: 0 | 1;
  /** How low the face sits, as a fraction of the body's height. */
  face: number;
  eyes: EyeKind;
  eyeScale: number;
  spread: number;
  /** Where the pupils look: -1..1 on each axis. */
  gaze: readonly [number, number];
  mouth: MouthKind;
  accessory: AccessoryKind;
  /** The accessory's colour: chrome, dark, or a palette colour other than the body's. */
  accessoryColor: string;
  mark: MarkKind;
  cheeks: boolean;
  feet: FeetKind;
  glow: boolean;
  /** A lean for accessories that can tilt (beret, antenna, sprout): -1..1. */
  tilt: number;
  /** The phase of the idle motion, 0..7, so a row of creatures does not move in step. */
  phase: number;
}

export interface CharacterOptions {
  /** Width and height in CSS pixels (default 96). */
  size?: number;
  /** Idle motion classes (default true). */
  animated?: boolean;
  /** The accessible name; "" makes the creature decorative (default: a description). */
  label?: string;
}

const INK = "#07080a";
const CHROME = "#e8ecf1";
const DARK = "#15181e";
const WHITE = "#ffffff";

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

const GAZES: readonly (readonly [number, number])[] = [
  [0, 0],
  [0, 0],
  [-1, 0],
  [1, 0],
  [0, -1],
  [0.7, 0.6],
  [-0.7, 0.6],
];

/** The creature of a seed. The order of the draws below is frozen. */
export function traits(seed: string): Traits {
  const rnd = prng(seed);
  const color = pick(rnd, PALETTE).name;
  const body = pick(rnd, BODIES);
  const soft = rnd() < 0.5 ? 0 : 1;
  const face = pick(rnd, [0.54, 0.58, 0.62]);
  const eyes = weighted(rnd, EYES, [4, 2, 2, 2, 1.5, 1.5, 1, 1]);
  const eyeScale = pick(rnd, [0.9, 1, 1.15]);
  const spread = pick(rnd, [0.9, 1, 1.1]);
  const gaze = pick(rnd, GAZES);
  const mouth = weighted(rnd, MOUTHS, [1, 3, 2, 1.5, 1, 1, 1]);
  const accessory = weighted(rnd, ACCESSORIES, [3, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1]);
  const others = PALETTE.filter((entry) => entry.name !== color).map((entry) => entry.hex);
  const accent = pick(rnd, others);
  const accessoryColor = pick(rnd, [CHROME, DARK, accent]);
  const mark = weighted(rnd, MARKS, [3, 2, 1, 1, 1, 1]);
  const cheeks = rnd() < 0.3;
  const feet = weighted(rnd, FEET, [2, 1.5, 1]);
  const glow = rnd() < 0.4;
  const tilt = Math.round((rnd() * 2 - 1) * 100) / 100;
  const phase = Math.floor(rnd() * 8);
  return {
    color,
    body,
    soft,
    face,
    eyes,
    eyeScale,
    spread,
    gaze,
    mouth,
    accessory,
    accessoryColor,
    mark,
    cheeks,
    feet,
    glow,
    tilt,
    phase,
  };
}

// ---------------------------------------------------------------------------------------
// Geometry

type Pt = readonly [number, number];

interface Shape {
  /** Clockwise from the top: the apex, or the middle of a flat top. */
  points: Pt[];
  /** The corner radius of each point (0 keeps it sharp). */
  radius: number[];
  /** The last point of the shaded (right) facet before the ridge turns back to the top. */
  facetLast: number;
  /** Where the ridge from the top meets the bottom. */
  ridgeFoot: Pt;
  /** The outline's left and right lines, top to bottom, for placing the face and things. */
  left: readonly [Pt, Pt];
  right: readonly [Pt, Pt];
}

const BASE_Y = 88;

function shapeOf(body: BodyKind, soft: 0 | 1): Shape {
  const r = soft === 1 ? 6.5 : 1.6;
  switch (body) {
    case "sharp":
    case "rounded": {
      const radius = body === "rounded" ? 11 : 1.6;
      return {
        points: [
          [50, 20],
          [88, BASE_Y],
          [12, BASE_Y],
        ],
        radius: [radius, radius, radius],
        facetLast: 1,
        ridgeFoot: [50, BASE_Y],
        left: [
          [50, 20],
          [12, BASE_Y],
        ],
        right: [
          [50, 20],
          [88, BASE_Y],
        ],
      };
    }
    case "tall":
      return {
        points: [
          [50, 13],
          [76, BASE_Y],
          [24, BASE_Y],
        ],
        radius: [r, r, r],
        facetLast: 1,
        ridgeFoot: [50, BASE_Y],
        left: [
          [50, 13],
          [24, BASE_Y],
        ],
        right: [
          [50, 13],
          [76, BASE_Y],
        ],
      };
    case "squat":
      return {
        points: [
          [50, 38],
          [94, BASE_Y],
          [6, BASE_Y],
        ],
        radius: [r, r, r],
        facetLast: 1,
        ridgeFoot: [50, BASE_Y],
        left: [
          [50, 38],
          [6, BASE_Y],
        ],
        right: [
          [50, 38],
          [94, BASE_Y],
        ],
      };
    case "notched":
      return {
        points: [
          [50, 20],
          [88, BASE_Y],
          [59, BASE_Y],
          [50, 77],
          [41, BASE_Y],
          [12, BASE_Y],
        ],
        radius: [r, r, 1.2, 0, 1.2, r],
        facetLast: 2,
        ridgeFoot: [50, 77],
        left: [
          [50, 20],
          [12, BASE_Y],
        ],
        right: [
          [50, 20],
          [88, BASE_Y],
        ],
      };
    case "lean":
      return {
        points: [
          [40, 20],
          [88, BASE_Y],
          [14, BASE_Y],
        ],
        radius: [r, r, r],
        facetLast: 1,
        ridgeFoot: [47, BASE_Y],
        left: [
          [40, 20],
          [14, BASE_Y],
        ],
        right: [
          [40, 20],
          [88, BASE_Y],
        ],
      };
    case "cut":
      return {
        points: [
          [50, 27],
          [57.5, 27],
          [90, BASE_Y],
          [10, BASE_Y],
          [42.5, 27],
        ],
        radius: [0, soft === 1 ? 3 : 1, r, r, soft === 1 ? 3 : 1],
        facetLast: 2,
        ridgeFoot: [50, BASE_Y],
        left: [
          [42.5, 27],
          [10, BASE_Y],
        ],
        right: [
          [57.5, 27],
          [90, BASE_Y],
        ],
      };
  }
}

function lerp(a: Pt, b: Pt, t: number): Pt {
  return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
}

function mid(a: Pt, b: Pt): Pt {
  return lerp(a, b, 0.5);
}

function toward(from: Pt, to: Pt, distance: number): Pt {
  const dx = to[0] - from[0];
  const dy = to[1] - from[1];
  const length = Math.hypot(dx, dy) || 1;
  return [from[0] + (dx / length) * distance, from[1] + (dy / length) * distance];
}

/** Numbers as short as SVG allows: one decimal, no trailing ".0". */
function n(value: number): string {
  const rounded = Math.round(value * 10) / 10;
  return Object.is(rounded, -0) ? "0" : String(rounded);
}

function p(point: Pt): string {
  return `${n(point[0])} ${n(point[1])}`;
}

interface Corner {
  a: Pt;
  v: Pt;
  b: Pt;
}

/** Each point's rounded corner: from `a` on the edge in, around `v`, to `b` on the edge out. */
function corners(shape: Shape): Corner[] {
  const { points, radius } = shape;
  return points.map((v, i) => {
    const prev = points[(i - 1 + points.length) % points.length]!;
    const next = points[(i + 1) % points.length]!;
    const room = Math.min(
      Math.hypot(prev[0] - v[0], prev[1] - v[1]),
      Math.hypot(next[0] - v[0], next[1] - v[1]),
    );
    const r = Math.min(radius[i] ?? 0, room / 2 - 0.01);
    return r <= 0 ? { a: v, v, b: v } : { a: toward(v, prev, r), v, b: toward(v, next, r) };
  });
}

interface Outline {
  /** The body's outline. */
  body: string;
  /** The shaded right facet, inside the outline. */
  facet: string;
  /** The top of the head: the middle of the rounded apex, or of the flat top. */
  top: Pt;
}

/**
 * The outline and the shaded facet, both starting at the top of the head. The apex curve is
 * split in two halves at its middle (de Casteljau at t = 0.5), so the facet follows the
 * outline exactly and needs no clip path.
 */
function outline(shape: Shape): Outline {
  const cs = corners(shape);
  const first = cs[0]!;
  const top: Pt = [
    (first.a[0] + 2 * first.v[0] + first.b[0]) / 4,
    (first.a[1] + 2 * first.v[1] + first.b[1]) / 4,
  ];
  const rightControl = mid(first.v, first.b);
  const leftControl = mid(first.a, first.v);
  const around = (from: number, to: number) => {
    let d = "";
    for (let i = from; i <= to; i++) {
      const c = cs[i]!;
      d += `L${p(c.a)}Q${p(c.v)} ${p(c.b)}`;
    }
    return d;
  };
  const start = `M${p(top)}Q${p(rightControl)} ${p(first.b)}`;
  const body = `${start}${around(1, cs.length - 1)}L${p(first.a)}Q${p(leftControl)} ${p(top)}Z`;
  const facet = `${start}${around(1, shape.facetLast)}L${p(shape.ridgeFoot)}Z`;
  return { body, facet, top };
}

/** The x of a line at height y (extended beyond its ends when needed). */
function xAt(line: readonly [Pt, Pt], y: number): number {
  const [a, b] = line;
  const t = (y - a[1]) / (b[1] - a[1] || 1);
  return a[0] + (b[0] - a[0]) * t;
}

function clamp(value: number, low: number, high: number): number {
  return Math.min(high, Math.max(low, value));
}

/** A colour mixed toward another: `amount` 0 is `hex`, 1 is `other`. */
function mix(hex: string, other: string, amount: number): string {
  const read = (value: string) => [1, 3, 5].map((i) => parseInt(value.slice(i, i + 2), 16));
  const a = read(hex);
  const b = read(other);
  const out = a.map((channel, i) => Math.round(channel + ((b[i] ?? 0) - channel) * amount));
  return `#${out.map((channel) => channel.toString(16).padStart(2, "0")).join("")}`;
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

interface Face {
  cx: number;
  eyeY: number;
  halfWidth: number;
  er: number;
  dx: number;
  /** The x of the ridge at eye level: an eye right of it sits on the shaded facet. */
  ridgeX: number;
  mouthY: number;
}

function faceOf(shape: Shape, top: Pt, tr: Traits): Face {
  const eyeY = top[1] + (BASE_Y - top[1]) * tr.face;
  const xl = xAt(shape.left, eyeY);
  const xr = xAt(shape.right, eyeY);
  const halfWidth = (xr - xl) / 2;
  const cx = (xl + xr) / 2;
  const er = clamp(halfWidth * 0.22, 3.8, 6.8) * tr.eyeScale;
  let dx = clamp(halfWidth * 0.4, 6.5, 12.5) * tr.spread;
  if (dx + er > halfWidth - 2.5) dx = Math.max(er + 0.8, halfWidth - 2.5 - er);
  const ridgeX = xAt([top, shape.ridgeFoot], eyeY);
  return { cx, eyeY, halfWidth, er, dx, ridgeX, mouthY: eyeY + er + 5.5 };
}

function eyesSvg(face: Face, tr: Traits, base: string, shade: string, hidden: boolean): string {
  if (hidden) return "";
  const { cx, eyeY, er, dx, ridgeX } = face;
  const [gx, gy] = tr.gaze;
  const pupil = (x: number, r: number) =>
    `<circle cx="${n(x + gx * r * 0.45)}" cy="${n(eyeY + gy * r * 0.4)}" r="${n(r)}" fill="${INK}"/>` +
    `<circle cx="${n(x + gx * r * 0.45 - r * 0.35)}" cy="${n(eyeY + gy * r * 0.4 - r * 0.35)}" r="${n(r * 0.32)}" fill="${WHITE}"/>`;
  const sclera = (x: number, r: number) =>
    `<circle cx="${n(x)}" cy="${n(eyeY)}" r="${n(r)}" fill="${WHITE}" stroke="${INK}" stroke-width="1"/>`;
  const happy = (x: number) =>
    `<path d="M${n(x - er * 0.9)} ${n(eyeY + er * 0.35)}Q${n(x)} ${n(eyeY - er * 0.95)} ${n(x + er * 0.9)} ${n(eyeY + er * 0.35)}" fill="none" stroke="${INK}" stroke-width="1.8" stroke-linecap="round"/>`;
  const left = cx - dx;
  const right = cx + dx;
  let inner = "";
  let blinks = true;
  switch (tr.eyes) {
    case "round":
      inner = [left, right].map((x) => sclera(x, er) + pupil(x, er * 0.52)).join("");
      break;
    case "big":
      inner = [left, right].map((x) => sclera(x, er * 1.3) + pupil(x, er * 0.62)).join("");
      break;
    case "dots":
      inner = [left, right].map((x) => pupil(x, er * 0.58)).join("");
      break;
    case "pixel": {
      const s = er * 0.95;
      inner = [left, right]
        .map(
          (x) =>
            `<rect x="${n(x - s)}" y="${n(eyeY - s)}" width="${n(2 * s)}" height="${n(2 * s)}" fill="${WHITE}" stroke="${INK}" stroke-width="1"/>` +
            `<rect x="${n(x - s * 0.45 + gx * s * 0.4)}" y="${n(eyeY - s * 0.45 + gy * s * 0.4)}" width="${n(s * 0.9)}" height="${n(s * 0.9)}" fill="${INK}"/>`,
        )
        .join("");
      break;
    }
    case "happy":
      inner = happy(left) + happy(right);
      blinks = false;
      break;
    case "sleepy":
      inner = [left, right]
        .map((x) => {
          const lid = x > ridgeX ? shade : base;
          return (
            sclera(x, er) +
            pupil(x, er * 0.5) +
            `<path d="M${n(x - er - 0.6)} ${n(eyeY + 0.4)}A${n(er + 0.6)} ${n(er + 0.6)} 0 0 1 ${n(x + er + 0.6)} ${n(eyeY + 0.4)}Z" fill="${lid}"/>` +
            `<path d="M${n(x - er)} ${n(eyeY + 0.4)}H${n(x + er)}" stroke="${INK}" stroke-width="1.2" stroke-linecap="round"/>`
          );
        })
        .join("");
      break;
    case "mono": {
      const r = er * 1.55;
      inner = sclera(cx, r) + pupil(cx, r * 0.5);
      break;
    }
    case "wink":
      inner = sclera(left, er) + pupil(left, er * 0.52) + happy(right);
      break;
  }
  return blinks ? `<g class="ch-eyes">${inner}</g>` : `<g>${inner}</g>`;
}

function mouthSvg(face: Face, tr: Traits): string {
  const x = face.cx;
  const y = face.mouthY;
  const w = Math.max(3, face.er * 1.1);
  const line = `fill="none" stroke="${INK}" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"`;
  switch (tr.mouth) {
    case "none":
      return "";
    case "smile":
      return `<path d="M${n(x - w)} ${n(y)}Q${n(x)} ${n(y + w * 0.9)} ${n(x + w)} ${n(y)}" ${line}/>`;
    case "grin":
      return `<path d="M${n(x - w)} ${n(y)}Q${n(x)} ${n(y + w * 1.6)} ${n(x + w)} ${n(y)}Z" fill="${INK}"/>`;
    case "o":
      return `<ellipse cx="${n(x)}" cy="${n(y + 1)}" rx="${n(w * 0.42)}" ry="${n(w * 0.55)}" fill="${INK}"/>`;
    case "flat":
      return `<path d="M${n(x - w * 0.7)} ${n(y + 1)}H${n(x + w * 0.7)}" ${line}/>`;
    case "fang": {
      const h = w * 0.9;
      const u = w * 0.35;
      const t = (u + w) / (2 * w);
      const at = y + 2 * t * (1 - t) * h;
      return (
        `<path d="M${n(x - w)} ${n(y)}Q${n(x)} ${n(y + h)} ${n(x + w)} ${n(y)}" ${line}/>` +
        `<path d="M${n(x + u - 1.3)} ${n(at - 0.3)}L${n(x + u + 1.3)} ${n(at - 0.5)}L${n(x + u + 0.2)} ${n(at + 2.4)}Z" fill="${WHITE}" stroke="${INK}" stroke-width=".6" stroke-linejoin="round"/>`
      );
    }
    case "cat":
      return `<path d="M${n(x - w)} ${n(y)}Q${n(x - w / 2)} ${n(y + w * 0.8)} ${n(x)} ${n(y)}Q${n(x + w / 2)} ${n(y + w * 0.8)} ${n(x + w)} ${n(y)}" ${line}/>`;
  }
}

function cheeksSvg(face: Face, tr: Traits): string {
  if (!tr.cheeks || tr.eyes === "mono") return "";
  const tint = tr.color === "pink" || tr.color === "red" || tr.color === "magenta";
  const fill = tint ? WHITE : "#ff6b9a";
  const opacity = tint ? 0.4 : 0.6;
  const y = face.eyeY + face.er + 2.6;
  return [face.cx - face.dx - face.er * 0.35, face.cx + face.dx + face.er * 0.35]
    .map(
      (x) =>
        `<ellipse cx="${n(x)}" cy="${n(y)}" rx="${n(face.er * 0.55)}" ry="${n(face.er * 0.32)}" fill="${fill}" fill-opacity="${opacity}"/>`,
    )
    .join("");
}

function markSvg(shape: Shape, face: Face, tr: Traits): string {
  if (tr.mark === "none") return "";
  const y = Math.max(face.eyeY + (BASE_Y - face.eyeY) * 0.62, face.mouthY + 7.5);
  if (y > BASE_Y - 4) return "";
  const xl = xAt(shape.left, y);
  const xr = xAt(shape.right, y);
  const x = (xl + xr) / 2;
  switch (tr.mark) {
    case "core": {
      const s = 4.2;
      return (
        `<path d="M${n(x)} ${n(y - s * 1.35)}L${n(x + s * 1.3)} ${n(y + s)}L${n(x - s * 1.3)} ${n(y + s)}Z" fill="${WHITE}" fill-opacity=".35"/>` +
        `<path d="M${n(x)} ${n(y - s * 0.7)}L${n(x + s * 0.7)} ${n(y + s * 0.55)}L${n(x - s * 0.7)} ${n(y + s * 0.55)}Z" fill="${WHITE}"/>`
      );
    }
    case "stripe":
      return `<path d="M${n(xl + 4)} ${n(y)}H${n(xr - 4)}" stroke="${INK}" stroke-opacity=".35" stroke-width="2.6"/>`;
    case "dots":
      return [-4.5, 0, 4.5]
        .map(
          (offset) =>
            `<circle cx="${n(x + offset)}" cy="${n(y)}" r="1.4" fill="${INK}" fill-opacity=".5"/>`,
        )
        .join("");
    case "chevron":
      return `<path d="M${n(x - 5)} ${n(y - 2)}L${n(x)} ${n(y + 2.5)}L${n(x + 5)} ${n(y - 2)}" fill="none" stroke="${INK}" stroke-opacity=".5" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>`;
    case "circuit":
      return (
        `<path d="M${n(x - 7)} ${n(y - 1)}H${n(x - 1.5)}V${n(y + 2.5)}H${n(x + 6)}" fill="none" stroke="${WHITE}" stroke-opacity=".6" stroke-width="1.1"/>` +
        `<circle cx="${n(x - 7)}" cy="${n(y - 1)}" r="1.2" fill="${WHITE}" fill-opacity=".8"/>` +
        `<circle cx="${n(x + 6)}" cy="${n(y + 2.5)}" r="1.2" fill="${WHITE}" fill-opacity=".8"/>`
      );
  }
}

function feetSvg(shape: Shape, tr: Traits, shade: string): string {
  if (tr.feet === "none" || tr.body === "notched") return "";
  const x = shape.ridgeFoot[0];
  const spread = Math.min(12, (xAt(shape.right, BASE_Y) - xAt(shape.left, BASE_Y)) * 0.18);
  if (tr.feet === "stubs") {
    return [x - spread, x + spread]
      .map(
        (fx) =>
          `<rect x="${n(fx - 3.4)}" y="${n(BASE_Y - 1)}" width="6.8" height="5.4" rx="1.2" fill="${shade}"/>`,
      )
      .join("");
  }
  return [x - spread, x + spread]
    .map(
      (fx) =>
        `<path d="M${n(fx - 3.6)} ${n(BASE_Y - 1)}H${n(fx + 3.6)}L${n(fx)} ${n(BASE_Y + 5)}Z" fill="${shade}"/>`,
    )
    .join("");
}

function accessorySvg(shape: Shape, top: Pt, face: Face, tr: Traits, colorHex: string): string {
  const c = tr.accessoryColor;
  const edge = (side: "left" | "right", t: number): Pt => {
    const line = shape[side];
    return lerp(line[0], line[1], t);
  };
  const { cx, eyeY, er, dx } = face;
  const [tx, ty] = top;
  switch (tr.accessory) {
    case "none":
      return "";
    case "beret": {
      const x = tx + 1.5 + tr.tilt * 2;
      const y = ty + 0.5;
      const angle = -10 + tr.tilt * 8;
      return (
        `<g transform="rotate(${n(angle)} ${n(x)} ${n(y)})">` +
        `<ellipse cx="${n(x)}" cy="${n(y)}" rx="13.5" ry="4.8" fill="${c}"/>` +
        `<path d="M${n(x - 12)} ${n(y + 1.6)}Q${n(x)} ${n(y + 5)} ${n(x + 12)} ${n(y + 1.6)}" fill="none" stroke="${INK}" stroke-opacity=".35" stroke-width="1"/>` +
        `<circle cx="${n(x + 1)}" cy="${n(y - 5.2)}" r="1.8" fill="${c}"/></g>`
      );
    }
    case "glasses": {
      const r = (tr.eyes === "big" ? er * 1.3 : er) + 2.6;
      const frame = `fill="${WHITE}" fill-opacity=".1" stroke="${c === DARK ? INK : c}" stroke-width="1.7"`;
      if (tr.eyes === "mono") {
        return `<circle cx="${n(cx)}" cy="${n(eyeY)}" r="${n(er * 1.55 + 2.6)}" ${frame}/>`;
      }
      return (
        `<circle cx="${n(cx - dx)}" cy="${n(eyeY)}" r="${n(r)}" ${frame}/>` +
        `<circle cx="${n(cx + dx)}" cy="${n(eyeY)}" r="${n(r)}" ${frame}/>` +
        `<path d="M${n(cx - dx + r)} ${n(eyeY)}Q${n(cx)} ${n(eyeY - 3)} ${n(cx + dx - r)} ${n(eyeY)}" fill="none" stroke="${c === DARK ? INK : c}" stroke-width="1.5"/>`
      );
    }
    case "sunglasses": {
      const w = er + 2.8;
      const h = er * 0.95 + 1.4;
      const lens = (x: number) =>
        `<rect x="${n(x - w)}" y="${n(eyeY - h)}" width="${n(2 * w)}" height="${n(2 * h)}" rx="1.4" fill="${INK}"/>` +
        `<path d="M${n(x - w + 1.6)} ${n(eyeY - h + 2)}L${n(x - w + 4.4)} ${n(eyeY - h + 2)}" stroke="${WHITE}" stroke-opacity=".7" stroke-width="1.1" stroke-linecap="round"/>`;
      const bridge = `<path d="M${n(cx - dx + w)} ${n(eyeY - h + 1.5)}H${n(cx + dx - w)}" stroke="${INK}" stroke-width="1.8"/>`;
      return dx - w < 0.5 ? lens(cx - dx) + lens(cx + dx) : lens(cx - dx) + lens(cx + dx) + bridge;
    }
    case "visor": {
      const y1 = eyeY - er - 1.8;
      const y2 = eyeY + er + 1.8;
      const band = `M${n(xAt(shape.left, y1) + 1.2)} ${n(y1)}H${n(xAt(shape.right, y1) - 1.2)}L${n(xAt(shape.right, y2) - 1.2)} ${n(y2)}H${n(xAt(shape.left, y2) + 1.2)}Z`;
      const neon = c === DARK || c === CHROME ? (colorHex === "#22e4ff" ? "#ff2e3e" : "#22e4ff") : c;
      const x1 = xAt(shape.left, eyeY) + 4;
      const x2 = xAt(shape.right, eyeY) - 4;
      const dot = cx + tr.gaze[0] * (x2 - x1) * 0.25;
      return (
        `<path d="${band}" fill="${INK}"/>` +
        `<path d="M${n(x1)} ${n(eyeY)}H${n(x2)}" stroke="${neon}" stroke-width="1.6" stroke-opacity=".9"/>` +
        `<rect x="${n(dot - 3)}" y="${n(eyeY - 1.6)}" width="6" height="3.2" fill="${neon}"/>`
      );
    }
    case "antenna": {
      const length = Math.min(13, ty - 3);
      const tip: Pt = [tx + tr.tilt * 4, ty - length];
      return (
        `<g class="ch-wiggle">` +
        `<path d="M${p(top)}L${p(tip)}" stroke="${c === DARK ? CHROME : c}" stroke-width="1.6" stroke-linecap="round"/>` +
        `<path d="M${n(tip[0])} ${n(tip[1] - 3.4)}L${n(tip[0] + 3)} ${n(tip[1] + 1.8)}H${n(tip[0] - 3)}Z" fill="${colorHex}" stroke="${WHITE}" stroke-width=".8" stroke-linejoin="round"/></g>`
      );
    }
    case "horns": {
      const fill = c === DARK ? CHROME : c;
      const horn = (side: "left" | "right") => {
        const sign = side === "left" ? -1 : 1;
        const a = edge(side, 0.14);
        const b = edge(side, 0.3);
        const tip: Pt = [a[0] + sign * 7.5, a[1] - 4.5];
        return `<path d="M${p(a)}L${p(tip)}L${p(b)}Z" fill="${fill}" stroke="${INK}" stroke-width=".8" stroke-linejoin="round"/>`;
      };
      return horn("left") + horn("right");
    }
    case "halo":
      return `<g class="ch-bob"><ellipse cx="${n(tx)}" cy="${n(ty - 7)}" rx="11" ry="3" fill="none" stroke="${c === DARK ? "#ffe14d" : c}" stroke-width="2"/></g>`;
    case "headphones": {
      const t = 0.42;
      const l = edge("left", t);
      const r = edge("right", t);
      const arc = Math.max(3, ty - 9);
      const cup = (point: Pt) =>
        `<rect x="${n(point[0] - 3)}" y="${n(point[1] - 5.5)}" width="6" height="11" rx="1.6" fill="${DARK}" stroke="${c === DARK ? CHROME : c}" stroke-width="1.2"/>`;
      return (
        `<path d="M${n(l[0])} ${n(l[1] - 4)}C${n(l[0])} ${n(arc)} ${n(r[0])} ${n(arc)} ${n(r[0])} ${n(r[1] - 4)}" fill="none" stroke="${DARK}" stroke-width="2.8"/>` +
        `<path d="M${n(l[0])} ${n(l[1] - 4)}C${n(l[0])} ${n(arc)} ${n(r[0])} ${n(arc)} ${n(r[0])} ${n(r[1] - 4)}" fill="none" stroke="${c === DARK ? CHROME : c}" stroke-width=".9"/>` +
        cup(l) +
        cup(r)
      );
    }
    case "crown": {
      const y = ty + 1;
      const fill = c === DARK || c === CHROME ? "#ffb020" : c;
      return `<path d="M${n(tx - 7)} ${n(y)}V${n(y - 6)}L${n(tx - 3.5)} ${n(y - 2.5)}L${n(tx)} ${n(y - 8.5)}L${n(tx + 3.5)} ${n(y - 2.5)}L${n(tx + 7)} ${n(y - 6)}V${n(y)}Z" fill="${fill}" stroke="${INK}" stroke-width=".8" stroke-linejoin="round"/>`;
    }
    case "sprout": {
      const green = tr.color === "lime" ? "#2effc0" : "#b6ff2e";
      const tip: Pt = [tx + tr.tilt * 3, ty - 9];
      return (
        `<g class="ch-wiggle">` +
        `<path d="M${p(top)}Q${n(tx - tr.tilt * 2)} ${n(ty - 5)} ${p(tip)}" fill="none" stroke="${green}" stroke-width="1.6" stroke-linecap="round"/>` +
        `<path d="M${p(tip)}Q${n(tip[0] - 7)} ${n(tip[1] - 5)} ${n(tip[0] - 8)} ${n(tip[1] + 1)}Q${n(tip[0] - 3)} ${n(tip[1] + 2)} ${p(tip)}Z" fill="${green}"/>` +
        `<path d="M${p(tip)}Q${n(tip[0] + 6)} ${n(tip[1] - 6)} ${n(tip[0] + 8)} ${n(tip[1] - 1)}Q${n(tip[0] + 3)} ${n(tip[1] + 1.5)} ${p(tip)}Z" fill="${green}"/></g>`
      );
    }
    case "scarf": {
      const y1 = face.mouthY + 3.5;
      const y2 = y1 + 5;
      if (y2 > BASE_Y - 6) return "";
      const fill = c === DARK ? "#ff2e3e" : c;
      const band = `M${n(xAt(shape.left, y1) - 0.6)} ${n(y1)}H${n(xAt(shape.right, y1) + 0.6)}L${n(xAt(shape.right, y2) + 0.6)} ${n(y2)}H${n(xAt(shape.left, y2) - 0.6)}Z`;
      const end = xAt(shape.right, y2) - 7;
      return (
        `<path d="${band}" fill="${fill}"/>` +
        `<path d="M${n(end)} ${n(y2 - 0.5)}H${n(end + 5)}L${n(end + 6.5)} ${n(y2 + 9)}H${n(end + 1.5)}Z" fill="${fill}" stroke="${INK}" stroke-opacity=".4" stroke-width=".7"/>`
      );
    }
    case "monocle": {
      const x = tr.eyes === "mono" ? cx : cx + dx;
      const r = (tr.eyes === "mono" ? er * 1.55 : tr.eyes === "big" ? er * 1.3 : er) + 2.8;
      const stroke = c === DARK ? "#ffb020" : c;
      return (
        `<circle cx="${n(x)}" cy="${n(eyeY)}" r="${n(r)}" fill="${WHITE}" fill-opacity=".12" stroke="${stroke}" stroke-width="1.6"/>` +
        `<path d="M${n(x + r * 0.7)} ${n(eyeY + r * 0.7)}Q${n(x + r + 3)} ${n(eyeY + 11)} ${n(x + 1)} ${n(eyeY + 17)}" fill="none" stroke="${stroke}" stroke-opacity=".8" stroke-width=".8"/>`
      );
    }
    case "bow": {
      const at = edge("right", 0.2);
      const x = at[0] - 1;
      const y = at[1];
      const fill = c === DARK ? "#ff2bd6" : c;
      return (
        `<path d="M${n(x)} ${n(y)}L${n(x - 6.5)} ${n(y - 4.5)}V${n(y + 4.5)}Z" fill="${fill}" stroke="${INK}" stroke-width=".7" stroke-linejoin="round"/>` +
        `<path d="M${n(x)} ${n(y)}L${n(x + 6.5)} ${n(y - 4.5)}V${n(y + 4.5)}Z" fill="${fill}" stroke="${INK}" stroke-width=".7" stroke-linejoin="round"/>` +
        `<rect x="${n(x - 1.6)}" y="${n(y - 1.8)}" width="3.2" height="3.6" rx=".6" fill="${INK}"/>`
      );
    }
  }
}

/** Whether the accessory covers the eyes (then no eyes are drawn and none blink). */
function coversEyes(accessory: AccessoryKind): boolean {
  return accessory === "sunglasses" || accessory === "visor";
}

const ACCESSORY_WORDS: Record<AccessoryKind, string> = {
  none: "",
  beret: "a beret",
  glasses: "glasses",
  sunglasses: "sunglasses",
  visor: "a visor",
  antenna: "an antenna",
  horns: "horns",
  halo: "a halo",
  headphones: "headphones",
  crown: "a crown",
  sprout: "a sprout",
  scarf: "a scarf",
  monocle: "a monocle",
  bow: "a bow",
};

const BODY_WORDS: Record<BodyKind, string> = {
  sharp: "sharp",
  rounded: "rounded",
  tall: "tall",
  squat: "squat",
  notched: "notched",
  lean: "leaning",
  cut: "flat-topped",
};

/** An English description of a creature, the default accessible name. */
export function describe(tr: Traits): string {
  const color = tr.color.charAt(0).toUpperCase() + tr.color.slice(1);
  const words = ACCESSORY_WORDS[tr.accessory];
  return `${color} ${BODY_WORDS[tr.body]} triangle creature${words === "" ? "" : ` with ${words}`}`;
}

/**
 * The creature of `seed` as an SVG string (viewBox 0 0 100 100).
 *
 * @param seed a tau's address, or `<address>/<name>` for a sub-tau
 * @param opts `size` in CSS pixels (96), `animated` idle motion (true), `label` its
 *   accessible name (a description; "" makes it decorative)
 */
export function character(seed: string, opts: CharacterOptions = {}): string {
  const size = opts.size ?? 96;
  const animated = opts.animated ?? true;
  const tr = traits(seed);
  const hex = PALETTE.find((entry) => entry.name === tr.color)!.hex;
  const shade = mix(hex, INK, 0.32);
  const edgeLight = mix(hex, WHITE, 0.45);
  const shape = shapeOf(tr.body, tr.soft);
  const { body, facet, top } = outline(shape);
  const face = faceOf(shape, top, tr);
  const hidden = coversEyes(tr.accessory);

  const baseLeft = xAt(shape.left, BASE_Y);
  const baseRight = xAt(shape.right, BASE_Y);
  const shadow =
    `<ellipse class="ch-shadow" cx="${n((baseLeft + baseRight) / 2)}" cy="95" ` +
    `rx="${n((baseRight - baseLeft) * 0.42)}" ry="2.6" fill="${hex}" fill-opacity=".22"/>`;
  const glow = tr.glow
    ? `<path d="${body}" fill="none" stroke="${hex}" stroke-opacity=".12" stroke-width="9" stroke-linejoin="round"/>` +
      `<path d="${body}" fill="none" stroke="${hex}" stroke-opacity=".3" stroke-width="4.5" stroke-linejoin="round"/>`
    : "";
  const shine0 = lerp(shape.left[0], shape.left[1], 0.16);
  const shine1 = lerp(shape.left[0], shape.left[1], 0.4);
  const shine =
    `<path d="M${n(shine0[0] + 3.2)} ${n(shine0[1] + 1.5)}L${n(shine1[0] + 3.2)} ${n(shine1[1])}" ` +
    `stroke="${WHITE}" stroke-opacity=".55" stroke-width="1.6" stroke-linecap="round"/>`;

  const parts = [
    glow,
    feetSvg(shape, tr, shade),
    `<path d="${body}" fill="${hex}"/>`,
    `<path d="${facet}" fill="${shade}"/>`,
    `<path d="${body}" fill="none" stroke="${edgeLight}" stroke-width="1.4" stroke-linejoin="round"/>`,
    shine,
    markSvg(shape, face, tr),
    cheeksSvg(face, tr),
    eyesSvg(face, tr, hex, shade, hidden),
    mouthSvg(face, tr),
    accessorySvg(shape, top, face, tr, hex),
  ].join("");

  const label = opts.label ?? describe(tr);
  const a11y =
    label === ""
      ? `aria-hidden="true" focusable="false"`
      : `role="img" aria-label="${escapeXml(label)}"`;
  const classes = animated ? `ch ch-anim ch-p${tr.phase}` : "ch";
  return (
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" width="${n(size)}" height="${n(size)}" ` +
    `class="${classes}" data-color="${tr.color}" ${a11y}>` +
    `${shadow}<g class="ch-body">${parts}</g></svg>`
  );
}
