/**
 * The landing page's hero: the live universe on a canvas, opened through the brand's portal.
 *
 * - The opening: on black, the floor line draws out, the hero poster's two neon triangles
 *   rise from it with the mark inside, stars show through, and the camera flies through the
 *   portal into the universe. It plays once per tab session; a click, a key, the wheel or
 *   "Skip" ends it at once, and the hero's text arrives as the universe settles.
 * - The universe: a deep field of grey stars around the listed taus (client/cosmos.ts places
 *   them). Fire burns only on what is alive: an online tau burns in two neon triangles, a
 *   mutual link between two online taus carries sparks, and a sub-tau that visitors can talk
 *   to glows as it circles its tau. Offline taus, their links and their sub-taus are grey.
 *   With no tau listed yet, a dashed grey "your tau" waits in the middle.
 * - The universe sits beside the hero's text when there is room, above it otherwise, and
 *   turns slowly with the pointer.
 * - Hovering a tau shows its card; a click opens its person page, or its place on /universe.
 *   The universe page is the keyboard path (the link under the hero's text).
 * - Under `prefers-reduced-motion` there is no opening and nothing moves: the universe is
 *   drawn once, and again on resize.
 * - Nothing is drawn while the hero is off screen.
 *
 * Everything the directory returns is drawn as canvas text or set with textContent, never
 * parsed as HTML. The page's own strings come from client/messages.ts.
 */

import { getJson } from "./api";
import {
  type Camera,
  type Projector,
  projector,
  clamp,
  easeIn,
  easeInOut,
  easeOut,
  frame,
  type Frame,
  lerp,
  orbitPoint,
  orbits,
  type Orbit,
  type Point,
  PORTAL,
  PORTAL_DISTANCE,
  positions,
  type Projected,
  reachOf,
  type Rect,
  span,
  type Star,
  stars,
  tauPath,
  TWO_PI,
} from "./cosmos";
import { byId, characterElement, html } from "./dom";
import { MESSAGES, pageLanguage } from "./messages";
import type { SiteSnapshot, SnapshotTau } from "./types";

const language = pageLanguage(document.documentElement.lang);
const t = MESSAGES[language];
const numberFormat = new Intl.NumberFormat(language, { notation: "compact" });
const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

/** Longer names are cut on the canvas; the card shows them whole. */
const NAME_LABEL_LIMIT = 40;
/** Set once the opening has played in this tab. */
const SEEN_KEY = "tau.portal";
/** Where the opening ends and the universe only drifts. */
const END = PORTAL.settle[1] + 0.2;

const RGB = {
  signal: "255,46,99",
  ember: "255,122,61",
  flare: "255,178,92",
  core: "255,244,224",
  ash: "140,140,146",
};

const page = {
  hero: byId<HTMLElement>("hero"),
  canvas: byId<HTMLCanvasElement>("cosmos"),
  copy: byId<HTMLElement>("hero-copy"),
  count: byId<HTMLElement>("sky-count"),
  card: byId<HTMLElement>("cosmos-card"),
  skip: byId<HTMLButtonElement>("hero-skip"),
  header: document.querySelector<HTMLElement>(".site-header"),
};

function count(message: (count: number, formatted: string) => string, value: number): string {
  return message(value, numberFormat.format(value));
}

function seen(): boolean {
  try {
    return window.sessionStorage.getItem(SEEN_KEY) === "1";
  } catch {
    return false;
  }
}

function markSeen(): void {
  try {
    window.sessionStorage.setItem(SEEN_KEY, "1");
  } catch {
    // Storage may be off; the opening then plays again next time.
  }
}

// ---------------------------------------------------------------------------------------
// The world

interface Tau extends Point {
  /** Null for the empty universe's "your tau". */
  tau: SnapshotTau | null;
  label: string;
  online: boolean;
  orbits: Orbit[];
  links: number;
  messages: number;
  /** When it lights during the opening, in seconds. */
  ignite: number;
  /** 0..1 this frame: how lit, and how visible. */
  heat: number;
  shown: number;
  /** Where it was drawn last, for hovering. */
  sx: number;
  sy: number;
  sr: number;
  drawn: boolean;
}

interface Beam {
  a: Tau;
  b: Tau;
  messages: number;
  phase: number;
  reveal: number;
}

interface World {
  taus: Tau[];
  beams: Beam[];
  reach: number;
}

function shortName(name: string): string {
  return name.length > NAME_LABEL_LIMIT ? `${name.slice(0, NAME_LABEL_LIMIT - 1)}…` : name;
}

function tauOf(tau: SnapshotTau | null, at: Point, i: number): Tau {
  const address = tau?.address ?? "";
  const subs =
    tau === null ? [{ name: "coach" }, { name: "chef" }] : Array.isArray(tau.subs) ? tau.subs : [];
  return {
    ...at,
    tau,
    label: tau === null ? t.yourTau : shortName(tau.name || tau.address),
    online: tau?.online === true,
    orbits: orbits(address || "your-tau", subs),
    links: 0,
    messages: 0,
    ignite: PORTAL.ignite + i * 0.09,
    heat: 0,
    shown: 0,
    sx: 0,
    sy: 0,
    sr: 0,
    drawn: false,
  };
}

function buildWorld(snapshot: SiteSnapshot | null): World {
  if (snapshot === null) return { taus: [], beams: [], reach: 220 };
  if (snapshot.taus.length === 0) {
    const ghost = tauOf(null, { x: 0, y: 0, z: 0 }, 0);
    return { taus: [ghost], beams: [], reach: 220 };
  }
  const placed = positions(
    snapshot.taus.map((tau) => tau.address),
    snapshot.links,
  );
  // Online taus light first.
  const order = [...snapshot.taus].sort((a, b) => Number(b.online) - Number(a.online));
  const taus = order.map((tau, i) =>
    tauOf(tau, placed.get(tau.address)!, i + (tau.online ? 0 : 2)),
  );
  const byAddress = new Map(taus.map((tau) => [tau.tau!.address, tau]));
  const beams: Beam[] = [];
  for (const link of snapshot.links) {
    const a = byAddress.get(link.a);
    const b = byAddress.get(link.b);
    if (a === undefined || b === undefined) continue;
    a.links++;
    b.links++;
    a.messages += link.messages;
    b.messages += link.messages;
    beams.push({ a, b, messages: link.messages, phase: (beams.length * 0.37) % 1, reveal: 0 });
  }
  return { taus, beams, reach: reachOf(taus) };
}

// ---------------------------------------------------------------------------------------
// Drawing

function sprite(rgb: string, soft = false): HTMLCanvasElement {
  const size = 128;
  const c = document.createElement("canvas");
  c.width = c.height = size;
  const g = c.getContext("2d")!;
  const grd = g.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  if (soft) {
    grd.addColorStop(0, `rgba(${rgb},0.5)`);
    grd.addColorStop(0.4, `rgba(${rgb},0.16)`);
    grd.addColorStop(1, `rgba(${rgb},0)`);
  } else {
    grd.addColorStop(0, `rgba(${rgb},1)`);
    grd.addColorStop(0.12, `rgba(${rgb},0.6)`);
    grd.addColorStop(0.4, `rgba(${rgb},0.13)`);
    grd.addColorStop(1, `rgba(${rgb},0)`);
  }
  g.fillStyle = grd;
  g.fillRect(0, 0, size, size);
  return c;
}

interface Label {
  tau: Tau;
  p: Projected;
  r: number;
  heat: number;
  alpha: number;
}

class Painter {
  readonly ctx: CanvasRenderingContext2D;
  width = 1;
  height = 1;
  dpr = 1;
  readonly glow = {
    signal: sprite(RGB.signal),
    ember: sprite(RGB.ember),
    flare: sprite(RGB.flare),
    core: sprite(RGB.core),
    ash: sprite(RGB.ash, true),
    haze: sprite("255,90,31", true),
  };
  readonly mark = new Image();

  constructor(readonly canvas: HTMLCanvasElement) {
    this.ctx = canvas.getContext("2d")!;
    this.mark.src = "/brand/tau-mark.svg";
  }

  resize(): void {
    const rect = this.canvas.getBoundingClientRect();
    this.dpr = Math.min(window.devicePixelRatio || 1, 2);
    this.width = Math.max(1, rect.width);
    this.height = Math.max(1, rect.height);
    this.canvas.width = Math.round(this.width * this.dpr);
    this.canvas.height = Math.round(this.height * this.dpr);
  }

  get focal(): number {
    return Math.max(this.width, Math.min(this.height, window.innerHeight)) * 0.78;
  }

  clear(): void {
    const { ctx } = this;
    ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    ctx.globalCompositeOperation = "source-over";
    ctx.globalAlpha = 1;
    ctx.fillStyle = "#000";
    ctx.fillRect(0, 0, this.width, this.height);
  }

  additive(draw: () => void): void {
    const { ctx } = this;
    ctx.globalCompositeOperation = "lighter";
    draw();
    ctx.globalAlpha = 1;
    ctx.globalCompositeOperation = "source-over";
  }

  sprite(
    image: HTMLCanvasElement | HTMLImageElement,
    x: number,
    y: number,
    radius: number,
    alpha: number,
  ): void {
    if (alpha <= 0.005 || radius <= 0) return;
    this.ctx.globalAlpha = Math.min(1, alpha);
    this.ctx.drawImage(image, x - radius, y - radius, radius * 2, radius * 2);
  }

  /** A warm haze where the living taus are; the rest of the sky stays black. */
  haze(view: Projector, warmth: number): void {
    const p = view({ x: 0, y: 0, z: 0 });
    if (p === null) return;
    const r = Math.min(1_100 * p.scale, Math.max(this.width, this.height) * 0.7);
    this.additive(() => {
      this.sprite(this.glow.haze, p.x, p.y, r, 0.1 * warmth);
      this.sprite(this.glow.ash, p.x, p.y, r, 0.05 * (1 - warmth));
    });
  }

  stars(
    view: Projector,
    dist: number,
    sky: Star[],
    time: number,
    alpha: number,
    streak: number,
  ): void {
    const { ctx } = this;
    this.additive(() => {
      ctx.lineCap = "round";
      for (const star of sky) {
        const p = view(star);
        if (p === null) continue;
        if (p.x < -40 || p.y < -40 || p.x > this.width + 40 || p.y > this.height + 40) continue;
        const near = clamp(p.scale * 2.6, 0.5, 3.2);
        const a =
          star.alpha *
          alpha *
          (0.72 + 0.28 * Math.sin(time * 1.4 + star.phase)) *
          clamp(2.2 - p.z / 5_200, 0.12, 1);
        if (a <= 0.01) continue;
        const size = star.size * near;
        const colour = star.warm ? "#ffb080" : "#e2e2e8";
        ctx.globalAlpha = clamp(a);
        if (streak > 0) {
          const q = view(star, dist + streak);
          if (q !== null) {
            ctx.strokeStyle = colour;
            ctx.lineWidth = Math.max(0.6, size * 0.8);
            ctx.beginPath();
            ctx.moveTo(q.x, q.y);
            ctx.lineTo(p.x, p.y);
            ctx.stroke();
            continue;
          }
        }
        if (size > 2.2)
          this.sprite(star.warm ? this.glow.flare : this.glow.core, p.x, p.y, size * 3.2, a * 0.5);
        ctx.globalAlpha = clamp(a);
        ctx.fillStyle = colour;
        ctx.fillRect(p.x - size / 2, p.y - size / 2, size, size);
      }
    });
  }

  beams(view: Projector, beams: Beam[], time: number, moving: boolean): void {
    const { ctx } = this;
    this.additive(() => {
      for (const beam of beams) {
        const shown = Math.min(beam.a.shown, beam.b.shown);
        if (beam.reveal <= 0 || shown <= 0.01) continue;
        const pa = view(beam.a);
        const pb = view(beam.b);
        if (pa === null || pb === null) continue;
        const heat = beam.a.online && beam.b.online ? Math.min(beam.a.heat, beam.b.heat) : 0;
        const weight = clamp(Math.log10(1 + beam.messages) / 2.4, 0.15, 1);
        const ex = lerp(pa.x, pb.x, beam.reveal);
        const ey = lerp(pa.y, pb.y, beam.reveal);
        const grd = ctx.createLinearGradient(pa.x, pa.y, pb.x, pb.y);
        if (heat > 0) {
          const edge = (0.22 + 0.4 * weight) * heat * shown;
          grd.addColorStop(0, `rgba(${RGB.signal},${edge})`);
          grd.addColorStop(0.5, `rgba(${RGB.ember},${(0.3 + 0.4 * weight) * heat * shown})`);
          grd.addColorStop(1, `rgba(${RGB.signal},${edge})`);
        } else {
          grd.addColorStop(0, `rgba(${RGB.ash},${0.22 * shown})`);
          grd.addColorStop(1, `rgba(${RGB.ash},${0.22 * shown})`);
        }
        ctx.globalAlpha = 1;
        ctx.strokeStyle = grd;
        ctx.lineWidth = heat > 0 ? 0.8 + weight * 1.1 : 0.7;
        ctx.beginPath();
        ctx.moveTo(pa.x, pa.y);
        ctx.lineTo(ex, ey);
        ctx.stroke();
        // Messages in flight: a spark or three along a live link.
        if (moving && heat > 0.5 && beam.reveal >= 1) {
          const sparks = 1 + Math.min(2, Math.floor(Math.log10(1 + beam.messages)));
          for (let k = 0; k < sparks; k++) {
            const at = (time * (0.08 + 0.05 * weight) + beam.phase + k / sparks) % 1;
            this.sprite(
              this.glow.flare,
              lerp(pa.x, pb.x, at),
              lerp(pa.y, pb.y, at),
              7 + 5 * weight,
              heat * shown * Math.sin(at * Math.PI),
            );
          }
        }
      }
    });
  }

  triangle(x: number, y: number, r: number): void {
    const { ctx } = this;
    ctx.beginPath();
    for (let k = 0; k < 3; k++) {
      const a = -Math.PI / 2 + (k * TWO_PI) / 3;
      if (k === 0) ctx.moveTo(x + Math.cos(a) * r, y + Math.sin(a) * r);
      else ctx.lineTo(x + Math.cos(a) * r, y + Math.sin(a) * r);
    }
    ctx.closePath();
  }

  taus(view: Projector, taus: Tau[], time: number): void {
    const { ctx } = this;
    const order = taus
      .map((tau) => ({ tau, p: view(tau) }))
      .filter((it): it is { tau: Tau; p: Projected } => it.p !== null)
      .sort((a, b) => b.p.z - a.p.z);
    for (const tau of taus) tau.drawn = false;
    const labels: Label[] = [];

    for (const { tau, p } of order) {
      if (tau.shown <= 0.01) continue;
      const heat = tau.online ? tau.heat : 0;
      const r = clamp(10 * p.scale, 3.2, 140);
      tau.sx = p.x;
      tau.sy = p.y;
      tau.sr = Math.max(r * 1.6, 14);
      tau.drawn = true;

      const moons = tau.orbits.map((orbit) => {
        const at = orbitPoint(tau, orbit, orbit.phase + time * orbit.speed);
        return { orbit, q: view(at) };
      });
      const moon = (it: (typeof moons)[number]) => {
        if (it.q === null) return;
        const lit = it.orbit.web && tau.online ? heat : 0;
        const size = clamp(2.6 * it.q.scale, 1.2, 9);
        this.additive(() => {
          if (lit > 0)
            this.sprite(this.glow.ember, it.q!.x, it.q!.y, size * 4, lit * tau.shown * 0.9);
          ctx.globalAlpha = tau.shown;
          ctx.fillStyle =
            lit > 0 ? `rgba(${RGB.flare},${0.5 + 0.5 * lit})` : `rgba(${RGB.ash},0.75)`;
          ctx.beginPath();
          ctx.arc(it.q!.x, it.q!.y, size / 2, 0, TWO_PI);
          ctx.fill();
        });
      };
      moons.filter((it) => it.q !== null && it.q.z > p.z).forEach(moon);

      // The tau: a burning core in two neon triangles when online, grey otherwise.
      this.additive(() => {
        if (heat > 0) {
          this.sprite(this.glow.signal, p.x, p.y, r * 5.5, heat * tau.shown * 0.85);
          this.sprite(this.glow.flare, p.x, p.y, r * 2.4, heat * tau.shown);
        } else {
          this.sprite(this.glow.ash, p.x, p.y, r * 3, 0.5 * tau.shown);
        }
        ctx.globalAlpha = tau.shown;
        ctx.lineJoin = "miter";
        ctx.lineWidth = clamp(r / 9, 1, 2.4);
        if (heat > 0) {
          const grd = ctx.createLinearGradient(p.x, p.y - r * 1.4, p.x, p.y + r);
          grd.addColorStop(0, `rgba(${RGB.flare},${heat})`);
          grd.addColorStop(1, `rgba(${RGB.signal},${heat})`);
          ctx.strokeStyle = grd;
        } else {
          ctx.strokeStyle = `rgba(${RGB.ash},0.6)`;
          if (tau.tau === null) ctx.setLineDash([4, 4]);
        }
        this.triangle(p.x, p.y, r * 1.35);
        ctx.stroke();
        if (p.scale > 0.9) {
          ctx.lineWidth = 1;
          this.triangle(p.x, p.y + r * 0.2, r * 0.8);
          ctx.stroke();
        }
        ctx.setLineDash([]);
        ctx.fillStyle = heat > 0 ? `rgba(${RGB.core},${0.6 + 0.4 * heat})` : `rgba(${RGB.ash},0.9)`;
        const core = clamp(r * 0.28, 1.6, 12);
        ctx.fillRect(p.x - core / 2, p.y - core / 2, core, core);
      });

      moons.filter((it) => it.q !== null && it.q.z <= p.z).forEach(moon);
      if (p.scale >= 0.5 && tau.shown > 0.3) {
        labels.push({ tau, p, r, heat, alpha: clamp((p.scale - 0.5) * 4) * tau.shown });
      }
    }
    this.labels(
      labels,
      order.map((it) => it.tau),
    );
  }

  /** HUD labels with a leader line: the living and the nearest first, none on top of another. */
  labels(labels: Label[], taus: Tau[]): void {
    const { ctx } = this;
    const spacing = (value: string) => {
      if ("letterSpacing" in ctx) (ctx as { letterSpacing: string }).letterSpacing = value;
    };
    labels.sort((a, b) => Number(b.heat > 0) - Number(a.heat > 0) || b.p.scale - a.p.scale);
    const placed: { x: number; y: number; w: number; h: number }[] = [];
    // Names are the owners' own words: drawn as written, never upper-cased.
    ctx.font = '600 12px "Chakra Petch", sans-serif';
    spacing("0.4px");
    for (const { tau, p, r, heat, alpha } of labels) {
      const text = tau.label;
      const width = ctx.measureText(text).width;
      const y = p.y - r * 1.1 - 6;
      const free = (x: number) => {
        const box = { x, y: y - 6, w: width + 10, h: 18 };
        const onLabel = placed.some(
          (b) =>
            box.x < b.x + b.w && box.x + box.w > b.x && box.y < b.y + b.h && box.y + box.h > b.y,
        );
        const onTau = taus.some(
          (other) =>
            other !== tau &&
            other.drawn &&
            other.shown > 0.3 &&
            other.sx + other.sr * 0.6 > box.x &&
            other.sx - other.sr * 0.6 < box.x + box.w &&
            other.sy + other.sr * 0.6 > box.y &&
            other.sy - other.sr * 0.6 < box.y + box.h,
        );
        const offScreen = box.x < 4 || box.x + box.w > this.width - 4;
        return onLabel || onTau || offScreen ? null : box;
      };
      const box = free(p.x + r * 1.4 + 10) ?? free(p.x - r * 1.4 - 20 - width);
      if (box === null) continue;
      placed.push(box);
      const left = box.x < p.x;
      const end = left ? box.x + box.w + 4 : box.x - 4;
      ctx.globalAlpha = 1;
      ctx.strokeStyle =
        heat > 0 ? `rgba(${RGB.ember},${0.6 * alpha})` : `rgba(${RGB.ash},${0.45 * alpha})`;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(left ? p.x - r * 0.9 : p.x + r * 0.9, p.y - r * 0.6);
      ctx.lineTo(end, y + 4);
      ctx.lineTo(left ? end - 6 : end + 6, y + 4);
      ctx.stroke();
      ctx.fillStyle =
        heat > 0 ? `rgba(${RGB.core},${0.95 * alpha})` : `rgba(${RGB.ash},${0.8 * alpha})`;
      ctx.fillText(text, left ? box.x : box.x + 6, y + 8);
    }
    spacing("0px");
  }
}

// ---------------------------------------------------------------------------------------
// The portal

interface PortalView {
  /** The middle of the floor, and the height of the outer triangle. */
  cx: number;
  base: number;
  height: number;
  /** The centroid, which the portal grows from. */
  cy: number;
}

function portalView(width: number, height: number): PortalView {
  const visible = Math.min(height, window.innerHeight);
  const base = visible * (width < 760 ? 0.6 : 0.68);
  const tall = Math.min(visible * 0.54, width * 0.8);
  return { cx: width / 2, base, height: tall, cy: base - tall / 3 };
}

function drawPortal(painter: Painter, view: PortalView, time: number, universe: () => void): void {
  const { ctx, width } = painter;
  const { cx, cy, base, height } = view;
  const grow = 1 + easeIn(span(time, ...PORTAL.grow)) * 34;
  const scaled = (x: number, y: number): [number, number] => [
    cx + (x - cx) * grow,
    cy + (y - cy) * grow,
  ];
  const corners = (tall: number) => [
    scaled(cx, base - tall),
    scaled(cx + tall / Math.sqrt(3), base),
    scaled(cx - tall / Math.sqrt(3), base),
  ];

  // The universe shows through the portal only, until the camera is through.
  if (time > PORTAL.sky[0]) {
    ctx.save();
    ctx.beginPath();
    corners(height).forEach(([x, y], i) => (i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y)));
    ctx.closePath();
    ctx.clip();
    universe();
    ctx.restore();
  }

  // The floor line and faint beams rising from it.
  const floor =
    span(time, ...PORTAL.floor) * (1 - span(time, PORTAL.grow[0] + 0.1, PORTAL.grow[1] - 0.1));
  if (floor > 0) {
    const half = easeOut(span(time, ...PORTAL.floor)) * width * 0.48;
    const grd = ctx.createLinearGradient(cx - half, 0, cx + half, 0);
    grd.addColorStop(0, `rgba(${RGB.signal},0)`);
    grd.addColorStop(0.5, `rgba(${RGB.flare},${floor})`);
    grd.addColorStop(1, `rgba(${RGB.signal},0)`);
    ctx.fillStyle = grd;
    ctx.fillRect(cx - half, base - 1, half * 2, 2);
    painter.additive(() => {
      ctx.globalAlpha = floor * 0.5;
      ctx.drawImage(painter.glow.ember, cx - half * 0.6, base - 30, half * 1.2, 60);
      for (let i = 0; i < 34; i++) {
        const x = cx + (((i * 0.6180339) % 1) - 0.5) * 2 * (height / Math.sqrt(3)) * 1.3;
        const rise = height * (0.25 + ((i * 0.381966) % 1) * 0.75) * easeOut(span(time, 0.4, 1.4));
        const a =
          (0.25 + ((i * 0.7548776) % 1) * 0.6) *
          floor *
          0.35 *
          (1 - Math.abs((x - cx) / width) * 1.2);
        const beam = ctx.createLinearGradient(0, base, 0, base - rise);
        beam.addColorStop(0, `rgba(${RGB.ember},${clamp(a)})`);
        beam.addColorStop(1, `rgba(${RGB.signal},0)`);
        ctx.globalAlpha = 1;
        ctx.fillStyle = beam;
        ctx.fillRect(x, base - rise, 1, rise);
      }
    });
  }

  // The two triangles rise from the floor: both legs up to the apex, then the base.
  const fade = 1 - span(time, PORTAL.through[0] + 0.05, PORTAL.through[1] + 0.1);
  const triangle = (
    tall: number,
    colour: string,
    [from, to]: readonly [number, number],
    lineWidth: number,
  ) => {
    const progress = easeInOut(span(time, from, to));
    if (progress <= 0 || fade <= 0) return;
    const [apex, right, left] = corners(tall) as [
      [number, number],
      [number, number],
      [number, number],
    ];
    const leg = clamp(progress * 1.25);
    ctx.save();
    ctx.globalAlpha = fade;
    ctx.strokeStyle = colour;
    ctx.lineWidth = lineWidth;
    ctx.shadowColor = colour;
    ctx.shadowBlur = 18;
    ctx.beginPath();
    ctx.moveTo(left[0], left[1]);
    ctx.lineTo(lerp(left[0], apex[0], leg), lerp(left[1], apex[1], leg));
    ctx.moveTo(right[0], right[1]);
    ctx.lineTo(lerp(right[0], apex[0], leg), lerp(right[1], apex[1], leg));
    const closing = span(progress, 0.8, 1);
    if (closing > 0) {
      const mid = (left[0] + right[0]) / 2;
      ctx.moveTo(lerp(mid, left[0], closing), left[1]);
      ctx.lineTo(lerp(mid, right[0], closing), right[1]);
    }
    ctx.stroke();
    ctx.restore();
  };
  triangle(height, "#ff2e63", PORTAL.outer, 2.2);
  triangle(height * 0.66, "#ff7a3d", PORTAL.inner, 1.6);

  // The mark inside, then a flash as the camera comes through.
  const [markIn, markFull, markOut, markGone] = PORTAL.mark;
  const mark = span(time, markIn, markFull) * (1 - span(time, markOut, markGone));
  if (mark > 0 && painter.mark.complete && painter.mark.naturalWidth > 0) {
    const size = height * 0.3 * (1 + span(time, markOut, markGone) * 0.6);
    painter.additive(() => {
      painter.sprite(painter.glow.ember, cx, cy, size * 1.6, mark);
      ctx.globalAlpha = mark;
      ctx.drawImage(painter.mark, cx - size / 2, cy - size / 2, size, size);
    });
  }
  const flash =
    span(time, PORTAL.through[0], PORTAL.through[0] + 0.15) *
    (1 - span(time, PORTAL.through[1], PORTAL.through[1] + 0.5));
  if (flash > 0) {
    painter.additive(() => {
      painter.sprite(
        painter.glow.flare,
        painter.width / 2,
        cy,
        Math.max(painter.width, painter.height) * 1.2,
        flash * 0.5,
      );
    });
  }
}

// ---------------------------------------------------------------------------------------
// The card

let cardFor: Tau | null = null;

function showCard(tau: Tau | null): void {
  const data = tau?.tau ?? null;
  if (tau === null || data === null) {
    page.card.hidden = true;
    cardFor = null;
    return;
  }
  if (cardFor !== tau) {
    cardFor = tau;
    const head = html("div", "cosmos-card-head");
    const names = html("div");
    names.append(
      html("p", "cosmos-card-name", data.name || data.address),
      html("p", "cosmos-card-address", data.address),
    );
    head.append(characterElement(data.address, { size: 44 }), names);
    const state = html("p", `cosmos-card-state${data.online ? " is-live" : ""}`);
    state.append(
      html("span", `pip ${data.online ? "pip-live" : "pip-off"}`),
      html("span", undefined, data.online ? t.online : t.offline),
    );
    const subs = Array.isArray(data.subs) ? data.subs.length : 0;
    const facts = [
      count(t.publicSubs, subs),
      count(t.links, tau.links),
      count(t.msgs, tau.messages),
    ];
    page.card.replaceChildren(
      head,
      state,
      html("p", "cosmos-card-facts", facts.join(" · ")),
      html("p", "cosmos-card-open", `${t.openPage} ›`),
    );
  }
  page.card.hidden = false;
  const width = page.card.offsetWidth;
  const x =
    tau.sx + tau.sr + 12 + width > page.hero.clientWidth - 12
      ? tau.sx - tau.sr - 12 - width
      : tau.sx + tau.sr + 12;
  page.card.style.transform = `translate(${Math.round(x)}px, ${Math.round(tau.sy - 24)}px)`;
}

// ---------------------------------------------------------------------------------------
// The hero

function relative(element: Element | null, to: DOMRect): Rect | null {
  if (element === null) return null;
  const rect = element.getBoundingClientRect();
  return {
    left: rect.left - to.left,
    top: rect.top - to.top,
    right: rect.right - to.left,
    bottom: rect.bottom - to.top,
  };
}

async function load(): Promise<SiteSnapshot | null> {
  const result = await getJson<SiteSnapshot>("/api/universe");
  if (result.status !== 200 || result.data === null || !Array.isArray(result.data.taus)) {
    page.count.textContent = t.unavailable;
    return null;
  }
  const { stats } = result.data;
  page.count.textContent =
    stats.taus === 0
      ? t.empty
      : t.skyCount(
          count(t.msgs, stats.messages),
          numberFormat.format(stats.online),
          count(t.taus, stats.taus),
        );
  if (!Array.isArray(result.data.links)) result.data.links = [];
  return result.data;
}

function start(): void {
  const painter = new Painter(page.canvas);
  const sky = stars(window.innerWidth < 760 ? 1_400 : 2_600);
  let world = buildWorld(null);
  let place: Frame = { cx: 0, cy: 0, dist: 1_000, layout: "side" };
  let portal = portalView(1, 1);
  const still = reducedMotion.matches;
  let origin = performance.now();
  let opened = false;
  let onScreen = true;
  let hovered: Tau | null = null;
  const pointer = { x: 0, y: 0, inside: false, nx: 0, ny: 0 };
  let lastDist = PORTAL_DISTANCE;

  const layout = () => {
    painter.resize();
    const hero = page.hero.getBoundingClientRect();
    const copy = relative(page.copy, hero) ?? {
      left: 0,
      top: painter.height,
      right: 0,
      bottom: painter.height,
    };
    const header = relative(page.header, hero);
    place = frame(
      painter.width,
      Math.min(painter.height, Math.max(window.innerHeight, copy.bottom)),
      copy,
      header?.bottom ?? 0,
      world.reach,
      painter.focal,
    );
    portal = portalView(painter.width, painter.height);
  };

  const open = () => {
    if (opened) return;
    opened = true;
    page.hero.classList.add("is-open");
    page.skip.hidden = true;
    for (const [type, handler] of skips) window.removeEventListener(type, handler);
  };
  const skip = () => {
    const now = (performance.now() - origin) / 1000;
    if (now < END) origin = performance.now() - END * 1000;
    open();
  };
  const skips: [string, () => void][] = [
    ["wheel", skip],
    ["keydown", skip],
    ["touchstart", skip],
  ];

  if (still || seen()) {
    origin -= END * 1000;
    open();
  } else {
    markSeen();
    page.skip.hidden = false;
    page.skip.addEventListener("click", skip);
    page.hero.addEventListener("pointerdown", skip, { once: true });
    for (const [type, handler] of skips) window.addEventListener(type, handler, { passive: true });
  }

  const draw = (now: number) => {
    const time = still ? END : (now - origin) / 1000;
    const clock = still ? 0 : now / 1000;
    painter.clear();

    const tx = pointer.inside ? (pointer.x / painter.width) * 2 - 1 : 0;
    const ty = pointer.inside
      ? (pointer.y / Math.min(painter.height, window.innerHeight)) * 2 - 1
      : 0;
    pointer.nx += (tx - pointer.nx) * (still ? 1 : 0.04);
    pointer.ny += (ty - pointer.ny) * (still ? 1 : 0.04);
    const settle = easeInOut(span(time, ...PORTAL.settle));
    const sway = still ? 0 : settle;

    const cam: Camera = {
      target: { x: 0, y: 0, z: 0 },
      yaw: 0.4 + (still ? 0 : clock * 0.03) + pointer.nx * 0.22 * sway,
      pitch: -0.22 + pointer.ny * 0.1 * sway,
      dist: lerp(PORTAL_DISTANCE, place.dist, easeInOut(span(time, ...PORTAL.fly))),
      cx: lerp(portal.cx, place.cx, settle),
      cy: lerp(portal.cy, place.cy, settle),
      focal: painter.focal,
    };
    const streak = Math.min(Math.max(0, lastDist - cam.dist) * 5, 900);
    lastDist = cam.dist;

    for (const tau of world.taus) {
      tau.heat = easeOut(span(time, tau.ignite, tau.ignite + 0.7));
      tau.shown =
        time < PORTAL.through[1]
          ? span(time, PORTAL.sky[0] + 0.3, PORTAL.sky[1] + 0.3)
          : tau.online
            ? 1
            : easeOut(span(time, tau.ignite, tau.ignite + 0.9));
      if (tau.tau === null)
        tau.shown = Math.max(tau.shown, span(time, PORTAL.ignite, PORTAL.ignite + 0.8));
    }
    world.beams.forEach((beam, i) => {
      beam.reveal = easeOut(
        span(time, PORTAL.settle[0] + 0.5 + i * 0.05, PORTAL.settle[1] + i * 0.05),
      );
    });

    const view = projector(cam);
    const universe = () => {
      painter.haze(view, world.taus.some((tau) => tau.online) ? 1 : 0.3);
      painter.stars(
        view,
        cam.dist,
        sky,
        clock,
        time < PORTAL.grow[0] ? span(time, ...PORTAL.sky) : 1,
        streak,
      );
      painter.beams(view, world.beams, clock, !still);
      painter.taus(view, world.taus, clock);
    };
    if (time < PORTAL.through[1]) drawPortal(painter, portal, time, universe);
    else universe();

    if (!opened && time >= PORTAL.open) open();
  };

  let lastFrame = 0;
  const loop = (now: number) => {
    window.requestAnimationFrame(loop);
    if (!onScreen) return;
    // After the opening the universe only drifts: 30 frames a second are enough.
    if ((now - origin) / 1000 > END && now - lastFrame < 30) return;
    lastFrame = now;
    draw(now);
    if (hovered !== null) showCard(hovered);
  };

  const redraw = () => {
    layout();
    if (still) draw(performance.now());
  };

  /** The listed tau under a point of the canvas, if any. */
  const pick = (x: number, y: number): Tau | null => {
    let best: Tau | null = null;
    let bestDistance = Infinity;
    for (const tau of world.taus) {
      if (!tau.drawn || tau.shown < 0.3 || tau.tau === null) continue;
      const d = Math.hypot(tau.sx - x, tau.sy - y);
      if (d < tau.sr && d < bestDistance) {
        best = tau;
        bestDistance = d;
      }
    }
    return best;
  };

  const hover = (event: PointerEvent) => {
    const rect = page.canvas.getBoundingClientRect();
    pointer.x = event.clientX - rect.left;
    pointer.y = event.clientY - rect.top;
    pointer.inside = true;
    if (!opened || event.pointerType === "touch") return;
    const best = pick(pointer.x, pointer.y);
    hovered = best;
    page.canvas.classList.toggle("is-pointing", best !== null);
    showCard(best);
  };

  page.canvas.addEventListener("pointermove", hover);
  page.canvas.addEventListener("pointerleave", () => {
    pointer.inside = false;
    hovered = null;
    page.canvas.classList.remove("is-pointing");
    showCard(null);
  });
  page.canvas.addEventListener("click", (event) => {
    if (!opened) return;
    const rect = page.canvas.getBoundingClientRect();
    const data = pick(event.clientX - rect.left, event.clientY - rect.top)?.tau ?? null;
    if (data !== null) window.location.assign(tauPath(data, language));
  });
  window.addEventListener("resize", redraw);
  new IntersectionObserver((entries) => {
    onScreen = entries.some((entry) => entry.isIntersecting);
  }).observe(page.hero);

  layout();
  if (still) draw(performance.now());
  else window.requestAnimationFrame(loop);

  void load().then((snapshot) => {
    world = buildWorld(snapshot);
    if (opened && !still) {
      // The universe arrived after the opening: its taus light now.
      const now = (performance.now() - origin) / 1000;
      world.taus.forEach((tau, i) => (tau.ignite = now + i * 0.09));
    }
    redraw();
  });
}

start();
