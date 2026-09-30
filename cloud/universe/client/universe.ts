/**
 * The universe graph: reads /api/universe and draws the taus as a force-directed graph, on
 * the universe page (`/universe`) and, full screen behind the hero, on the landing page.
 *
 * - Every tau and sub-tau is drawn as its ember sigil (cloud/shared/character.ts), seeded
 *   with its address (a sub-tau: `<address>/<name>`, burning in its tau's hue).
 * - Taus of the same owner share a hull, a sharp polygon; a tau without an owner is a group
 *   of its own.
 * - A tau's public sub-taus circle it as small sigils inside the hull (client/layout.ts).
 * - A mutual link is an energy beam: a thin line from one tau's hue to the other's over a
 *   faint glow, wider for more messages, with a pulse running along it.
 * - Online taus burn; offline ones are cold and still. Hover and selection show a square
 *   reticle.
 * - Hover or tap shows a tau's card; `#<address>` in the URL pins it, and
 *   `#<address>/<name>` pins the card of one of its sub-taus. A card links the tau's person
 *   page and a sub-tau's page when the universe knows them.
 * - The list under the graph is the keyboard path: every tau is a link to `#<address>`.
 * - Under `prefers-reduced-motion` the layout is computed up front and drawn once, and the
 *   characters stand still.
 * - On the landing page (`body.page-home`) there is no list, search or pinned card: a click
 *   opens the tau's person page (or its place on /universe), and the drawing keeps clear of
 *   the hero's text.
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
import type { PublicLink } from "../src/snapshot";
import { getJson } from "./api";
import { hueOf, type Kind, traits } from "../../shared/character";
import { byId, characterElement, html, link, maybeId, svg } from "./dom";
import {
  groupKey,
  hash01,
  matches,
  NODE_RADIUS,
  nameOffset,
  parseTarget,
  reach,
  SUB_RADIUS,
  type SubNodeData,
  subsOf,
  tauSubNodes,
} from "./layout";
import { MESSAGES, pageLanguage } from "./messages";
import { HANDLE, personPath, subPath, universePath } from "./paths";
import type { SiteSnapshot, SnapshotSub, SnapshotTau } from "./types";

type PublicTau = SnapshotTau;
type Snapshot = SiteSnapshot;

const HULL_PADDING = 16;
/** Sub-taus sit closer to the hull's edge than taus do. */
const SUB_HULL_PADDING = 10;
/** The graph never draws larger than this many pixels per unit (a small universe). */
const MAX_SCALE = 1.8;
const NAME_LABEL_LIMIT = 40;
const TINY_UNIVERSE = 5;
const JOIN_COMMAND = "tau net universe join";
/** A sigil is drawn this many times its node's radius wide. */
const CHARACTER_SCALE = 2.7;
/** Where a sigil's centre sits, as a fraction of its height: a tau's ring, a sub-tau's
 *  smaller triangle. */
const SIGIL_CENTRE: Record<Kind, number> = { tau: 0.52, sub: 0.58 };
/** The beams' middle: Flare, the brightest of the fire. */
const BEAM_MIDDLE = "#ffb25c";

interface GraphNode extends SimulationNodeDatum {
  tau: PublicTau;
  group: string;
  element: SVGGElement;
  label: SVGTextElement | null;
  /** Its public sub-taus, drawn at fixed offsets around it. */
  subs: SubNode[];
  /** How far its drawing reaches from its centre (its disc or its sub-taus). */
  reach: number;
}

/** A public sub-tau: a small node that follows its tau. */
interface SubNode {
  data: SubNodeData;
  parent: GraphNode;
  element: SVGGElement;
}

interface GraphLink extends SimulationLinkDatum<GraphNode> {
  data: PublicLink;
  element: SVGGElement;
  /** The glow, the beam and the hit area: lines between the two taus. */
  lines: SVGLineElement[];
  /** The travelling pulse: a path, so its dashes can be measured in `pathLength` units. */
  pulse: SVGPathElement;
  /** The beam's gradient, in the graph's own units, from one tau's hue to the other's. */
  gradient: SVGLinearGradientElement;
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
  subsById: Map<string, SubNode>;
  cards: Map<string, HTMLLIElement>;
  query: string;
  /** The selected tau, also when one of its sub-taus is selected. */
  selected: string | null;
  /** The selected sub-tau's id (`<address>/<name>`). */
  selectedSub: string | null;
  hovered: string | null;
  hoveredSub: string | null;
  simulation: Simulation<GraphNode, GraphLink> | null;
  view: { x: number; y: number; w: number; h: number } | null;
}

const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
const language = pageLanguage(document.documentElement.lang);
const t = MESSAGES[language];
const numberFormat = new Intl.NumberFormat(language, { notation: "compact" });
const dateFormat = new Intl.DateTimeFormat(language, { dateStyle: "medium" });
const relative = new Intl.RelativeTimeFormat(language, { numeric: "auto" });
/** The landing page: the graph is the hero's backdrop. */
const hero = document.body.classList.contains("page-home");

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

/** A tau's handle from the snapshot, when it is a valid one. */
function handleOf(tau: PublicTau): string | null {
  return typeof tau.handle === "string" && HANDLE.test(tau.handle) ? tau.handle : null;
}

/** The page of a sub-tau, when the universe gives one or its tau has a handle. */
function pageOfSub(tau: PublicTau, name: string): string | null {
  const sub = subsOf(tau).find((candidate) => candidate.name === name) as SnapshotSub | undefined;
  if (sub === undefined) return null;
  return subPath(sub, handleOf(tau), language);
}

// ---------------------------------------------------------------------------------------
// Page elements

const page = {
  count: byId<HTMLElement>("sky-count"),
  box: byId<HTMLDivElement>("graph-box"),
  graph: byId<SVGSVGElement>("graph"),
  message: byId<HTMLDivElement>("stage-message"),
  note: byId<HTMLParagraphElement>("stage-note"),
  detail: byId<HTMLElement>("detail"),
  sky: byId<HTMLElement>("sky"),
  // The universe page only: the search, the list of taus and the legend.
  search: maybeId<HTMLInputElement>("search"),
  list: maybeId<HTMLUListElement>("tau-list"),
  rosterCount: maybeId<HTMLParagraphElement>("roster-count"),
  rosterEmpty: maybeId<HTMLParagraphElement>("roster-empty"),
  legend: maybeId<HTMLParagraphElement>("legend"),
  // The landing page only: the hero's text, which the drawing keeps clear of.
  heroCopy: maybeId<HTMLElement>("hero-copy"),
  header: document.querySelector<HTMLElement>(".site-header"),
};

function layer(name: string): SVGGElement {
  const element = page.graph.querySelector<SVGGElement>(`.layer-${name}`);
  if (element === null) throw new Error(`missing layer ${name}`);
  return element;
}

/** The graph's <defs>, where each beam keeps its gradient. */
const defs: SVGDefsElement =
  page.graph.querySelector("defs") ?? page.graph.insertBefore(svg("defs"), page.graph.firstChild);

const layers = {
  hulls: layer("hulls"),
  links: layer("links"),
  subs: layer("subs"),
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
  const result = await getJson<Snapshot>("/api/universe");
  if (result.status !== 200 || result.data === null || !Array.isArray(result.data.taus)) {
    page.count.textContent = t.unavailable;
    showMessage([t.loadFailed], true);
    return;
  }
  render(result.data);
}

function render(snapshot: Snapshot): void {
  state?.simulation?.stop();
  const { stats } = snapshot;
  page.count.textContent = t.skyCount(
    count(t.msgs, stats.messages),
    numberFormat.format(stats.online),
    count(t.taus, stats.taus),
  );
  if (page.search !== null) page.search.disabled = stats.taus === 0;
  if (page.legend !== null) page.legend.hidden = stats.taus === 0;

  state = {
    snapshot,
    nodes: [],
    links: [],
    groups: [],
    byAddress: new Map(),
    subsById: new Map(),
    cards: new Map(),
    query: page.search?.value.trim().toLowerCase() ?? "",
    selected: null,
    selectedSub: null,
    hovered: null,
    hoveredSub: null,
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
  if (stats.taus < TINY_UNIVERSE && !hero) {
    page.note.replaceChildren(...withCommand(t.fewSoFar(count(t.taus, stats.taus))));
    page.note.hidden = false;
  } else {
    page.note.hidden = true;
  }

  buildGraph(state);
  if (!hero) applyHash();
}

// ---------------------------------------------------------------------------------------
// The graph

/** A sigil centred on its node: its ring's (or its triangle's) middle on the node's centre. */
function placedCharacter(seed: string, radius: number, kind: Kind): SVGSVGElement {
  const size = radius * CHARACTER_SCALE;
  const element = characterElement(seed, { size, kind, animated: !reducedMotion.matches });
  element.setAttribute("x", (-size / 2).toFixed(1));
  element.setAttribute("y", (-size * SIGIL_CENTRE[kind]).toFixed(1));
  element.classList.add("node-character");
  return element;
}

/** A square reticle of four corner brackets, `half` from the centre, arms `arm` long. */
function reticle(half: number, arm: number): SVGPathElement {
  const h = half.toFixed(1);
  const a = (half - arm).toFixed(1);
  const d =
    `M-${h} -${a}V-${h}H-${a}M${a} -${h}H${h}V-${a}` +
    `M${h} ${a}V${h}H${a}M-${a} ${h}H-${h}V${a}`;
  return svg("path", { class: "reticle", d });
}

/** The colour of a tau's triangle, for the ends of its beams. */
function hueColour(address: string): string {
  return hueOf(traits(address, "tau").hue).a;
}

function gradientStop(offset: string, colour: string, opacity: string): SVGStopElement {
  return svg("stop", { offset, "stop-color": colour, "stop-opacity": opacity });
}

function buildGraph(s: State): void {
  layers.hulls.replaceChildren();
  layers.links.replaceChildren();
  defs.replaceChildren();
  layers.subs.replaceChildren();
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
    element.append(reticle(NODE_RADIUS + 7, 5));
    element.append(svg("circle", { class: "node-hit", r: NODE_RADIUS + 2 }));
    element.append(placedCharacter(tau.address, NODE_RADIUS, "tau"));
    const subData = tauSubNodes(tau);
    let label: SVGTextElement | null = null;
    if (showNames) {
      label = svg("text", { class: "node-name", "text-anchor": "middle", y: nameOffset(subData) });
      label.textContent = tau.name;
      element.append(label);
    }
    layers.nodes.append(element);

    const node: GraphNode = {
      tau,
      group: key,
      element,
      label,
      subs: [],
      reach: reach(subData.length),
    };
    for (const data of subData) {
      const sub = buildSub(node, data, showNames);
      node.subs.push(sub);
      s.subsById.set(data.id, sub);
      wireSub(s, sub);
    }
    group.members.push(node);
    s.nodes.push(node);
    s.byAddress.set(tau.address, node);
    wireNode(s, node);
  }
  s.groups = [...groupsByKey.values()];

  const counts = s.snapshot.links.map((link) => link.messages);
  const most = Math.max(1, ...counts);
  s.snapshot.links.forEach((data, index) => {
    const source = s.byAddress.get(data.a);
    const target = s.byAddress.get(data.b);
    if (source === undefined || target === undefined) return;
    const id = `beam-${index}`;
    const gradient = svg("linearGradient", { id, gradientUnits: "userSpaceOnUse" });
    gradient.append(
      gradientStop("0", hueColour(data.a), "0.95"),
      gradientStop("0.5", BEAM_MIDDLE, "0.5"),
      gradientStop("1", hueColour(data.b), "0.95"),
    );
    defs.append(gradient);
    // Pulses start at different points and half of them run the other way.
    const element = svg("g", {
      class: `link beam-d${index % 6}${index % 2 === 1 ? " beam-back" : ""}`,
    });
    const width = 0.8 + 1.5 * Math.sqrt(data.messages / most);
    const glow = svg("line", { class: "beam-glow", "stroke-width": (width * 4).toFixed(2) });
    const line = svg("line", {
      class: "beam-line",
      stroke: `url(#${id})`,
      "stroke-width": width.toFixed(2),
    });
    const pulse = svg("path", { class: "beam-pulse", pathLength: 100 });
    const hit = svg("line", { class: "link-hit" });
    const title = svg("title");
    title.textContent = t.linkTitle(
      source.tau.name,
      target.tau.name,
      count(t.messages, data.messages),
    );
    hit.append(title);
    element.append(glow, line, pulse, hit);
    layers.links.append(element);
    s.links.push({ source, target, data, element, lines: [glow, line, hit], pulse, gradient });
  });

  // Spread the layout the way the free part of the box is shaped: wide on a desktop, tall on
  // a phone.
  const rect = page.box.getBoundingClientRect();
  const inset = insets(s, rect);
  const freeWidth = rect.width - inset.left - inset.right;
  const freeHeight = rect.height - inset.top - inset.bottom;
  const tall = freeWidth > 0 && freeHeight > 0 && freeWidth / freeHeight < 1;
  seedPositions(s, tall);
  page.graph.setAttribute(
    "aria-label",
    t.mapLabel(count(t.taus, s.nodes.length), count(t.links, s.links.length)),
  );

  const simulation = forceSimulation<GraphNode, GraphLink>(s.nodes)
    .force(
      "link",
      forceLink<GraphNode, GraphLink>(s.links)
        .distance((link) => (sameGroup(link) ? 60 : 150) + extra(link))
        .strength((link) => (sameGroup(link) ? 0.6 : 0.12)),
    )
    .force("charge", forceManyBody<GraphNode>().strength(-260).distanceMax(520))
    .force("collide", forceCollide<GraphNode>((node) => node.reach + 14))
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

/** A link between taus with sub-taus is longer by the room their sub-taus take. */
function extra(link: GraphLink): number {
  const source = link.source as GraphNode;
  const target = link.target as GraphNode;
  return source.reach + target.reach - 2 * NODE_RADIUS;
}

/**
 * A sub-tau's small node, drawn in its own layer under the taus: a short tether to its tau,
 * its character and, when names are shown, its `/name` outside the orbit. Its position is
 * set from its tau's in draw().
 */
function buildSub(parent: GraphNode, data: SubNodeData, showNames: boolean): SubNode {
  const element = svg("g", { class: `sub ${parent.tau.online ? "online" : "offline"}` });
  const distance = Math.hypot(data.dx, data.dy) || 1;
  const ux = data.dx / distance;
  const uy = data.dy / distance;
  // In the sub-tau's own coordinates its tau's centre is at (-dx, -dy).
  element.append(
    svg("line", {
      class: "sub-tether",
      x1: (-data.dx + ux * (NODE_RADIUS + 2)).toFixed(1),
      y1: (-data.dy + uy * (NODE_RADIUS + 2)).toFixed(1),
      x2: (-ux * (SUB_RADIUS + 1.5)).toFixed(1),
      y2: (-uy * (SUB_RADIUS + 1.5)).toFixed(1),
    }),
  );
  element.append(svg("circle", { class: "sub-hit", r: SUB_RADIUS + 5 }));
  element.append(reticle(SUB_RADIUS + 4, 3));
  element.append(placedCharacter(data.id, SUB_RADIUS, "sub"));
  if (showNames) {
    const label = svg("text", {
      class: "sub-name",
      x: data.labelX,
      y: data.labelY,
      "text-anchor": data.anchor,
    });
    label.textContent = data.label;
    element.append(label);
  }
  layers.subs.append(element);
  return { data, parent, element };
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

/**
 * A closed path through the hull of octagons around a group's members and their sub-taus,
 * so the sub-taus are inside their owner's hull. The edges stay straight: a hard, faceted
 * outline rather than a soft blob.
 */
function hullPath(members: GraphNode[]): { d: string; top: number; cx: number } {
  const points: [number, number][] = [];
  const octagon = (x: number, y: number, r: number) => {
    for (let i = 0; i < 8; i++) {
      const angle = ((i + 0.5) / 8) * Math.PI * 2;
      points.push([x + Math.cos(angle) * r, y + Math.sin(angle) * r]);
    }
  };
  for (const node of members) {
    const x = node.x ?? 0;
    const y = node.y ?? 0;
    octagon(x, y, NODE_RADIUS + HULL_PADDING);
    for (const sub of node.subs) {
      octagon(x + sub.data.dx, y + sub.data.dy, SUB_RADIUS + SUB_HULL_PADDING);
    }
  }
  const hull = polygonHull(points) ?? points;
  let d = "";
  let top = Infinity;
  hull.forEach(([x, y], index) => {
    d += `${index === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    if (y < top) top = y;
  });
  let cx = 0;
  for (const node of members) cx += node.x ?? 0;
  cx /= members.length;
  return { d: `${d}Z`, top, cx };
}

function draw(s: State, settled: boolean): void {
  for (const node of s.nodes) {
    const x = node.x ?? 0;
    const y = node.y ?? 0;
    node.element.setAttribute("transform", `translate(${x.toFixed(1)},${y.toFixed(1)})`);
    for (const sub of node.subs) {
      sub.element.setAttribute(
        "transform",
        `translate(${(x + sub.data.dx).toFixed(1)},${(y + sub.data.dy).toFixed(1)})`,
      );
    }
  }
  for (const link of s.links) {
    const source = link.source as GraphNode;
    const target = link.target as GraphNode;
    const x1 = (source.x ?? 0).toFixed(1);
    const y1 = (source.y ?? 0).toFixed(1);
    const x2 = (target.x ?? 0).toFixed(1);
    const y2 = (target.y ?? 0).toFixed(1);
    for (const element of [...link.lines, link.gradient]) {
      element.setAttribute("x1", x1);
      element.setAttribute("y1", y1);
      element.setAttribute("x2", x2);
      element.setAttribute("y2", y2);
    }
    link.pulse.setAttribute("d", `M${x1} ${y1}L${x2} ${y2}`);
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

interface Insets {
  left: number;
  right: number;
  top: number;
  bottom: number;
}

/**
 * The parts of the box the drawing keeps clear of, in pixels: a pinned card floating over the
 * graph (wide screens), and on the landing page the header and the hero's text when they
 * lie over the box.
 */
function insets(s: State, rect: DOMRect): Insets {
  const out: Insets = { left: 0, right: 0, top: 0, bottom: 0 };
  const floating =
    s.selected !== null &&
    !page.detail.hidden &&
    page.detail.classList.contains("pinned") &&
    window.getComputedStyle(page.detail).position === "absolute";
  if (floating) out.right = Math.min(page.detail.offsetWidth + 24, rect.width * 0.55);
  if (hero && page.heroCopy !== null) {
    const copy = page.heroCopy.getBoundingClientRect();
    const overlapX = Math.min(rect.right, copy.right) - Math.max(rect.left, copy.left);
    const overlapY = Math.min(rect.bottom, copy.bottom) - Math.max(rect.top, copy.top);
    if (overlapX > 0 && overlapY > 0) {
      if (copy.width < rect.width * 0.6) out.left = Math.max(out.left, copy.right - rect.left + 8);
      else out.bottom = Math.max(out.bottom, rect.bottom - copy.top + 8);
    }
  }
  if (hero && page.header !== null) {
    const bar = page.header.getBoundingClientRect();
    if (bar.bottom > rect.top && bar.top < rect.bottom) out.top = bar.bottom - rect.top + 8;
  }
  return out;
}

/**
 * Moves the viewBox toward the bounds of the drawing: the drawing fits into the part of the
 * box that nothing covers (see insets), the viewBox covers the whole box at the same scale,
 * so links and hulls may run on under the covered parts.
 */
function fit(s: State, immediate: boolean): void {
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const node of s.nodes) {
    const x = node.x ?? 0;
    const y = node.y ?? 0;
    // A tau with sub-taus reaches further than its disc.
    const around = node.reach - NODE_RADIUS;
    minX = Math.min(minX, x - around);
    maxX = Math.max(maxX, x + around);
    minY = Math.min(minY, y - around);
    maxY = Math.max(maxY, y + around);
  }
  const pad = NODE_RADIUS + HULL_PADDING + 24;
  minX -= pad;
  maxX += pad;
  minY -= pad + 14;
  maxY += pad + 18;
  const rect = page.box.getBoundingClientRect();
  const width = rect.width > 0 ? rect.width : 16;
  const height = rect.height > 0 ? rect.height : 9;
  const inset = rect.width > 0 ? insets(s, rect) : { left: 0, right: 0, top: 0, bottom: 0 };
  // A covered part never takes more than two thirds of the box.
  const usableW = Math.max(width / 3, width - inset.left - inset.right);
  const usableH = Math.max(height / 3, height - inset.top - inset.bottom);
  const scale = Math.min(
    usableW / Math.max(1, maxX - minX),
    usableH / Math.max(1, maxY - minY),
    rect.width > 0 ? MAX_SCALE : Infinity,
  );
  const cx = (minX + maxX) / 2;
  const cy = (minY + maxY) / 2;
  const left = Math.min(inset.left, width - usableW);
  const top = Math.min(inset.top, height - usableH);
  const target = {
    x: cx - (left + usableW / 2) / scale,
    y: cy - (top + usableH / 2) / scale,
    w: width / scale,
    h: height / scale,
  };
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

/** Hovering a sub-tau shows its card; a click pins it (`#<address>/<name>`). */
function wireSub(s: State, sub: SubNode): void {
  const id = sub.data.id;
  const parent = sub.parent.tau.address;
  sub.element.addEventListener("pointerenter", () => {
    s.hoveredSub = id;
    s.hovered = parent;
    highlight(s);
    if (s.selected === null) showSubDetail(s, sub, false);
  });
  sub.element.addEventListener("pointerleave", () => {
    if (s.hoveredSub === id) s.hoveredSub = null;
    if (s.hovered === parent) s.hovered = null;
    highlight(s);
    if (s.selected === null) hideDetail();
  });
  sub.element.addEventListener("pointerdown", (event) => event.stopPropagation());
  sub.element.addEventListener("click", () => select(id));
}

function toGraph(clientX: number, clientY: number): { x: number; y: number } {
  const matrix = page.graph.getScreenCTM();
  if (matrix === null) return { x: 0, y: 0 };
  const point = new DOMPoint(clientX, clientY).matrixTransform(matrix.inverse());
  return { x: point.x, y: point.y };
}

/**
 * On the landing page a click leaves for the tau's page: its person page when it has a
 * handle, a sub-tau's page when it has one, and otherwise its place on /universe.
 */
function leaveFor(target: string): void {
  const s = state;
  if (s === null) return;
  const found = parseTarget(s.snapshot, target);
  if (found === null) return;
  const tau = s.byAddress.get(found.address)?.tau;
  if (tau === undefined) return;
  const handle = handleOf(tau);
  const destination =
    found.sub !== null
      ? (pageOfSub(tau, found.sub) ?? universePath(target, language))
      : handle !== null
        ? personPath(handle, language)
        : universePath(found.address, language);
  window.location.assign(destination);
}

/**
 * Selecting goes through the URL, so a pinned tau can be shared and the back button works.
 * `target` is a tau's address or a sub-tau's id (`<address>/<name>`).
 */
function select(target: string | null): void {
  if (hero) {
    if (target !== null) leaveFor(target);
    return;
  }
  if (target === null) {
    if (window.location.hash !== "") {
      history.pushState(null, "", window.location.pathname + window.location.search);
    }
    applyHash();
    return;
  }
  const hash = `#${target}`;
  if (window.location.hash !== hash) window.location.hash = hash;
  else applyHash();
}

function applyHash(): void {
  const s = state;
  if (s === null) return;
  let hash = "";
  try {
    hash = decodeURIComponent(window.location.hash.slice(1));
  } catch {
    hash = "";
  }
  const target = parseTarget(s.snapshot, hash);
  s.selected = target?.address ?? null;
  s.selectedSub = target?.sub != null ? `${target.address}/${target.sub}` : null;
  for (const [key, card] of s.cards) {
    const anchor = card.querySelector("a");
    if (key === s.selected) anchor?.setAttribute("aria-current", "true");
    else anchor?.removeAttribute("aria-current");
  }
  highlight(s);
  const sub = s.selectedSub !== null ? s.subsById.get(s.selectedSub) : undefined;
  if (sub !== undefined) showSubDetail(s, sub, true);
  else if (s.selected !== null) showDetail(s, s.selected, true);
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
    // A selected sub-tau carries the selection mark, not its tau.
    node.element.classList.toggle("selected", node.tau.address === focus && s.selectedSub === null);
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
  for (const node of s.nodes) {
    const on = lit(node);
    for (const sub of node.subs) {
      sub.element.classList.toggle("dimmed", !on);
      sub.element.classList.toggle("selected", sub.data.id === s.selectedSub);
      sub.element.classList.toggle("hovered", sub.data.id === s.hoveredSub);
      sub.element.classList.toggle("named", on && (s.query !== "" || focus !== null));
    }
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

/** Empties the detail card and places it for `element`, with a close button when pinned. */
function openCard(element: SVGGElement, pinned: boolean): HTMLElement {
  const card = page.detail;
  card.replaceChildren();
  card.classList.toggle("pinned", pinned);
  // A hover card goes to the side away from the tau, so it never covers it. A pinned card
  // stays on the right, where fit() keeps the graph out of its way.
  let onLeft = false;
  if (!pinned && !hero) {
    const box = page.box.getBoundingClientRect();
    const spot = element.getBoundingClientRect();
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
  return card;
}

function statusLine(tau: PublicTau, now: number): HTMLParagraphElement {
  const status = html("p", `detail-status kicker ${tau.online ? "is-online" : "is-offline"}`);
  status.append(
    html("span", `pip ${tau.online ? "" : "pip-off"}`),
    tau.online ? t.online : t.lastSeen(ago(tau.last_seen, now)),
  );
  return status;
}

/** The card's head: the character, the status line and the name. */
function cardHead(seed: string, tau: PublicTau, name: string, now: number): HTMLElement {
  const head = html("div", "detail-head");
  const text = html("div", "detail-titles");
  text.append(statusLine(tau, now), html("h3", "detail-name", name));
  head.append(characterElement(seed, { size: 56, animated: !reducedMotion.matches }), text);
  return head;
}

/** The card of one sub-tau: its name, the tau it belongs to, its address and about line. */
function showSubDetail(s: State, sub: SubNode, pinned: boolean): void {
  const { data } = sub;
  const tau = sub.parent.tau;
  const card = openCard(sub.element, pinned);
  const parent = html("p", "detail-parent");
  const back = html("a", undefined, tau.name);
  back.href = hero ? universePath(tau.address, language) : `#${tau.address}`;
  parent.append(`${t.subOf} `, back);
  const addressLine = html("p", "detail-address");
  addressLine.append(html("code", undefined, data.id));
  card.append(cardHead(data.id, tau, data.label, s.snapshot.generated_at), parent, addressLine);
  if (data.about.trim() !== "") card.append(html("p", "detail-about", data.about));
  const own = pageOfSub(tau, data.name);
  if (own !== null && pinned) card.append(link(own, `${t.openPage} →`, "detail-page"));
  card.hidden = false;
}

function showDetail(s: State, address: string, pinned: boolean): void {
  const node = s.byAddress.get(address);
  if (node === undefined) return;
  const { tau } = node;
  const now = s.snapshot.generated_at;
  const card = openCard(node.element, pinned);
  const addressLine = html("p", "detail-address");
  addressLine.append(html("code", undefined, tau.address));
  card.append(cardHead(tau.address, tau, tau.name, now), addressLine);
  const handle = handleOf(tau);
  if (handle !== null) {
    card.append(link(personPath(handle, language), `@${handle}`, "detail-handle"));
  }

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

  const subs = subsOf(tau);
  if (subs.length > 0) {
    card.append(html("h4", "detail-heading", t.subTaus));
    const list = html("ul", "detail-subs");
    for (const sub of subs) {
      const chip = html("a", "sub-chip", `/${sub.name}`);
      chip.href = hero
        ? (pageOfSub(tau, sub.name) ?? universePath(`${tau.address}/${sub.name}`, language))
        : `#${tau.address}/${sub.name}`;
      if (sub.about.trim() !== "") chip.title = sub.about;
      const item = html("li");
      item.append(chip);
      list.append(item);
    }
    card.append(list);
  }

  const links = s.snapshot.links
    .filter((link) => link.a === address || link.b === address)
    .map((link) => ({ peer: link.a === address ? link.b : link.a, messages: link.messages }))
    .sort((x, y) => y.messages - x.messages);
  if (links.length === 0) {
    card.append(html("p", "detail-none", t.noLinks));
  } else {
    card.append(html("h4", "detail-heading", t.talksWith));
    const list = html("ul", "detail-links");
    for (const entry of links) {
      const peer = s.byAddress.get(entry.peer);
      const item = html("li");
      const anchor = html("a", undefined, peer?.tau.name ?? entry.peer);
      anchor.href = hero ? universePath(entry.peer, language) : `#${entry.peer}`;
      item.append(anchor, html("span", "detail-count", count(t.msgs, entry.messages)));
      list.append(item);
    }
    card.append(list);
  }
  if (handle !== null && pinned) {
    card.append(link(personPath(handle, language), `${t.openPage} →`, "detail-page"));
  }
  card.hidden = false;
}

// ---------------------------------------------------------------------------------------
// The list under the graph (also the keyboard path into the graph)

function renderList(s: State): void {
  const list = page.list;
  if (list === null) return;
  list.replaceChildren();
  s.cards.clear();
  const now = s.snapshot.generated_at;
  const degree = new Map<string, number>();
  for (const entry of s.snapshot.links) {
    degree.set(entry.a, (degree.get(entry.a) ?? 0) + 1);
    degree.set(entry.b, (degree.get(entry.b) ?? 0) + 1);
  }

  for (const tau of s.snapshot.taus) {
    const item = html("li");
    const card = html("a", `tau-card ${tau.online ? "is-online" : "is-offline"}`);
    card.href = `#${tau.address}`;

    const head = html("span", "tau-card-head");
    const titles = html("span", "tau-card-titles");
    const status = html("span", "tau-card-name");
    status.append(html("span", `pip ${tau.online ? "" : "pip-off"}`), tau.name);
    titles.append(status, html("span", "tau-card-address", tau.address));
    head.append(characterElement(tau.address, { size: 44, animated: false }), titles);
    card.append(head);
    const handle = handleOf(tau);
    if (handle !== null) card.append(html("span", "tau-card-handle", `@${handle}`));
    if (tau.owner.trim() !== "") {
      card.append(html("span", "tau-card-owner", t.ownerLine(tau.owner)));
    }
    if (tau.about.trim() !== "") card.append(html("span", "tau-card-about", tau.about));
    const subs = subsOf(tau);
    if (subs.length > 0) {
      const row = html("span", "tau-card-subs");
      row.append(html("span", "visually-hidden", `${t.subTaus}: `));
      for (const sub of subs) {
        const chip = html("span", "sub-chip", `/${sub.name}`);
        if (sub.about.trim() !== "") chip.title = sub.about;
        row.append(chip, " ");
      }
      card.append(row);
    }
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
    list.append(item);
    s.cards.set(tau.address, item);
  }
  filterList(s);
}

function filterList(s: State): void {
  if (page.list === null) return;
  const total = s.snapshot.taus.length;
  let shown = 0;
  for (const tau of s.snapshot.taus) {
    const visible = matches(tau, s.query);
    const card = s.cards.get(tau.address);
    if (card !== undefined) card.hidden = !visible;
    if (visible) shown++;
  }
  const online = s.snapshot.stats.online;
  if (page.rosterCount !== null) {
    page.rosterCount.textContent =
      s.query === ""
        ? t.listed(numberFormat.format(total), numberFormat.format(online))
        : t.matching(numberFormat.format(shown), numberFormat.format(total));
  }
  const empty = page.rosterEmpty;
  if (empty === null) return;
  if (total === 0) {
    empty.textContent = t.nobodyYet;
    empty.hidden = false;
  } else if (shown === 0) {
    empty.textContent = t.noMatch(page.search?.value.trim() ?? "");
    empty.hidden = false;
  } else {
    empty.hidden = true;
  }
}

// ---------------------------------------------------------------------------------------
// Wiring

const search = page.search;
if (search !== null) {
  search.addEventListener("input", () => {
    if (state === null) return;
    state.query = search.value.trim().toLowerCase();
    filterList(state);
    highlight(state);
  });

  search.addEventListener("keydown", (event) => {
    if (state === null) return;
    if (event.key === "Enter") {
      const first = state.snapshot.taus.find((tau) => matches(tau, state?.query ?? ""));
      if (first !== undefined) select(first.address);
    } else if (event.key === "Escape") {
      search.value = "";
      state.query = "";
      filterList(state);
      highlight(state);
    }
  });
}

page.graph.addEventListener("pointerdown", (event) => {
  if (event.target === page.graph) select(null);
});

if (!hero) window.addEventListener("hashchange", applyHash);

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
