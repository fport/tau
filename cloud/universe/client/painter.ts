/**
 * The universe on a canvas, shared by the landing's hero (client/landing.ts) and the universe
 * page (client/universe.ts): the world built from a snapshot, and the painter that draws it.
 *
 * - A deep field of grey stars around the listed taus (client/cosmos.ts places them).
 * - Fire burns only on what is alive: an online tau burns in two neon triangles, a mutual
 *   link between two online taus carries sparks, and a sub-tau that visitors can talk to
 *   glows as it circles its tau. Offline taus, their links and their sub-taus are grey.
 * - With no tau listed yet, a dashed grey "your tau" waits in the middle.
 * - A focus (the universe page) dims what is not selected or not matching, marks the
 *   selected tau or sub-tau with a reticle and names the selected tau's sub-taus.
 *
 * Everything the directory returns is drawn as canvas text, never parsed as HTML.
 */

import {
  clamp,
  hull,
  lerp,
  orbitPoint,
  orbits,
  type Orbit,
  ownerKey,
  type Point,
  PORTAL,
  positions,
  type Projected,
  type Projector,
  reachOf,
  type Star,
  TWO_PI,
} from "./cosmos";
import type { SiteSnapshot, SnapshotTau } from "./types";

/** Longer names are cut on the canvas; the cards show them whole. */
const NAME_LABEL_LIMIT = 40;

export const RGB = {
  signal: "255,46,99",
  ember: "255,122,61",
  flare: "255,178,92",
  core: "255,244,224",
  ash: "140,140,146",
};

// ---------------------------------------------------------------------------------------
// The world

/** Where a sub-tau was drawn last, for pointing at it. */
export interface MoonSpot {
  name: string;
  x: number;
  y: number;
  r: number;
}

export interface Tau extends Point {
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
  /** Where it was drawn last, for pointing at it. */
  sx: number;
  sy: number;
  sr: number;
  drawn: boolean;
  /** Drawn faint this frame (see Focus). */
  faint: boolean;
  moons: MoonSpot[];
}

export interface Beam {
  a: Tau;
  b: Tau;
  messages: number;
  phase: number;
  reveal: number;
}

/** An owner with more than one listed tau: drawn as one dashed outline around them. */
export interface Owner {
  name: string;
  taus: Tau[];
}

export interface World {
  taus: Tau[];
  beams: Beam[];
  owners: Owner[];
  byAddress: Map<string, Tau>;
  reach: number;
}

function shortName(name: string): string {
  return name.length > NAME_LABEL_LIMIT ? `${name.slice(0, NAME_LABEL_LIMIT - 1)}…` : name;
}

function tauOf(tau: SnapshotTau | null, at: Point, i: number, ghostLabel: string): Tau {
  const address = tau?.address ?? "";
  const subs =
    tau === null ? [{ name: "coach" }, { name: "chef" }] : Array.isArray(tau.subs) ? tau.subs : [];
  return {
    ...at,
    tau,
    label: tau === null ? ghostLabel : shortName(tau.name || tau.address),
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
    faint: false,
    moons: [],
  };
}

/** The world of a snapshot; `ghostLabel` names the empty universe's placeholder tau. */
export function buildWorld(snapshot: SiteSnapshot | null, ghostLabel: string): World {
  if (snapshot === null)
    return { taus: [], beams: [], owners: [], byAddress: new Map(), reach: 220 };
  if (snapshot.taus.length === 0) {
    const ghost = tauOf(null, { x: 0, y: 0, z: 0 }, 0, ghostLabel);
    return { taus: [ghost], beams: [], owners: [], byAddress: new Map(), reach: 220 };
  }
  const placed = positions(
    snapshot.taus.map((tau) => tau.address),
    snapshot.links,
  );
  // Online taus light first.
  const order = [...snapshot.taus].sort((a, b) => Number(b.online) - Number(a.online));
  const taus = order.map((tau, i) =>
    tauOf(tau, placed.get(tau.address)!, i + (tau.online ? 0 : 2), ghostLabel),
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
  const groups = new Map<string, Owner>();
  for (const tau of taus) {
    const owner = tau.tau!.owner;
    const key = ownerKey(owner);
    if (key === "") continue;
    const group = groups.get(key) ?? { name: owner.trim(), taus: [] };
    group.taus.push(tau);
    groups.set(key, group);
  }
  const owners = [...groups.values()].filter((group) => group.taus.length > 1);
  return { taus, beams, owners, byAddress, reach: reachOf(taus) };
}

// ---------------------------------------------------------------------------------------
// The focus

export interface Focus {
  /** The selected tau: a reticle around it, and its sub-taus named. */
  selected: Tau | null;
  /** The selected sub-tau's name, on the selected tau. */
  sub: string | null;
  /** The tau under the pointer: named even where its label would be crowded out. */
  hovered: Tau | null;
  /** Taus drawn faint: away from the selection, or not matching the search. */
  dim: (tau: Tau) => boolean;
  /** Links drawn faint. */
  dimBeam: (beam: Beam) => boolean;
}

/** How visible something faint stays. */
const FAINT = 0.2;

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
  /** Placed first and never crowded out. */
  first: boolean;
}

export class Painter {
  readonly ctx: CanvasRenderingContext2D;
  width = 1;
  height = 1;
  dpr = 1;
  /** The size of the taus' names, in CSS pixels. */
  labelSize = 12;
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

  /** A dashed grey outline around each owner's taus, with the owner's name under it. */
  owners(view: Projector, owners: Owner[], focus?: Focus): void {
    const { ctx } = this;
    for (const owner of owners) {
      const around: { x: number; y: number }[] = [];
      let shown = 1;
      let faint = true;
      for (const tau of owner.taus) {
        const p = view(tau);
        if (p === null) continue;
        shown = Math.min(shown, tau.shown);
        if (focus?.dim(tau) !== true) faint = false;
        const pad = clamp(10 * p.scale, 3.2, 140) * 2.6 + 10;
        for (let k = 0; k < 8; k++) {
          const a = (k * TWO_PI) / 8;
          around.push({ x: p.x + Math.cos(a) * pad, y: p.y + Math.sin(a) * pad });
        }
      }
      if (around.length < 16 || shown <= 0.05) continue;
      const outline = hull(around);
      const alpha = shown * (faint ? FAINT : 1);
      ctx.globalAlpha = 0.5 * alpha;
      ctx.strokeStyle = `rgb(${RGB.ash})`;
      ctx.lineWidth = 1;
      ctx.setLineDash([3, 5]);
      ctx.beginPath();
      outline.forEach((q, i) => (i === 0 ? ctx.moveTo(q.x, q.y) : ctx.lineTo(q.x, q.y)));
      ctx.closePath();
      ctx.stroke();
      ctx.setLineDash([]);
      // Under the outline: the taus' own names sit above them.
      const low = outline.reduce((best, q) => (q.y > best.y ? q : best));
      ctx.globalAlpha = 0.85 * alpha;
      ctx.fillStyle = `rgb(${RGB.ash})`;
      // Owner names are the owners' own words: never upper-cased.
      ctx.font = '500 11px "JetBrains Mono", ui-monospace, monospace';
      ctx.textAlign = "center";
      ctx.fillText(owner.name, low.x, low.y + 14);
      ctx.textAlign = "start";
    }
    ctx.globalAlpha = 1;
  }

  beams(view: Projector, beams: Beam[], time: number, moving: boolean, focus?: Focus): void {
    const { ctx } = this;
    this.additive(() => {
      for (const beam of beams) {
        const fade = focus?.dimBeam(beam) ? FAINT : 1;
        const shown = Math.min(beam.a.shown, beam.b.shown) * fade;
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

  /** A square reticle: four corner brackets around a point. */
  reticle(x: number, y: number, half: number, alpha: number, rgb = RGB.flare): void {
    const { ctx } = this;
    const arm = Math.max(4, half * 0.38);
    ctx.globalAlpha = alpha;
    ctx.strokeStyle = `rgb(${rgb})`;
    ctx.lineWidth = 1.2;
    ctx.beginPath();
    for (const [sx, sy] of [
      [-1, -1],
      [1, -1],
      [1, 1],
      [-1, 1],
    ] as const) {
      const cx = x + sx * half;
      const cy = y + sy * half;
      ctx.moveTo(cx, cy - sy * arm);
      ctx.lineTo(cx, cy);
      ctx.lineTo(cx - sx * arm, cy);
    }
    ctx.stroke();
    ctx.globalAlpha = 1;
  }

  taus(view: Projector, taus: Tau[], time: number, focus?: Focus): void {
    const { ctx } = this;
    const order = taus
      .map((tau) => ({ tau, p: view(tau) }))
      .filter((it): it is { tau: Tau; p: Projected } => it.p !== null)
      .sort((a, b) => b.p.z - a.p.z);
    for (const tau of taus) {
      tau.drawn = false;
      tau.moons = [];
    }
    const labels: Label[] = [];

    for (const { tau, p } of order) {
      const faint = focus?.dim(tau) === true;
      const shown = tau.shown * (faint ? FAINT : 1);
      if (shown <= 0.01) continue;
      const heat = tau.online ? tau.heat : 0;
      const r = clamp(10 * p.scale, 3.2, 140);
      const selected = focus?.selected === tau;
      tau.sx = p.x;
      tau.sy = p.y;
      tau.sr = Math.max(r * 1.6, 14);
      tau.drawn = true;
      tau.faint = faint;

      const moons = tau.orbits.map((orbit) => {
        const at = orbitPoint(tau, orbit, orbit.phase + time * orbit.speed);
        return { orbit, q: view(at) };
      });
      const moon = (it: (typeof moons)[number]) => {
        if (it.q === null) return;
        const lit = it.orbit.web && tau.online ? heat : 0;
        const size = clamp(2.6 * it.q.scale, 1.2, 9);
        tau.moons.push({ name: it.orbit.name, x: it.q.x, y: it.q.y, r: Math.max(size * 2, 9) });
        this.additive(() => {
          if (lit > 0)
            this.sprite(this.glow.ember, it.q!.x, it.q!.y, size * 4, lit * shown * 0.9);
          ctx.globalAlpha = shown;
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
          this.sprite(this.glow.signal, p.x, p.y, r * 5.5, heat * shown * 0.85);
          this.sprite(this.glow.flare, p.x, p.y, r * 2.4, heat * shown);
        } else {
          this.sprite(this.glow.ash, p.x, p.y, r * 3, 0.5 * shown);
        }
        ctx.globalAlpha = shown;
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

      if (selected) {
        if (focus?.sub == null) this.reticle(p.x, p.y, Math.max(r * 2, 16), tau.shown);
        this.moonLabels(tau, focus?.sub ?? null, heat);
      }
      const first = selected || focus?.hovered === tau;
      if ((p.scale >= 0.5 || first) && tau.shown > 0.3 && !faint) {
        const alpha = first ? tau.shown : clamp((p.scale - 0.5) * 4) * tau.shown;
        labels.push({ tau, p, r, heat, alpha, first });
      }
    }
    this.labels(
      labels,
      order.map((it) => it.tau),
    );
  }

  /** The selected tau's sub-taus by name, and a reticle on the selected one. */
  moonLabels(tau: Tau, selected: string | null, heat: number): void {
    const { ctx } = this;
    ctx.font = '500 11px "JetBrains Mono", ui-monospace, monospace';
    for (const spot of tau.moons) {
      const orbit = tau.orbits.find((it) => it.name === spot.name);
      const lit = orbit?.web === true && tau.online && heat > 0;
      const right = spot.x >= tau.sx;
      const text = `/${spot.name}`;
      const width = ctx.measureText(text).width;
      const x = right ? spot.x + spot.r + 4 : spot.x - spot.r - 4 - width;
      ctx.globalAlpha = tau.shown;
      ctx.fillStyle = lit ? `rgba(${RGB.flare},0.95)` : `rgba(${RGB.ash},0.95)`;
      ctx.fillText(text, x, spot.y + 4);
      if (spot.name === selected) this.reticle(spot.x, spot.y, spot.r * 0.9, tau.shown);
    }
    ctx.globalAlpha = 1;
  }

  /** HUD labels with a leader line: the living and the nearest first, none on top of another. */
  labels(labels: Label[], taus: Tau[]): void {
    const { ctx } = this;
    const spacing = (value: string) => {
      if ("letterSpacing" in ctx) (ctx as { letterSpacing: string }).letterSpacing = value;
    };
    labels.sort(
      (a, b) =>
        Number(b.first) - Number(a.first) ||
        Number(b.heat > 0) - Number(a.heat > 0) ||
        b.p.scale - a.p.scale,
    );
    const placed: { x: number; y: number; w: number; h: number }[] = [];
    const size = this.labelSize;
    // Names are the owners' own words: drawn as written, never upper-cased.
    ctx.font = `600 ${size}px "Chakra Petch", sans-serif`;
    spacing("0.4px");
    for (const { tau, p, r, heat, alpha, first } of labels) {
      const text = tau.label;
      const width = ctx.measureText(text).width;
      const y = p.y - r * 1.1 - 6;
      const free = (x: number) => {
        const box = { x, y: y - size / 2, w: width + 10, h: size * 1.5 };
        const onLabel = placed.some(
          (b) =>
            box.x < b.x + b.w && box.x + box.w > b.x && box.y < b.y + b.h && box.y + box.h > b.y,
        );
        const onTau = taus.some(
          (other) =>
            other !== tau &&
            other.drawn &&
            !other.faint &&
            other.shown > 0.3 &&
            other.sx + other.sr * 0.6 > box.x &&
            other.sx - other.sr * 0.6 < box.x + box.w &&
            other.sy + other.sr * 0.6 > box.y &&
            other.sy - other.sr * 0.6 < box.y + box.h,
        );
        const offScreen = box.x < 4 || box.x + box.w > this.width - 4;
        return (onLabel || onTau) && !first ? null : offScreen ? null : box;
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
      ctx.fillText(text, left ? box.x : box.x + 6, y + size * 0.67);
    }
    spacing("0px");
  }
}
