/**
 * A stand-in for the shared character generator (cloud/shared/character.ts, ADR 0013 §8),
 * with the same signature: `character(seed, opts) → SVG string`. scripts/build.mjs bundles
 * the shared one instead as soon as it exists; nothing else changes.
 *
 * Deterministic per seed: a triangle body in one colour of a fixed neon palette, two eyes.
 * The idle motion is a CSS class (host.css), off under prefers-reduced-motion.
 */

export interface CharacterOptions {
  size?: number;
  animated?: boolean;
  label?: string;
  /** A tau or a sub-tau; the shared generator derives it from the seed when left out. */
  kind?: "tau" | "sub";
}

const PALETTE = ["#ff2e3e", "#ff7a1a", "#ffd60a", "#2bff88", "#1ee3ff", "#4d7cff", "#b14dff", "#ff4dd2"];

function hash(seed: string): number {
  let h = 2166136261;
  for (let i = 0; i < seed.length; i++) {
    h ^= seed.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

function escapeXml(text: string): string {
  return text.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
}

export function character(seed: string, opts: CharacterOptions = {}): string {
  const h = hash(seed);
  const size = opts.size ?? 64;
  const colour = PALETTE[h % PALETTE.length] ?? "#ff2e3e";
  const lean = ((h >> 3) % 7) - 3;
  const eye = 2 + ((h >> 6) % 2);
  const gap = 6 + ((h >> 7) % 4);
  const label = escapeXml(opts.label ?? seed);
  const classes = `tau-char${opts.animated ? " tau-char--idle" : ""}`;
  return (
    `<svg xmlns="http://www.w3.org/2000/svg" class="${classes}" role="img" aria-label="${label}" width="${size}" height="${size}" viewBox="0 0 64 64">` +
    `<g class="tau-char-body">` +
    `<path d="M${32 + lean} 6 L58 56 L6 56 Z" fill="none" stroke="${colour}" stroke-width="2.5" stroke-linejoin="miter"/>` +
    `<path d="M${32 + lean} 14 L50 50 L14 50 Z" fill="${colour}" fill-opacity="0.12"/>` +
    `<rect x="${32 - gap - eye}" y="36" width="${eye * 2}" height="${eye * 2}" fill="#e8ecf1"/>` +
    `<rect x="${32 + gap - eye}" y="36" width="${eye * 2}" height="${eye * 2}" fill="#e8ecf1"/>` +
    `</g></svg>`
  );
}
