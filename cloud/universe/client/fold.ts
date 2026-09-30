/**
 * The landing page below the hero: the flight goes on through the same sky.
 *
 * - "What tau is" is a small constellation. A faint wire links the traits' marks; a trait
 *   lights as you reach it (its mark above the lower third of the screen), and the wire
 *   between two lit traits carries a spark. Hovering a trait lights it too (site.css).
 * - Each section rises into view as it arrives.
 * - The portal draws itself when it comes into view: both legs up to the apex, the base out
 *   from the middle, then the floor and the mark. Under it, the hero's live count repeats.
 * - Under `prefers-reduced-motion`, or without this script, everything shows lit and still:
 *   `.fold-js` on <html> is what turns the ash-grey and hidden starting states on.
 */

import { maybeId, svg } from "./dom";

const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

/** A mark is reached once its centre is above this share of the viewport's height. */
const REACHED = 0.66;

/** Repeats the hero's live count (#sky-count, set by client/landing.ts) under the portal. */
function mirrorCount(): void {
  const source = maybeId<HTMLElement>("sky-count");
  const target = maybeId<HTMLElement>("portal-count");
  if (source === null || target === null) return;
  // The first text is "Loading…", not worth repeating; the count replaces it.
  const loading = source.textContent;
  new MutationObserver(() => {
    target.textContent = source.textContent === loading ? "" : (source.textContent ?? "");
  }).observe(source, { childList: true, characterData: true, subtree: true });
}

interface Wire {
  line: SVGPathElement;
  spark: SVGPathElement;
  from: number;
  to: number;
}

/** Where a trait's mark sits inside its glyph (the glyph's own units are CSS pixels). */
const MARK = { x: 20, y: 28.3 };
/** How far from a mark's centre the wire starts and ends, clear of the triangle. */
const CLEAR = 24;

/**
 * The route from one trait's mark to the next, or null when the next trait starts a new row.
 * It never crosses the words: beside each other, it runs between the first trait's name and
 * its text to the column's end, then angles across the gap to the next mark; one under the
 * other, it runs straight down the column of marks.
 */
function route(a: HTMLElement, b: HTMLElement): string | null {
  const ax = a.offsetLeft + MARK.x;
  const ay = a.offsetTop + MARK.y;
  const bx = b.offsetLeft + MARK.x;
  const by = b.offsetTop + MARK.y;
  const f = (n: number) => n.toFixed(1);
  if (Math.abs(bx - ax) < 2) {
    if (by - ay < CLEAR * 3) return null;
    return `M${f(ax)} ${f(ay + CLEAR)}V${f(by - CLEAR)}`;
  }
  if (bx < ax) return null;
  // Under the name even when it wraps: between it and the text under it.
  const name = a.querySelector<HTMLElement>("h3");
  const under = name === null ? 0 : name.offsetTop + name.offsetHeight + 7;
  const run = a.offsetTop + Math.max(MARK.y, under);
  const turn = a.offsetLeft + a.offsetWidth;
  const drop = run - ay;
  return (
    `M${f(ax + CLEAR)} ${f(ay)}` +
    (drop > 0.5 ? `L${f(ax + CLEAR + drop)} ${f(run)}` : "") +
    `H${f(turn)}L${f(bx - CLEAR - 8)} ${f(by)}H${f(bx - CLEAR)}`
  );
}

/**
 * Draws the wire between the traits' marks, in list order, and returns its pieces. It reads
 * the traits' layout offsets, not their boxes, so the rise into view does not bend it.
 */
function wire(list: HTMLElement, traits: HTMLElement[]): () => Wire[] {
  // Beside the list, not in it: a list holds only its items, and `:nth-child` staggers them.
  const layer = svg("svg", { class: "constellation-wire", "aria-hidden": "true", focusable: "false" });
  list.after(layer);
  let wires: Wire[] = [];

  const layout = () => {
    const width = Math.max(1, list.clientWidth);
    const height = Math.max(1, list.clientHeight);
    layer.setAttribute("viewBox", `0 0 ${width} ${height}`);
    layer.style.left = `${list.offsetLeft}px`;
    layer.style.top = `${list.offsetTop}px`;
    layer.style.width = `${width}px`;
    layer.style.height = `${height}px`;
    const lit = new Set(wires.filter((w) => w.line.classList.contains("is-lit")).map((w) => w.from));
    layer.replaceChildren();
    wires = [];
    for (let i = 0; i + 1 < traits.length; i++) {
      const d = route(traits[i]!, traits[i + 1]!);
      if (d === null) continue;
      const line = svg("path", { class: "wire", d });
      const spark = svg("path", { class: "wire-spark", d, pathLength: 1 });
      if (lit.has(i)) {
        line.classList.add("is-lit");
        spark.classList.add("is-lit");
      }
      layer.append(line, spark);
      wires.push({ line, spark, from: i, to: i + 1 });
    }
  };

  layout();
  new ResizeObserver(layout).observe(list);
  return () => wires;
}

/** Lights the traits you have reached, and the wires between two lit ones. */
function light(traits: HTMLElement[], marks: SVGRectElement[], wires: () => Wire[]): void {
  let queued = false;
  const update = () => {
    queued = false;
    const line = window.innerHeight * REACHED;
    const lit = marks.map((mark) => mark.getBoundingClientRect().top < line);
    traits.forEach((trait, i) => trait.classList.toggle("is-lit", lit[i]!));
    for (const w of wires()) {
      const on = lit[w.from]! && lit[w.to]!;
      w.line.classList.toggle("is-lit", on);
      w.spark.classList.toggle("is-lit", on);
    }
  };
  const request = () => {
    if (queued) return;
    queued = true;
    window.requestAnimationFrame(update);
  };
  window.addEventListener("scroll", request, { passive: true });
  window.addEventListener("resize", request);
  update();
}

/** Sections rise into view once, as they arrive. */
function reveal(sections: HTMLElement[]): void {
  const seen = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        entry.target.classList.add("is-in");
        seen.unobserve(entry.target);
      }
    },
    { rootMargin: "0px 0px -12% 0px" },
  );
  sections.forEach((section) => seen.observe(section));
}

/** The portal draws itself the first time it comes into view. */
function portal(element: HTMLElement): void {
  const seen = new IntersectionObserver(
    (entries) => {
      if (!entries.some((entry) => entry.isIntersecting)) return;
      element.classList.add("is-drawn");
      seen.disconnect();
    },
    { rootMargin: "0px 0px -18% 0px" },
  );
  seen.observe(element);
}

export function fold(): void {
  mirrorCount();
  const list = maybeId<HTMLElement>("constellation");
  const traits = list === null ? [] : [...list.querySelectorAll<HTMLElement>(".trait")];
  const marks = traits
    .map((trait) => trait.querySelector<SVGRectElement>(".glyph-core"))
    .filter((mark): mark is SVGRectElement => mark !== null);
  const wires = list !== null && marks.length === traits.length ? wire(list, traits) : () => [];

  if (reducedMotion.matches) return;
  document.documentElement.classList.add("fold-js");
  light(traits, marks, wires);
  reveal([...document.querySelectorAll<HTMLElement>(".leg")]);
  const gate = maybeId<HTMLElement>("portal");
  if (gate !== null) portal(gate);
}
