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
  clamp,
  easeIn,
  easeInOut,
  easeOut,
  frame,
  type Frame,
  lerp,
  PORTAL,
  PORTAL_DISTANCE,
  projector,
  type Rect,
  span,
  stars,
  tauPath,
} from "./cosmos";
import { byId, characterElement, html } from "./dom";
import { fold } from "./fold";
import { MESSAGES, pageLanguage } from "./messages";
import { buildWorld, Painter, RGB, type Tau } from "./painter";
import { starfield } from "./starfield";
import type { SiteSnapshot } from "./types";

const language = pageLanguage(document.documentElement.lang);
const t = MESSAGES[language];
const numberFormat = new Intl.NumberFormat(language, { notation: "compact" });
const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

/** Set once the opening has played in this tab. */
const SEEN_KEY = "tau.portal";
/** Where the opening ends and the universe only drifts. */
const END = PORTAL.settle[1] + 0.2;

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
  let world = buildWorld(null, t.yourTau);
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
    world = buildWorld(snapshot, t.yourTau);
    if (opened && !still) {
      // The universe arrived after the opening: its taus light now.
      const now = (performance.now() - origin) / 1000;
      world.taus.forEach((tau, i) => (tau.ignite = now + i * 0.09));
    }
    redraw();
  });
}

starfield();
start();
fold();
