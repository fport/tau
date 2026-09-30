/**
 * The landing page's universe without the DOM (client/landing.ts draws it): the stars, where
 * the taus float, the camera and its projection, where the universe sits next to the hero's
 * text, the portal's timeline, and where a click on a tau leads.
 *
 * Pure and deterministic: the same snapshot always gives the same sky, so the Worker's tests
 * can check it.
 */

import type { PublicLink } from "../src/snapshot";
import type { PageLanguage } from "./messages";
import { HANDLE, personPath, universePath } from "./paths";

export const TWO_PI = Math.PI * 2;

export const clamp = (value: number, low = 0, high = 1): number =>
  Math.min(high, Math.max(low, value));
export const lerp = (a: number, b: number, t: number): number => a + (b - a) * t;
/** Where `t` is between `a` and `b`, as 0..1. */
export const span = (t: number, a: number, b: number): number => clamp((t - a) / (b - a));
export const easeOut = (t: number): number => 1 - Math.pow(1 - t, 3);
export const easeIn = (t: number): number => t * t * t;
export const easeInOut = (t: number): number =>
  t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;

/** FNV-1a, 32 bits. */
export function hash(text: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return h >>> 0;
}

/** Mulberry32: a small seeded generator, 0 ≤ n < 1. */
export function random(seed: number): () => number {
  let s = seed >>> 0;
  return () => {
    s = (s + 0x6d2b79f5) >>> 0;
    let t = s;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export interface Point {
  x: number;
  y: number;
  z: number;
}

// ---------------------------------------------------------------------------------------
// The sky

export interface Star extends Point {
  /** 1, 1.5 or 2.2: most stars are specks. */
  size: number;
  /** 0.18..1, mostly dim. */
  alpha: number;
  /** The twinkle's phase. */
  phase: number;
  /** A few stars burn warm; the rest are grey-white. */
  warm: boolean;
}

/** Stars never come closer to the centre than this, so the taus float in clear space. */
export const STAR_INNER = 260;
export const STAR_OUTER = 9_060;

/** A sphere of stars around the taus, denser towards the middle. */
export function stars(count: number, seed = 7): Star[] {
  const next = random(seed);
  const out: Star[] = [];
  for (let i = 0; i < count; i++) {
    const theta = next() * TWO_PI;
    const phi = Math.acos(2 * next() - 1);
    const radius = STAR_INNER + Math.pow(next(), 1.5) * (STAR_OUTER - STAR_INNER);
    const bright = next();
    out.push({
      x: Math.sin(phi) * Math.cos(theta) * radius,
      y: Math.cos(phi) * radius,
      z: Math.sin(phi) * Math.sin(theta) * radius,
      size: bright > 0.985 ? 2.2 : bright > 0.9 ? 1.5 : 1,
      alpha: 0.18 + Math.pow(bright, 3) * 0.82,
      phase: next() * TWO_PI,
      warm: next() < 0.06,
    });
  }
  return out;
}

// ---------------------------------------------------------------------------------------
// The taus

export interface Orbit {
  name: string;
  /** Visitors can talk to it on its page. */
  web: boolean;
  radius: number;
  /** Radians per second; the sign is the direction. */
  speed: number;
  phase: number;
  tilt: number;
  turn: number;
}

/** A tau's sub-taus as orbits around it, seeded by its address. */
export function orbits(address: string, subs: readonly { name: string; web?: boolean }[]): Orbit[] {
  const next = random(hash(address));
  return subs.map((sub, i) => ({
    name: sub.name,
    web: sub.web === true,
    radius: 26 + i * 11 + next() * 6,
    speed: ((0.35 + next() * 0.3) * (next() < 0.5 ? -1 : 1)) / (1 + i * 0.35),
    phase: next() * TWO_PI,
    tilt: 0.35 + next() * 0.9,
    turn: next() * TWO_PI,
  }));
}

/** Where a sub-tau on `orbit` is at `time`, around a tau at `centre`. */
export function orbitPoint(centre: Point, orbit: Orbit, angle: number): Point {
  const lx = Math.cos(angle) * orbit.radius;
  const ly = Math.sin(angle) * orbit.radius * Math.sin(orbit.tilt);
  const lz = Math.sin(angle) * orbit.radius * Math.cos(orbit.tilt);
  const ct = Math.cos(orbit.turn);
  const st = Math.sin(orbit.turn);
  return { x: centre.x + lx * ct - lz * st, y: centre.y + ly, z: centre.z + lx * st + lz * ct };
}

/** How far apart two linked taus settle. */
export const LINK_LENGTH = 240;

/**
 * Where each tau floats: seeded on a shell by its address, then relaxed so taus push each
 * other apart and linked taus pull together, flattened a little, and centred on the origin.
 * One tau sits at the origin.
 */
export function positions(
  addresses: readonly string[],
  links: readonly PublicLink[],
): Map<string, Point> {
  const points = addresses.map((address) => {
    const next = random(hash(address) ^ 0x9e3779b9);
    const theta = next() * TWO_PI;
    const phi = Math.acos(2 * next() - 1);
    const radius = 140 + next() * 200;
    return {
      x: Math.sin(phi) * Math.cos(theta) * radius,
      y: Math.cos(phi) * radius * 0.55,
      z: Math.sin(phi) * Math.sin(theta) * radius,
    };
  });
  const index = new Map(addresses.map((address, i) => [address, i]));
  const springs = links
    .map((link) => [index.get(link.a), index.get(link.b)] as const)
    .filter(
      (pair): pair is readonly [number, number] => pair[0] !== undefined && pair[1] !== undefined,
    );

  if (points.length === 1) points[0] = { x: 0, y: 0, z: 0 };
  const steps = points.length > 1 ? 260 : 0;
  for (let step = 0; step < steps; step++) {
    const cool = 1 - step / steps;
    for (let i = 0; i < points.length; i++) {
      const a = points[i]!;
      for (let j = i + 1; j < points.length; j++) {
        const b = points[j]!;
        let dx = a.x - b.x;
        let dy = a.y - b.y;
        let dz = a.z - b.z;
        const d2 = Math.max(dx * dx + dy * dy + dz * dz, 100);
        const push = (52_000 / d2) * cool;
        const d = Math.sqrt(d2);
        dx /= d;
        dy /= d;
        dz /= d;
        a.x += dx * push;
        a.y += dy * push * 0.6;
        a.z += dz * push;
        b.x -= dx * push;
        b.y -= dy * push * 0.6;
        b.z -= dz * push;
      }
    }
    for (const [i, j] of springs) {
      const a = points[i]!;
      const b = points[j]!;
      const dx = b.x - a.x;
      const dy = b.y - a.y;
      const dz = b.z - a.z;
      const d = Math.max(Math.hypot(dx, dy, dz), 1);
      const pull = ((d - LINK_LENGTH) / d) * 0.06 * cool;
      a.x += dx * pull;
      a.y += dy * pull;
      a.z += dz * pull;
      b.x -= dx * pull;
      b.y -= dy * pull;
      b.z -= dz * pull;
    }
    for (const point of points) {
      point.x *= 0.992;
      point.y *= 0.985;
      point.z *= 0.992;
    }
  }

  if (points.length > 0) {
    const mean = points.reduce((acc, p) => ({ x: acc.x + p.x, y: acc.y + p.y, z: acc.z + p.z }), {
      x: 0,
      y: 0,
      z: 0,
    });
    for (const point of points) {
      point.x -= mean.x / points.length;
      point.y -= mean.y / points.length;
      point.z -= mean.z / points.length;
    }
  }
  return new Map(addresses.map((address, i) => [address, points[i]!]));
}

/** The radius the camera frames: the farthest tau, but never less than a few taus' room. */
export function reachOf(points: Iterable<Point>): number {
  let reach = 0;
  for (const p of points) reach = Math.max(reach, Math.hypot(p.x, p.y, p.z));
  return Math.max(reach + 60, 220);
}

// ---------------------------------------------------------------------------------------
// The camera

/** An orbiting camera: it looks at `target`, turned by `yaw` and `pitch`, from `dist`. */
export interface Camera {
  target: Point;
  yaw: number;
  pitch: number;
  dist: number;
  /** Where the target lands on screen, in CSS pixels from the top left. */
  cx: number;
  cy: number;
  /** Focal length in CSS pixels. */
  focal: number;
}

export interface Projected {
  x: number;
  y: number;
  /** Depth in front of the camera. */
  z: number;
  /** CSS pixels per world unit at this depth. */
  scale: number;
}

/** Nothing closer to the camera than this is drawn. */
export const NEAR = 6;

/** Projects a world point, or null when it is behind the camera. `dist` overrides the camera's. */
export type Projector = (p: Point, dist?: number) => Projected | null;

/** A projector for one frame: the camera's turns are worked out once, not for every point. */
export function projector(cam: Camera): Projector {
  const cy = Math.cos(cam.yaw);
  const sy = Math.sin(cam.yaw);
  const cp = Math.cos(cam.pitch);
  const sp = Math.sin(cam.pitch);
  return (p, dist = cam.dist) => {
    const dx = p.x - cam.target.x;
    const dy = p.y - cam.target.y;
    const dz = p.z - cam.target.z;
    const x1 = dx * cy - dz * sy;
    const z1 = dx * sy + dz * cy;
    const y2 = dy * cp - z1 * sp;
    const z2 = dy * sp + z1 * cp + dist;
    if (z2 < NEAR) return null;
    const scale = cam.focal / z2;
    return { x: cam.cx + x1 * scale, y: cam.cy + y2 * scale, z: z2, scale };
  };
}

export function project(cam: Camera, p: Point, dist = cam.dist): Projected | null {
  return projector(cam)(p, dist);
}

export interface Rect {
  left: number;
  top: number;
  right: number;
  bottom: number;
}

export interface Frame {
  /** Where the universe's centre goes on screen. */
  cx: number;
  cy: number;
  /** The camera distance that fits `reach` into the free space. */
  dist: number;
  /** Side by side with the text, or above it. */
  layout: "side" | "stacked";
}

/** The narrowest free column next to the text that still holds the universe. */
const SIDE_MIN = 340;

/**
 * Where the universe sits: beside the hero's text when there is room on its right, above it
 * otherwise, and as far away as it takes for `reach` to fit that space.
 */
export function frame(
  width: number,
  height: number,
  copy: Rect,
  top: number,
  reach: number,
  focal: number,
): Frame {
  const side = width - copy.right >= SIDE_MIN && width >= height;
  const box: Rect = side
    ? { left: copy.right, top, right: width, bottom: height }
    : { left: 0, top, right: width, bottom: Math.max(top + 160, copy.top) };
  const room = Math.max(80, Math.min(box.right - box.left, box.bottom - box.top) / 2);
  return {
    cx: (box.left + box.right) / 2,
    cy: (box.top + box.bottom) / 2,
    // A margin: the universe turns, nearer taus project larger, and labels need room.
    dist: clamp((focal * reach) / (room * 0.8), 420, 4_200),
    layout: side ? "side" : "stacked",
  };
}

// ---------------------------------------------------------------------------------------
// The portal: the timeline of the opening, in seconds

export const PORTAL = {
  /** The floor line draws out from the middle. */
  floor: [0.05, 0.7],
  /** The outer triangle rises from the floor; the inner one follows. */
  outer: [0.35, 1.15],
  inner: [0.6, 1.4],
  /** The mark lights inside, then fades as the portal fills with stars. */
  mark: [0.9, 1.3, 1.6, 2.0],
  /** Stars show through the portal. */
  sky: [1.3, 1.9],
  /** The portal grows past the screen while the camera flies in. */
  grow: [1.9, 2.9],
  fly: [1.8, 3.2],
  /** The flash as the camera comes through, and the taus lighting one by one. */
  through: [2.7, 3.0],
  ignite: 2.95,
  /** The universe settles next to the text; the text arrives. */
  settle: [2.8, 3.8],
  open: 3.5,
} as const;

/** How far the camera starts, inside the portal. */
export const PORTAL_DISTANCE = 5_600;

// ---------------------------------------------------------------------------------------
// Links

/** Where a click on a tau leads: its person page with a handle, else its place on /universe. */
export function tauPath(
  tau: { address: string; handle?: string | null },
  lang: PageLanguage,
): string {
  const handle = typeof tau.handle === "string" && HANDLE.test(tau.handle) ? tau.handle : null;
  return handle !== null ? personPath(handle, lang) : universePath(tau.address, lang);
}
