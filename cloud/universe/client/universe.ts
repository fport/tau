/**
 * The universe page: reads /api/universe and draws the taus as a force-directed graph.
 *
 * - Taus of the same owner share a soft hull; a tau without an owner is a group of its own.
 * - A mutual link is a dashed line, wider for more messages.
 * - Online taus glow (Flare), offline ones are dim.
 * - Hover or tap shows a tau's card; `#<address>` in the URL pins it.
 * - The list under the graph is the keyboard path: every tau is a link to `#<address>`.
 * - Under `prefers-reduced-motion` the layout is computed up front and drawn once.
 *
 * Everything the directory returns is set with textContent, never parsed as HTML. The
 * page's own strings come from client/messages.ts, in the language of `<html lang>`.
 */

import {
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  forceX,
  forceY,
  type Simulation,
  type SimulationLinkDatum,
  type SimulationNodeDatum,
} from "d3-force";
import { polygonHull } from "d3-polygon";
import type { PublicLink, PublicTau, Snapshot } from "../src/snapshot";
import { MESSAGES, pageLanguage } from "./messages";

const SVG_NS = "http://www.w3.org/2000/svg";
const NODE_RADIUS = 15;
const HULL_PADDING = 16;
/** The graph never draws larger than this many pixels per unit (a small universe). */
const MAX_SCALE = 1.8;
const NAME_LABEL_LIMIT = 40;
const TINY_UNIVERSE = 5;
const JOIN_COMMAND = "tau net universe join";

interface GraphNode extends SimulationNodeDatum {
  tau: PublicTau;
  group: string;
  element: SVGGElement;
  label: SVGTextElement | null;
}

interface GraphLink extends SimulationLinkDatum<GraphNode> {
  data: PublicLink;
  element: SVGGElement;
  line: SVGLineElement;
  hit: SVGLineElement;
}

interface Group {
  key: string;
  owner: string;
  members: GraphNode[];
  element: SVGGElement;
  path: SVGPathElement;
  label: SVGTextElement | null;
}

interface State {
  snapshot: Snapshot;
  nodes: GraphNode[];
  links: GraphLink[];
  groups: Group[];
  byAddress: Map<string, GraphNode>;
  cards: Map<string, HTMLLIElement>;
  query: string;
  selected: string | null;
  hovered: string | null;
  simulation: Simulation<GraphNode, GraphLink> | null;
  view: { x: number; y: number; w: number; h: number } | null;
}

const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
const language = pageLanguage(document.documentElement.lang);
const t = MESSAGES[language];
const numberFormat = new Intl.NumberFormat(language, { notation: "compact" });
const dateFormat = new Intl.DateTimeFormat(language, { dateStyle: "medium" });
const relative = new Intl.RelativeTimeFormat(language, { numeric: "auto" });
const graphemes = new Intl.Segmenter(language, { granularity: "grapheme" });

function byId<T extends HTMLElement | SVGElement>(id: string): T {
  const element = document.getElementById(id);
  if (element === null) throw new Error(`missing #${id}`);
  return element as T;
}

function svg<K extends keyof SVGElementTagNameMap>(
  name: K,
  attributes: Record<string, string | number> = {},
): SVGElementTagNameMap[K] {
  const element = document.createElementNS(SVG_NS, name);
  for (const [key, value] of Object.entries(attributes)) element.setAttribute(key, String(value));
  return element;
}

function html<K extends keyof HTMLElementTagNameMap>(
  name: K,
  className?: string,
  text?: string,
): HTMLElementTagNameMap[K] {
  const element = document.createElement(name);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

/** A counted noun: `count(t.taus, 3)` is "3 taus" or "3 tau". */
function count(message: (count: number, formatted: string) => string, value: number): string {
  return message(value, numberFormat.format(value));
}

/** A message with `{cmd}` as text around a code element holding the join command. */
function withCommand(message: string): (string | Node)[] {
  const [before = "", after = ""] = message.split("{cmd}");
  return [before, html("code", undefined, JOIN_COMMAND), after].filter((part) => part !== "");
}

function ago(seconds: number, now: number): string {
  const delta = Math.max(0, now - seconds);
  if (delta < 60) return t.justNow;
  if (delta < 3_600) return relative.format(-Math.floor(delta / 60), "minute");
  if (delta < 86_400) return relative.format(-Math.floor(delta / 3_600), "hour");
  return relative.format(-Math.floor(delta / 86_400), "day");
}

function initial(name: string): string {
  for (const { segment } of graphemes.segment(name.trim())) return segment.toUpperCase();
  return "·";
}

function groupKey(tau: PublicTau): string {
  const owner = tau.owner.trim().replace(/\s+/g, " ").toLowerCase();
  return owner === "" ? `tau:${tau.address}` : `owner:${owner}`;
}

function matches(tau: PublicTau, query: string): boolean {
  if (query === "") return true;
  return [tau.name, tau.owner, tau.address].some((field) => field.toLowerCase().includes(query));
}

/** A deterministic number in [0, 1) from a string, for stable starting positions. */
function hash01(text: string): number {
  let h = 2166136261;
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return (h >>> 0) / 4294967296;
}

// ---------------------------------------------------------------------------------------
// Page elements

const page = {
  count: byId<HTMLParagraphElement>("sky-count"),
  search: byId<HTMLInputElement>("search"),
  box: byId<HTMLDivElement>("graph-box"),
  graph: byId<SVGSVGElement>("graph"),
  message: byId<HTMLDivElement>("stage-message"),
  note: byId<HTMLParagraphElement>("stage-note"),
  detail: byId<HTMLElement>("detail"),
  list: byId<HTMLUListElement>("tau-list"),
  rosterCount: byId<HTMLParagraphElement>("roster-count"),
  rosterEmpty: byId<HTMLParagraphElement>("roster-empty"),
  legend: byId<HTMLParagraphElement>("legend"),
  sky: byId<HTMLElement>("sky"),
};

function layer(name: string): SVGGElement {
  const element = page.graph.querySelector<SVGGElement>(`.layer-${name}`);
  if (element === null) throw new Error(`missing layer ${name}`);
  return element;
}

const layers = {
  hulls: layer("hulls"),
  links: layer("links"),
  nodes: layer("nodes"),
};

let state: State | null = null;

// ---------------------------------------------------------------------------------------
// Loading and the states around the graph

function showMessage(parts: (string | Node)[], retry = false): void {
  page.message.replaceChildren();
  for (const part of parts) {
    page.message.append(typeof part === "string" ? html("p", undefined, part) : part);
  }
  if (retry) {
    const button = html("button", "button", t.tryAgain);
    button.type = "button";
    button.addEventListener("click", () => void load());
    page.message.append(button);
  }
  page.message.hidden = false;
}

function commandLine(): HTMLParagraphElement {
  const line = html("p", "stage-command");
  line.append(...withCommand(t.runOnHub));
  return line;
}

async function load(): Promise<void> {
  showMessage([t.loadingUniverse]);
  page.count.textContent = t.loading;
  let snapshot: Snapshot;
  try {
    const response = await fetch("/api/universe", { headers: { accept: "application/json" } });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    snapshot = (await response.json()) as Snapshot;
  } catch {
    page.count.textContent = t.unavailable;
    showMessage([t.loadFailed], true);
    return;
  }
  render(snapshot);
}

function render(snapshot: Snapshot): void {
  state?.simulation?.stop();
  const { stats } = snapshot;
  page.count.textContent = t.skyCount(
    count(t.msgs, stats.messages),
    numberFormat.format(stats.online),
    count(t.taus, stats.taus),
  );
  page.search.disabled = stats.taus === 0;
  page.legend.hidden = stats.taus === 0;

  state = {
    snapshot,
    nodes: [],
    links: [],
    groups: [],
    byAddress: new Map(),
    cards: new Map(),
    query: page.search.value.trim().toLowerCase(),
    selected: null,
    hovered: null,
    simulation: null,
    view: null,
  };

  renderList(state);

  if (stats.taus === 0) {
    page.graph.toggleAttribute("hidden", true);
    page.note.hidden = true;
    showMessage([t.empty, commandLine()]);
    return;
  }
  page.message.hidden = true;
  page.graph.toggleAttribute("hidden", false);
  if (stats.taus < TINY_UNIVERSE) {
    page.note.replaceChildren(...withCommand(t.fewSoFar(count(t.taus, stats.taus))));
    page.note.hidden = false;
  } else {
    page.note.hidden = true;
  }

  buildGraph(state);
  applyHash();
}

// ---------------------------------------------------------------------------------------
// The graph

function buildGraph(s: State): void {
  layers.hulls.replaceChildren();
  layers.links.replaceChildren();
  layers.nodes.replaceChildren();

  const showNames = s.snapshot.taus.length <= NAME_LABEL_LIMIT;
  const groupsByKey = new Map<string, Group>();

  for (const tau of s.snapshot.taus) {
    const key = groupKey(tau);
    let group = groupsByKey.get(key);
    if (group === undefined) {
      const element = svg("g", { class: "hull" });
      const path = svg("path");
      element.append(path);
      let label: SVGTextElement | null = null;
      if (tau.owner.trim() !== "") {
        label = svg("text", { class: "hull-label", "text-anchor": "middle" });
        label.textContent = tau.owner.trim();
        element.append(label);
      }
      layers.hulls.append(element);
      group = { key, owner: tau.owner.trim(), members: [], element, path, label };
      groupsByKey.set(key, group);
    }

    const element = svg("g", { class: `node ${tau.online ? "online" : "offline"}` });
    if (tau.online) element.append(svg("circle", { class: "halo", r: NODE_RADIUS + 3 }));
    element.append(svg("circle", { class: "ring", r: NODE_RADIUS + 6 }));
    element.append(svg("circle", { class: "disc", r: NODE_RADIUS }));
    const letter = svg("text", { class: "initial", "text-anchor": "middle", dy: "0.35em" });
    letter.textContent = initial(tau.name);
    element.append(letter);
    let label: SVGTextElement | null = null;
    if (showNames) {
      label = svg("text", { class: "node-name", "text-anchor": "middle", y: NODE_RADIUS + 16 });
      label.textContent = tau.name;
      element.append(label);
    }
    layers.nodes.append(element);

    const node: GraphNode = { tau, group: key, element, label };
    group.members.push(node);
    s.nodes.push(node);
    s.byAddress.set(tau.address, node);
    wireNode(s, node);
  }
  s.groups = [...groupsByKey.values()];

  const counts = s.snapshot.links.map((link) => link.messages);
  const most = Math.max(1, ...counts);
  for (const data of s.snapshot.links) {
    const source = s.byAddress.get(data.a);
    const target = s.byAddress.get(data.b);
    if (source === undefined || target === undefined) continue;
    const element = svg("g", { class: "link" });
    const width = 1.2 + 3.3 * Math.sqrt(data.messages / most);
    const line = svg("line", { class: "link-line", "stroke-width": width.toFixed(2) });
    const hit = svg("line", { class: "link-hit" });
    const title = svg("title");
    title.textContent = t.linkTitle(
      source.tau.name,
      target.tau.name,
      count(t.messages, data.messages),
    );
    hit.append(title);
    element.append(line, hit);
    layers.links.append(element);
    s.links.push({ source, target, data, element, line, hit });
  }

  // Spread the layout the way the box is shaped: wide on a desktop, tall on a phone.
  const rect = page.box.getBoundingClientRect();
  const tall = rect.width > 0 && rect.height > 0 && rect.width / rect.height < 1;
  seedPositions(s, tall);
  page.graph.setAttribute(
    "aria-label",
    t.mapLabel(count(t.taus, s.nodes.length), count(t.links, s.links.length)),
  );

  const simulation = forceSimulation<GraphNode, GraphLink>(s.nodes)
    .force(
      "link",
      forceLink<GraphNode, GraphLink>(s.links)
        .distance((link) => (sameGroup(link) ? 56 : 150))
        .strength((link) => (sameGroup(link) ? 0.6 : 0.12)),
    )
    .force("charge", forceManyBody<GraphNode>().strength(-240).distanceMax(520))
    .force("collide", forceCollide<GraphNode>(NODE_RADIUS + 12))
    .force("cluster", clusterForce(s))
    .force("x", forceX<GraphNode>(0).strength(tall ? 0.1 : 0.035))
    .force("y", forceY<GraphNode>(0).strength(tall ? 0.025 : 0.06));
  s.simulation = simulation;

  if (reducedMotion.matches) {
    simulation.stop();
    for (let i = 0; i < 320; i++) simulation.tick();
    draw(s, true);
  } else {
    simulation.on("tick", () => draw(s, false));
    simulation.on("end", () => draw(s, true));
  }
  highlight(s);
}

function sameGroup(link: GraphLink): boolean {
  const source = link.source as GraphNode;
  const target = link.target as GraphNode;
  return source.group === target.group;
}

/** Groups start on a circle, members close to their group's point. */
function seedPositions(s: State, tall: boolean): void {
  const radius = 90 * Math.sqrt(s.groups.length);
  s.groups.forEach((group, index) => {
    const angle = (index / Math.max(1, s.groups.length)) * Math.PI * 2 - Math.PI / 2;
    const cx = s.groups.length === 1 ? 0 : Math.cos(angle) * radius * (tall ? 0.6 : 1);
    const cy = s.groups.length === 1 ? 0 : Math.sin(angle) * radius * (tall ? 1 : 0.7);
    for (const node of group.members) {
      const jitter = hash01(node.tau.address) * Math.PI * 2;
      node.x = cx + Math.cos(jitter) * 24;
      node.y = cy + Math.sin(jitter) * 24;
    }
  });
}

/** Pulls every tau toward the centre of its owner's group. */
function clusterForce(s: State) {
  return (alpha: number) => {
    for (const group of s.groups) {
      if (group.members.length < 2) continue;
      let cx = 0;
      let cy = 0;
      for (const node of group.members) {
        cx += node.x ?? 0;
        cy += node.y ?? 0;
      }
      cx /= group.members.length;
      cy /= group.members.length;
      for (const node of group.members) {
        node.vx = (node.vx ?? 0) + (cx - (node.x ?? 0)) * 0.2 * alpha;
        node.vy = (node.vy ?? 0) + (cy - (node.y ?? 0)) * 0.2 * alpha;
      }
    }
  };
}

/** A closed, smoothed path through the hull of the circles around a group's members. */
function hullPath(members: GraphNode[]): { d: string; top: number; cx: number } {
  const points: [number, number][] = [];
  const r = NODE_RADIUS + HULL_PADDING;
  for (const node of members) {
    for (let i = 0; i < 16; i++) {
      const angle = (i / 16) * Math.PI * 2;
      points.push([(node.x ?? 0) + Math.cos(angle) * r, (node.y ?? 0) + Math.sin(angle) * r]);
    }
  }
  const hull = polygonHull(points) ?? points;
  const mid = (p: [number, number], q: [number, number]) => [(p[0] + q[0]) / 2, (p[1] + q[1]) / 2];
  const last = hull[hull.length - 1]!;
  const start = mid(last, hull[0]!);
  let d = `M${start[0]!.toFixed(1)},${start[1]!.toFixed(1)}`;
  for (let i = 0; i < hull.length; i++) {
    const p = hull[i]!;
    const q = hull[(i + 1) % hull.length]!;
    const m = mid(p, q);
    d += `Q${p[0].toFixed(1)},${p[1].toFixed(1)} ${m[0]!.toFixed(1)},${m[1]!.toFixed(1)}`;
  }
  let top = Infinity;
  let cx = 0;
  for (const [x, y] of hull) {
    if (y < top) top = y;
  }
  for (const node of members) cx += node.x ?? 0;
  cx /= members.length;
  return { d: `${d}Z`, top, cx };
}

function draw(s: State, settled: boolean): void {
  for (const node of s.nodes) {
    node.element.setAttribute(
      "transform",
      `translate(${(node.x ?? 0).toFixed(1)},${(node.y ?? 0).toFixed(1)})`,
    );
  }
  for (const link of s.links) {
    const source = link.source as GraphNode;
    const target = link.target as GraphNode;
    for (const line of [link.line, link.hit]) {
      line.setAttribute("x1", (source.x ?? 0).toFixed(1));
      line.setAttribute("y1", (source.y ?? 0).toFixed(1));
      line.setAttribute("x2", (target.x ?? 0).toFixed(1));
      line.setAttribute("y2", (target.y ?? 0).toFixed(1));
    }
  }
  for (const group of s.groups) {
    const { d, top, cx } = hullPath(group.members);
    group.path.setAttribute("d", d);
    if (group.label !== null) {
      group.label.setAttribute("x", cx.toFixed(1));
      group.label.setAttribute("y", (top - 7).toFixed(1));
    }
  }
  fit(s, settled);
}

/**
 * Moves the viewBox toward the bounds of the drawing, keeping the box's aspect ratio. A
 * pinned detail card that floats over the graph (wide screens) keeps its part of the box
 * free: the drawing fits into the rest.
 */
function fit(s: State, immediate: boolean): void {
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const node of s.nodes) {
    const x = node.x ?? 0;
    const y = node.y ?? 0;
    minX = Math.min(minX, x);
    maxX = Math.max(maxX, x);
    minY = Math.min(minY, y);
    maxY = Math.max(maxY, y);
  }
  const pad = NODE_RADIUS + HULL_PADDING + 24;
  minX -= pad;
  maxX += pad;
  minY -= pad + 14;
  maxY += pad + 18;
  const rect = page.box.getBoundingClientRect();
  const floating =
    s.selected !== null &&
    !page.detail.hidden &&
    window.getComputedStyle(page.detail).position === "absolute";
  const reserved = floating ? Math.min(page.detail.offsetWidth + 24, rect.width * 0.55) : 0;
  const usable = Math.max(1, rect.width - reserved);
  const aspect = rect.width > 0 && rect.height > 0 ? usable / rect.height : 16 / 9;
  let w = Math.max(maxX - minX, usable / MAX_SCALE);
  let h = Math.max(maxY - minY, w / aspect);
  w = Math.max(w, h * aspect);
  h = w / aspect;
  const total = rect.width > 0 ? (w * rect.width) / usable : w;
  const target = { x: (minX + maxX) / 2 - w / 2, y: (minY + maxY) / 2 - h / 2, w: total, h };
  const view = s.view;
  const next =
    immediate || view === null
      ? target
      : {
          x: view.x + (target.x - view.x) * 0.15,
          y: view.y + (target.y - view.y) * 0.15,
          w: view.w + (target.w - view.w) * 0.15,
          h: view.h + (target.h - view.h) * 0.15,
        };
  s.view = next;
  page.graph.setAttribute(
    "viewBox",
    `${next.x.toFixed(1)} ${next.y.toFixed(1)} ${next.w.toFixed(1)} ${next.h.toFixed(1)}`,
  );
}

let fitFrame = 0;

/** Glides the viewBox to its new target over a few frames (at once under reduced motion). */
function refit(s: State): void {
  cancelAnimationFrame(fitFrame);
  if (s.nodes.length === 0) return;
  if (reducedMotion.matches) {
    fit(s, true);
    return;
  }
  let frames = 0;
  const step = () => {
    fit(s, frames >= 24);
    frames += 1;
    if (frames <= 24) fitFrame = requestAnimationFrame(step);
  };
  step();
}

// ---------------------------------------------------------------------------------------
// Interaction

function wireNode(s: State, node: GraphNode): void {
  const address = node.tau.address;
  node.element.addEventListener("pointerenter", () => {
    s.hovered = address;
    highlight(s);
    if (s.selected === null) showDetail(s, address, false);
  });
  node.element.addEventListener("pointerleave", () => {
    if (s.hovered === address) s.hovered = null;
    highlight(s);
    if (s.selected === null) hideDetail();
  });

  let start: { x: number; y: number } | null = null;
  let dragging = false;
  node.element.addEventListener("pointerdown", (event) => {
    event.stopPropagation();
    start = { x: event.clientX, y: event.clientY };
    dragging = false;
    if (!reducedMotion.matches) node.element.setPointerCapture(event.pointerId);
  });
  node.element.addEventListener("pointermove", (event) => {
    if (start === null || reducedMotion.matches || s.simulation === null) return;
    if (!dragging && Math.hypot(event.clientX - start.x, event.clientY - start.y) < 4) return;
    if (!dragging) {
      dragging = true;
      s.simulation.alphaTarget(0.25).restart();
    }
    const point = toGraph(event.clientX, event.clientY);
    node.fx = point.x;
    node.fy = point.y;
  });
  const release = (event: PointerEvent) => {
    if (start === null) return;
    start = null;
    if (node.element.hasPointerCapture(event.pointerId)) {
      node.element.releasePointerCapture(event.pointerId);
    }
    if (dragging) {
      dragging = false;
      node.fx = null;
      node.fy = null;
      s.simulation?.alphaTarget(0);
      return;
    }
    select(address);
  };
  node.element.addEventListener("pointerup", release);
  node.element.addEventListener("pointercancel", (event) => {
    start = null;
    dragging = false;
    node.fx = null;
    node.fy = null;
    s.simulation?.alphaTarget(0);
    if (node.element.hasPointerCapture(event.pointerId)) {
      node.element.releasePointerCapture(event.pointerId);
    }
  });
}

function toGraph(clientX: number, clientY: number): { x: number; y: number } {
  const matrix = page.graph.getScreenCTM();
  if (matrix === null) return { x: 0, y: 0 };
  const point = new DOMPoint(clientX, clientY).matrixTransform(matrix.inverse());
  return { x: point.x, y: point.y };
}

/** Selecting goes through the URL, so a pinned tau can be shared and the back button works. */
function select(address: string | null): void {
  if (address === null) {
    if (window.location.hash !== "") {
      history.pushState(null, "", window.location.pathname + window.location.search);
    }
    applyHash();
    return;
  }
  const hash = `#${address}`;
  if (window.location.hash !== hash) window.location.hash = hash;
  else applyHash();
}

function applyHash(): void {
  const s = state;
  if (s === null) return;
  let address: string | null = null;
  try {
    address = decodeURIComponent(window.location.hash.slice(1)) || null;
  } catch {
    address = null;
  }
  s.selected = address !== null && s.byAddress.has(address) ? address : null;
  for (const [key, card] of s.cards) {
    const link = card.querySelector("a");
    if (key === s.selected) link?.setAttribute("aria-current", "true");
    else link?.removeAttribute("aria-current");
  }
  highlight(s);
  if (s.selected !== null) showDetail(s, s.selected, true);
  else hideDetail();
  refit(s);
}

function neighbours(s: State, address: string): Set<string> {
  const around = new Set([address]);
  for (const link of s.snapshot.links) {
    if (link.a === address) around.add(link.b);
    if (link.b === address) around.add(link.a);
  }
  return around;
}

/** Dims what is not selected, not matching the search, or not next to the hovered tau. */
function highlight(s: State): void {
  const focus = s.selected ?? null;
  const around = focus !== null ? neighbours(s, focus) : null;
  const lit = (node: GraphNode) =>
    around !== null ? around.has(node.tau.address) : matches(node.tau, s.query);

  for (const node of s.nodes) {
    const on = lit(node);
    node.element.classList.toggle("dimmed", !on);
    node.element.classList.toggle("selected", node.tau.address === focus);
    node.element.classList.toggle("hovered", node.tau.address === s.hovered);
    node.element.classList.toggle("named", on && (s.query !== "" || focus !== null));
  }
  for (const link of s.links) {
    const source = link.source as GraphNode;
    const target = link.target as GraphNode;
    const on =
      focus !== null
        ? source.tau.address === focus || target.tau.address === focus
        : lit(source) && lit(target);
    link.element.classList.toggle("dimmed", !on);
    link.element.classList.toggle(
      "active",
      s.hovered !== null && (source.tau.address === s.hovered || target.tau.address === s.hovered),
    );
  }
  for (const group of s.groups) {
    group.element.classList.toggle("dimmed", !group.members.some(lit));
  }
}

// ---------------------------------------------------------------------------------------
// The detail card

function hideDetail(): void {
  page.detail.hidden = true;
  page.detail.replaceChildren();
}

function showDetail(s: State, address: string, pinned: boolean): void {
  const node = s.byAddress.get(address);
  if (node === undefined) return;
  const { tau } = node;
  const now = s.snapshot.generated_at;
  const card = page.detail;
  card.replaceChildren();
  card.classList.toggle("pinned", pinned);
  // A hover card goes to the side away from the tau, so it never covers it. A pinned card
  // stays on the right, where fit() keeps the graph out of its way.
  let onLeft = false;
  if (!pinned) {
    const box = page.box.getBoundingClientRect();
    const spot = node.element.getBoundingClientRect();
    onLeft = spot.left + spot.width / 2 > box.left + box.width / 2;
  }
  card.classList.toggle("on-left", onLeft);

  if (pinned) {
    const close = html("button", "detail-close", "×");
    close.type = "button";
    close.setAttribute("aria-label", t.close);
    close.addEventListener("click", () => select(null));
    card.append(close);
  }

  const status = html("p", `detail-status ${tau.online ? "is-online" : "is-offline"}`);
  status.append(
    html("span", `dot ${tau.online ? "dot-online" : "dot-offline"}`),
    tau.online ? t.online : t.lastSeen(ago(tau.last_seen, now)),
  );
  const name = html("h3", "detail-name", tau.name);
  const addressLine = html("p", "detail-address");
  addressLine.append(html("code", undefined, tau.address));
  card.append(status, name, addressLine);

  if (tau.about.trim() !== "") card.append(html("p", "detail-about", tau.about));

  const facts = html("dl", "detail-facts");
  const fact = (term: string, value: string) => {
    const row = html("div");
    row.append(html("dt", undefined, term), html("dd", undefined, value));
    facts.append(row);
  };
  if (tau.owner.trim() !== "") fact(t.owner, tau.owner);
  fact(t.joined, dateFormat.format(new Date(tau.joined_at * 1000)));
  if (tau.online) fact(t.lastReport, ago(tau.last_seen, now));
  card.append(facts);

  const links = s.snapshot.links
    .filter((link) => link.a === address || link.b === address)
    .map((link) => ({ peer: link.a === address ? link.b : link.a, messages: link.messages }))
    .sort((x, y) => y.messages - x.messages);
  if (links.length === 0) {
    card.append(html("p", "detail-none", t.noLinks));
  } else {
    card.append(html("h4", "detail-heading", t.talksWith));
    const list = html("ul", "detail-links");
    for (const link of links) {
      const peer = s.byAddress.get(link.peer);
      const item = html("li");
      const anchor = html("a", undefined, peer?.tau.name ?? link.peer);
      anchor.href = `#${link.peer}`;
      item.append(anchor, html("span", "detail-count", count(t.msgs, link.messages)));
      list.append(item);
    }
    card.append(list);
  }
  card.hidden = false;
}

// ---------------------------------------------------------------------------------------
// The list under the graph (also the keyboard path into the graph)

function renderList(s: State): void {
  page.list.replaceChildren();
  s.cards.clear();
  const now = s.snapshot.generated_at;
  const degree = new Map<string, number>();
  for (const link of s.snapshot.links) {
    degree.set(link.a, (degree.get(link.a) ?? 0) + 1);
    degree.set(link.b, (degree.get(link.b) ?? 0) + 1);
  }

  for (const tau of s.snapshot.taus) {
    const item = html("li");
    const card = html("a", `tau-card ${tau.online ? "is-online" : "is-offline"}`);
    card.href = `#${tau.address}`;

    const head = html("span", "tau-card-head");
    head.append(
      html("span", `dot ${tau.online ? "dot-online" : "dot-offline"}`),
      html("span", "tau-card-name", tau.name),
    );
    card.append(head);
    card.append(html("span", "tau-card-address", tau.address));
    if (tau.owner.trim() !== "") {
      card.append(html("span", "tau-card-owner", t.ownerLine(tau.owner)));
    }
    if (tau.about.trim() !== "") card.append(html("span", "tau-card-about", tau.about));
    const meta = html("span", "tau-card-meta");
    const links = degree.get(tau.address) ?? 0;
    meta.textContent = [
      tau.online ? t.online : t.lastSeen(ago(tau.last_seen, now)),
      t.joinedOn(dateFormat.format(new Date(tau.joined_at * 1000))),
      count(t.links, links),
    ].join(", ");
    card.append(meta);

    card.addEventListener("click", () => {
      // The hash change selects the tau; bring the graph into view if it is off screen.
      const top = page.sky.getBoundingClientRect().top;
      if (top < -page.sky.offsetHeight / 2 || top > window.innerHeight) {
        page.sky.scrollIntoView({ behavior: reducedMotion.matches ? "auto" : "smooth" });
      }
    });

    item.append(card);
    page.list.append(item);
    s.cards.set(tau.address, item);
  }
  filterList(s);
}

function filterList(s: State): void {
  const total = s.snapshot.taus.length;
  let shown = 0;
  for (const tau of s.snapshot.taus) {
    const visible = matches(tau, s.query);
    const card = s.cards.get(tau.address);
    if (card !== undefined) card.hidden = !visible;
    if (visible) shown++;
  }
  const online = s.snapshot.stats.online;
  page.rosterCount.textContent =
    s.query === ""
      ? t.listed(numberFormat.format(total), numberFormat.format(online))
      : t.matching(numberFormat.format(shown), numberFormat.format(total));
  if (total === 0) {
    page.rosterEmpty.textContent = t.nobodyYet;
    page.rosterEmpty.hidden = false;
  } else if (shown === 0) {
    page.rosterEmpty.textContent = t.noMatch(page.search.value.trim());
    page.rosterEmpty.hidden = false;
  } else {
    page.rosterEmpty.hidden = true;
  }
}

// ---------------------------------------------------------------------------------------
// Wiring

page.search.addEventListener("input", () => {
  if (state === null) return;
  state.query = page.search.value.trim().toLowerCase();
  filterList(state);
  highlight(state);
});

page.search.addEventListener("keydown", (event) => {
  if (state === null) return;
  if (event.key === "Enter") {
    const first = state.snapshot.taus.find((tau) => matches(tau, state?.query ?? ""));
    if (first !== undefined) select(first.address);
  } else if (event.key === "Escape") {
    page.search.value = "";
    state.query = "";
    filterList(state);
    highlight(state);
  }
});

page.graph.addEventListener("pointerdown", (event) => {
  if (event.target === page.graph) select(null);
});

window.addEventListener("hashchange", applyHash);

let resizeFrame = 0;
new ResizeObserver(() => {
  cancelAnimationFrame(resizeFrame);
  resizeFrame = requestAnimationFrame(() => {
    if (state !== null && state.nodes.length > 0) fit(state, true);
  });
}).observe(page.box);

for (const button of document.querySelectorAll<HTMLButtonElement>("button[data-copy]")) {
  button.addEventListener("click", async () => {
    const source = document.getElementById(button.dataset.copy ?? "");
    const text = source?.textContent ?? "";
    try {
      await navigator.clipboard.writeText(text);
      button.textContent = t.copied;
    } catch {
      const range = document.createRange();
      if (source !== null) range.selectNodeContents(source);
      window.getSelection()?.removeAllRanges();
      window.getSelection()?.addRange(range);
      button.textContent = t.selected;
    }
    window.setTimeout(() => {
      button.textContent = t.copy;
    }, 2000);
  });
}

void load();
