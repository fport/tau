/**
 * The quiet sky behind every page: grey stars on black, a few warm ones, in three depths
 * that drift with the scroll, the far ones slowest. It is the landing's sky seen from afar,
 * so the reading pages and the universe feel like one space.
 *
 * - One fixed canvas under the page (`.starfield` in site.css), drawn on scroll and resize
 *   only, never in a loop.
 * - Under `prefers-reduced-motion` the stars stay put when the page scrolls.
 * - Seeded: every page draws the same sky.
 * - The page works without it: the sky is then plain black.
 */

import { random } from "./cosmos";

interface Speck {
  /** 0..1 across the viewport and down one viewport's height. */
  x: number;
  y: number;
  size: number;
  alpha: number;
  warm: boolean;
}

interface Layer {
  /** How far it moves for a pixel of scroll. */
  speed: number;
  /** Stars per CSS pixel of viewport. */
  density: number;
  sizes: readonly number[];
  alpha: readonly [number, number];
  specks: Speck[];
}

const DEPTHS: readonly Omit<Layer, "specks">[] = [
  { speed: 0.015, density: 1 / 5_600, sizes: [1], alpha: [0.1, 0.34] },
  { speed: 0.05, density: 1 / 16_000, sizes: [1, 1, 1.5], alpha: [0.22, 0.6] },
  { speed: 0.12, density: 1 / 70_000, sizes: [1.5, 2.2], alpha: [0.45, 0.85] },
];

const GREY = "#e2e2e8";
const WARM = "#ffb080";

function specks(count: number, depth: Omit<Layer, "specks">, seed: number): Speck[] {
  const next = random(seed);
  const [low, high] = depth.alpha;
  return Array.from({ length: count }, () => ({
    x: next(),
    y: next(),
    size: depth.sizes[Math.floor(next() * depth.sizes.length)]!,
    alpha: low + Math.pow(next(), 2) * (high - low),
    warm: next() < 0.06,
  }));
}

/** A soft round glow for the brightest stars. */
function glow(colour: string): HTMLCanvasElement {
  const size = 32;
  const c = document.createElement("canvas");
  c.width = c.height = size;
  const g = c.getContext("2d")!;
  const grd = g.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  grd.addColorStop(0, colour);
  grd.addColorStop(1, "rgba(0,0,0,0)");
  g.fillStyle = grd;
  g.globalAlpha = 0.5;
  g.fillRect(0, 0, size, size);
  return c;
}

/** Puts the star field under the page. Safe to call once per page. */
export function starfield(): void {
  if (document.querySelector("canvas.starfield") !== null) return;
  const canvas = document.createElement("canvas");
  canvas.className = "starfield";
  canvas.setAttribute("aria-hidden", "true");
  const ctx = canvas.getContext("2d");
  if (ctx === null) return;
  document.body.prepend(canvas);

  const still = window.matchMedia("(prefers-reduced-motion: reduce)");
  const halo = { grey: glow(GREY), warm: glow(WARM) };
  let layers: Layer[] = [];
  let width = 1;
  let height = 1;
  let dpr = 1;
  let queued = false;

  const layout = () => {
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    width = Math.max(1, window.innerWidth);
    height = Math.max(1, window.innerHeight);
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
    const area = width * height;
    layers = DEPTHS.map((depth, i) => ({
      ...depth,
      specks: specks(Math.round(area * depth.density), depth, 101 + i * 7919),
    }));
  };

  const draw = () => {
    queued = false;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, width, height);
    const scroll = still.matches ? 0 : window.scrollY;
    for (const layer of layers) {
      const shift = (scroll * layer.speed) % height;
      for (const star of layer.specks) {
        let y = star.y * height - shift;
        if (y < -3) y += height;
        const x = star.x * width;
        if (star.size > 2) {
          ctx.globalAlpha = star.alpha;
          ctx.drawImage(star.warm ? halo.warm : halo.grey, x - 7, y - 7, 14, 14);
        }
        ctx.globalAlpha = star.alpha;
        ctx.fillStyle = star.warm ? WARM : GREY;
        ctx.fillRect(x - star.size / 2, y - star.size / 2, star.size, star.size);
      }
    }
    ctx.globalAlpha = 1;
  };

  const request = () => {
    if (queued) return;
    queued = true;
    window.requestAnimationFrame(draw);
  };

  layout();
  draw();
  window.addEventListener("scroll", () => {
    if (!still.matches) request();
  }, { passive: true });
  window.addEventListener("resize", () => {
    layout();
    request();
  });
}
