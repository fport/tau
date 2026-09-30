/**
 * The universe page (`/universe`): the whole viewport is the live universe, drawn by the
 * landing's engine (client/painter.ts), with the page's controls as HUD over the sky.
 *
 * - Arriving, the camera flies in from far away, star streaks and all, and the taus light
 *   one by one. Then the universe drifts slowly until someone touches it.
 * - Drag turns the universe, the wheel or a pinch zooms, and the buttons do both.
 * - A click on a tau (or `#<address>` in the URL) flies the camera to it, names its
 *   sub-taus and opens its card in the panel; `#<address>/<name>` does the same for one of
 *   its sub-taus. Selecting goes through the URL, so a pinned tau can be shared and the back
 *   button works. What is not next to the selection goes faint.
 * - The search dims the taus that do not match and filters the list; Enter picks the first.
 * - The panel holds the list of taus (the keyboard path: every tau is a link to
 *   `#<address>`), a tau's card, or how to add your tau. It stands at the right on wide
 *   screens and rises from the bottom on narrow ones; the universe keeps clear of it.
 * - Under `prefers-reduced-motion` nothing moves by itself: no fly-in, no drift, no sparks;
 *   the camera jumps and the universe is drawn only when something changes.
 *
 * Everything the directory returns is drawn as canvas text or set with textContent, never
 * parsed as HTML. The page's own strings come from client/messages.ts.
 */

import { getJson } from "./api";
import {
  type Camera,
  clamp,
  closeUp,
  easeOut,
  fitBox,
  type Point,
  projector,
  type Rect,
  span,
  stars,
} from "./cosmos";
import { byId, characterElement, html, link } from "./dom";
import { matches, parseTarget, subsOf } from "./layout";
import { MESSAGES, pageLanguage } from "./messages";
import { type Beam, buildWorld, type Focus, Painter, type Tau, type World } from "./painter";
import { HANDLE, personPath, subPath } from "./paths";
import type { SiteSnapshot, SnapshotSub, SnapshotTau } from "./types";

const language = pageLanguage(document.documentElement.lang);
const t = MESSAGES[language];
const numberFormat = new Intl.NumberFormat(language, { notation: "compact" });
const dateFormat = new Intl.DateTimeFormat(language, { dateStyle: "medium" });
const relative = new Intl.RelativeTimeFormat(language, { numeric: "auto" });
const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

const TINY_UNIVERSE = 5;
const JOIN_COMMAND = "tau net universe join";
/** The camera's usual tilt: a little from above. */
const PITCH = -0.22;
/** How far the camera may come, and how many overviews it may back away. */
const NEAREST = 160;
const FARTHEST = 2.6;
/** How much nearer than a plain fit the whole universe is shown. */
const OVERVIEW_ZOOM = 0.82;
/** A pointer that moves farther than this between down and up is a drag, not a click. */
const DRAG_SLOP = 5;
/** After the last touch, the universe starts drifting again. */
const IDLE_MS = 4_000;

const page = {
  sky: byId<HTMLElement>("sky"),
  canvas: byId<HTMLCanvasElement>("cosmos"),
  count: byId<HTMLElement>("sky-count"),
  message: byId<HTMLElement>("stage-message"),
  note: byId<HTMLElement>("stage-note"),
  legend: byId<HTMLElement>("legend"),
  search: byId<HTMLInputElement>("search"),
  card: byId<HTMLElement>("cosmos-card"),
  tools: document.querySelector<HTMLElement>(".u-tools"),
  zoomIn: byId<HTMLButtonElement>("zoom-in"),
  zoomOut: byId<HTMLButtonElement>("zoom-out"),
  reset: byId<HTMLButtonElement>("reset-view"),
  openList: byId<HTMLButtonElement>("open-list"),
  openJoin: byId<HTMLButtonElement>("open-join"),
  listCount: byId<HTMLElement>("list-count"),
  panel: byId<HTMLElement>("panel"),
  back: byId<HTMLButtonElement>("panel-back"),
  close: byId<HTMLButtonElement>("panel-close"),
  roster: byId<HTMLElement>("roster"),
  rosterTitle: byId<HTMLElement>("taus-title"),
  rosterCount: byId<HTMLElement>("roster-count"),
  rosterEmpty: byId<HTMLElement>("roster-empty"),
  list: byId<HTMLUListElement>("tau-list"),
  detail: byId<HTMLElement>("detail"),
  join: byId<HTMLElement>("join"),
  joinTitle: byId<HTMLElement>("join-title"),
  skip: document.getElementById("skip-list"),
  header: document.querySelector<HTMLElement>(".site-header"),
};

// ---------------------------------------------------------------------------------------
// Words

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
function handleOf(tau: SnapshotTau): string | null {
  return typeof tau.handle === "string" && HANDLE.test(tau.handle) ? tau.handle : null;
}

function subOf(tau: SnapshotTau, name: string): SnapshotSub | undefined {
  return subsOf(tau).find((sub) => sub.name === name) as SnapshotSub | undefined;
}

// ---------------------------------------------------------------------------------------
// State

type PanelMode = "list" | "detail" | "join";

const state = {
  snapshot: null as SiteSnapshot | null,
  world: buildWorld(null, t.yourTau) as World,
  query: "",
  selected: null as Tau | null,
  selectedSub: null as string | null,
  hovered: null as Tau | null,
  panel: null as PanelMode | null,
  /** List items by address, for the current mark. */
  items: new Map<string, HTMLLIElement>(),
  /** When the universe arrived, for the taus lighting one by one. */
  arrived: 0,
};

/** Where the camera is, and where it is going. */
interface View extends Point {
  yaw: number;
  pitch: number;
  dist: number;
  cx: number;
  cy: number;
}

const still = reducedMotion.matches;
const painter = new Painter(page.canvas);
painter.labelSize = 13;
const sky = stars(window.innerWidth < 760 ? 1_400 : 2_600);
const view: View = { x: 0, y: 0, z: 0, yaw: 0.4, pitch: PITCH, dist: 1_000, cx: 0, cy: 0 };
const goal: View = { ...view };
let overview = { cx: 0, cy: 0, dist: 1_000 };
let lastTouch = 0;
let dirty = true;

function touched(): void {
  lastTouch = performance.now();
  dirty = true;
}

// ---------------------------------------------------------------------------------------
// The camera

/** The part of the sky the universe keeps to: under the header, clear of the panel. */
function freeBox(): Rect {
  const sky = page.sky.getBoundingClientRect();
  const box: Rect = { left: 0, top: 0, right: painter.width, bottom: painter.height };
  const header = page.header?.getBoundingClientRect();
  if (header !== undefined) box.top = Math.max(0, header.bottom - sky.top) + 8;
  const tools = page.tools?.getBoundingClientRect();
  if (tools !== undefined && tools.height > 0) box.bottom = tools.top - sky.top - 8;
  if (!page.panel.hidden) {
    const panel = page.panel.getBoundingClientRect();
    if (panel.left - sky.left > painter.width * 0.4) box.right = panel.left - sky.left - 12;
    else box.bottom = Math.min(box.bottom, panel.top - sky.top - 8);
  }
  if (box.bottom - box.top < 160) box.bottom = box.top + 160;
  return box;
}

function layout(): void {
  // The HUD starts under the header, which wraps onto two lines on phones.
  const header = page.header?.getBoundingClientRect().height ?? 64;
  page.sky.style.setProperty("--top", `${Math.round(header)}px`);
  painter.resize();
  const fit = fitBox(freeBox(), state.world.reach, painter.focal);
  // The page is the universe: it may come nearer than the landing's framing.
  overview = { ...fit, dist: Math.max(NEAREST * 2, fit.dist * OVERVIEW_ZOOM) };
  aim();
  if (still) Object.assign(view, goal);
  dirty = true;
}

/** Points the camera at the selection, or at the whole universe. */
function aim(): void {
  const box = freeBox();
  goal.cx = (box.left + box.right) / 2;
  goal.cy = (box.top + box.bottom) / 2;
  const tau = state.selected;
  if (tau === null) {
    goal.x = goal.y = goal.z = 0;
    goal.dist = overview.dist;
    return;
  }
  goal.x = tau.x;
  goal.y = tau.y;
  goal.z = tau.z;
  goal.dist = closeUp(
    tau.orbits.map((orbit) => orbit.radius),
    painter.focal,
    overview.dist,
  );
}

function zoom(factor: number): void {
  goal.dist = clamp(goal.dist * factor, NEAREST, overview.dist * FARTHEST);
  touched();
}

function turn(yaw: number, pitch: number): void {
  goal.yaw += yaw;
  goal.pitch = clamp(goal.pitch + pitch, -1.2, 0.5);
  if (still) Object.assign(view, goal);
  touched();
}

// ---------------------------------------------------------------------------------------
// Drawing

function neighbours(tau: Tau): Set<Tau> {
  const around = new Set([tau]);
  for (const beam of state.world.beams) {
    if (beam.a === tau) around.add(beam.b);
    if (beam.b === tau) around.add(beam.a);
  }
  return around;
}

function focus(): Focus {
  const selected = state.selected;
  const around = selected !== null ? neighbours(selected) : null;
  const query = state.query;
  const dim = (tau: Tau) =>
    around !== null
      ? !around.has(tau)
      : query !== "" && (tau.tau === null || !matches(tau.tau, query));
  return {
    selected,
    sub: state.selectedSub,
    hovered: state.hovered,
    dim,
    dimBeam: (beam: Beam) =>
      selected !== null
        ? beam.a !== selected && beam.b !== selected
        : query !== "" && (dim(beam.a) || dim(beam.b)),
  };
}

/** The taus light one by one after the universe arrives. */
function light(now: number): void {
  const age = still ? 1_000 : (now - state.arrived) / 1000;
  state.world.taus.forEach((tau, i) => {
    const at = 0.35 + i * 0.07;
    tau.shown = easeOut(span(age, at - 0.3, at + 0.5));
    tau.heat = easeOut(span(age, at, at + 0.7));
  });
  state.world.beams.forEach((beam, i) => {
    beam.reveal = easeOut(span(age, 0.9 + i * 0.04, 1.7 + i * 0.04));
  });
}

let lastDist = view.dist;

function draw(now: number): void {
  light(now);
  const clock = still ? 0 : now / 1000;
  const cam: Camera = {
    target: { x: view.x, y: view.y, z: view.z },
    yaw: view.yaw,
    pitch: view.pitch,
    dist: view.dist,
    cx: view.cx,
    cy: view.cy,
    focal: painter.focal,
  };
  // Star streaks only while the camera really flies in, not while it settles.
  const closing = lastDist - view.dist;
  const streak = still || closing < 3 ? 0 : Math.min(closing * 5, 900);
  lastDist = view.dist;
  const project = projector(cam);
  const lens = focus();
  painter.clear();
  painter.haze(project, state.world.taus.some((tau) => tau.online) ? 1 : 0.3);
  painter.stars(project, view.dist, sky, clock, 1, streak);
  painter.owners(project, state.world.owners, lens);
  painter.beams(project, state.world.beams, clock, !still, lens);
  painter.taus(project, state.world.taus, clock, lens);
  if (state.hovered !== null) placeCard(state.hovered);
}

let last = performance.now();
let lastFrame = 0;

function loop(now: number): void {
  window.requestAnimationFrame(loop);
  if (document.hidden) return;
  const dt = Math.min(0.05, (now - last) / 1000);
  last = now;
  const idle = now - lastTouch > IDLE_MS;

  if (!still) {
    if (idle && state.selected === null && !dragging) goal.yaw += dt * 0.03;
    const k = 1 - Math.exp(-dt * 4.2);
    for (const key of ["x", "y", "z", "yaw", "pitch", "dist", "cx", "cy"] as const) {
      view[key] += (goal[key] - view[key]) * k;
    }
    // Settled and untouched: the universe only drifts, 30 frames a second are enough.
    const moving = Math.abs(goal.dist - view.dist) > 1 || !idle;
    if (!moving && now - lastFrame < 30) return;
  } else if (!dirty) {
    return;
  }
  lastFrame = now;
  dirty = false;
  draw(now);
}

// ---------------------------------------------------------------------------------------
// Pointing

/** The tau, or the sub-tau of a tau, under a point of the canvas. */
function pick(x: number, y: number): { tau: Tau; sub: string | null } | null {
  const candidates = state.world.taus.filter((tau) => tau.drawn && tau.tau !== null);
  // Sub-taus first: they sit close to their tau and are small.
  for (const tau of candidates) {
    const named = tau === state.selected;
    for (const moon of tau.moons) {
      if (!named && moon.r < 7) continue;
      if (Math.hypot(moon.x - x, moon.y - y) < moon.r) return { tau, sub: moon.name };
    }
  }
  let best: Tau | null = null;
  let bestDistance = Infinity;
  for (const tau of candidates) {
    const d = Math.hypot(tau.sx - x, tau.sy - y);
    if (d < tau.sr && d < bestDistance) {
      best = tau;
      bestDistance = d;
    }
  }
  return best === null ? null : { tau: best, sub: null };
}

let cardFor: Tau | null = null;

function placeCard(tau: Tau): void {
  const width = page.card.offsetWidth;
  const x =
    tau.sx + tau.sr + 12 + width > painter.width - 12
      ? tau.sx - tau.sr - 12 - width
      : tau.sx + tau.sr + 12;
  page.card.style.transform = `translate(${Math.round(x)}px, ${Math.round(tau.sy - 24)}px)`;
}

/** The small card on hover: who it is, whether it is alive, how busy. */
function showCard(tau: Tau | null): void {
  const data = tau?.tau ?? null;
  if (tau === null || data === null || tau === state.selected) {
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
    head.append(characterElement(data.address, { size: 44, animated: false }), names);
    const status = html("p", `cosmos-card-state${data.online ? " is-live" : ""}`);
    status.append(
      html("span", `pip ${data.online ? "pip-live" : "pip-off"}`),
      html("span", undefined, data.online ? t.online : t.offline),
    );
    const facts = [
      count(t.publicSubs, subsOf(data).length),
      count(t.links, tau.links),
      count(t.msgs, tau.messages),
    ];
    page.card.replaceChildren(head, status, html("p", "cosmos-card-facts", facts.join(" · ")));
  }
  page.card.hidden = false;
  placeCard(tau);
}

const pointers = new Map<number, { x: number; y: number }>();
let press: { x: number; y: number; moved: number } | null = null;
let pinch = 0;
let dragging = false;

function local(event: PointerEvent | MouseEvent): { x: number; y: number } {
  const rect = page.canvas.getBoundingClientRect();
  return { x: event.clientX - rect.left, y: event.clientY - rect.top };
}

function spread(): number {
  const [a, b] = [...pointers.values()];
  return a !== undefined && b !== undefined ? Math.hypot(a.x - b.x, a.y - b.y) : 0;
}

page.canvas.addEventListener("pointerdown", (event) => {
  page.canvas.setPointerCapture(event.pointerId);
  const at = local(event);
  pointers.set(event.pointerId, at);
  if (pointers.size === 1) press = { ...at, moved: 0 };
  if (pointers.size === 2) pinch = spread();
  touched();
});

page.canvas.addEventListener("pointermove", (event) => {
  const at = local(event);
  const before = pointers.get(event.pointerId);
  if (before === undefined) {
    // Hover (a mouse or a pen, not pressed).
    if (event.pointerType === "touch") return;
    const hit = pick(at.x, at.y);
    const tau = hit?.tau ?? null;
    if (tau !== state.hovered) {
      state.hovered = tau;
      dirty = true;
    }
    page.canvas.classList.toggle("is-pointing", hit !== null);
    showCard(hit?.sub == null ? tau : null);
    return;
  }
  pointers.set(event.pointerId, at);
  if (pointers.size === 2) {
    const now = spread();
    if (pinch > 0 && now > 0) zoom(pinch / now);
    pinch = now;
    dragging = true;
    return;
  }
  const dx = at.x - before.x;
  const dy = at.y - before.y;
  if (press !== null) press.moved += Math.hypot(dx, dy);
  if (press !== null && press.moved > DRAG_SLOP) {
    dragging = true;
    page.canvas.classList.add("is-dragging");
    showCard(null);
    turn(-dx * 0.006, dy * 0.004);
    view.yaw = goal.yaw;
    view.pitch = goal.pitch;
  }
});

function release(event: PointerEvent): void {
  pointers.delete(event.pointerId);
  if (pointers.size < 2) pinch = 0;
  if (pointers.size > 0) return;
  const at = local(event);
  const click = press !== null && !dragging && event.type === "pointerup";
  press = null;
  dragging = false;
  page.canvas.classList.remove("is-dragging");
  touched();
  if (!click) return;
  const hit = pick(at.x, at.y);
  if (hit === null) {
    if (state.selected !== null) select(null);
    return;
  }
  const address = hit.tau.tau!.address;
  select(hit.sub !== null ? `${address}/${hit.sub}` : address);
}

page.canvas.addEventListener("pointerup", release);
page.canvas.addEventListener("pointercancel", release);
page.canvas.addEventListener("pointerleave", () => {
  if (pointers.size > 0) return;
  state.hovered = null;
  page.canvas.classList.remove("is-pointing");
  showCard(null);
  dirty = true;
});

page.canvas.addEventListener(
  "wheel",
  (event) => {
    event.preventDefault();
    const scale = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? 400 : 1;
    zoom(Math.exp(event.deltaY * scale * (event.ctrlKey ? 0.01 : 0.0012)));
  },
  { passive: false },
);

page.canvas.addEventListener("keydown", (event) => {
  const keys: Record<string, () => void> = {
    ArrowLeft: () => turn(0.12, 0),
    ArrowRight: () => turn(-0.12, 0),
    ArrowUp: () => turn(0, -0.08),
    ArrowDown: () => turn(0, 0.08),
    "+": () => zoom(0.8),
    "=": () => zoom(0.8),
    "-": () => zoom(1.25),
    "0": () => resetView(),
    Home: () => resetView(),
  };
  const action = keys[event.key];
  if (action === undefined) return;
  event.preventDefault();
  action();
});

page.zoomIn.addEventListener("click", () => zoom(0.72));
page.zoomOut.addEventListener("click", () => zoom(1.39));
page.reset.addEventListener("click", () => resetView());

function resetView(): void {
  goal.pitch = PITCH;
  if (state.selected !== null) select(null);
  else {
    aim();
    touched();
  }
}

// ---------------------------------------------------------------------------------------
// Selecting, through the URL

/** `target` is a tau's address or a sub-tau's id (`<address>/<name>`), or null for none. */
function select(target: string | null): void {
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
  const snapshot = state.snapshot;
  if (snapshot === null) return;
  let hash = "";
  try {
    hash = decodeURIComponent(window.location.hash.slice(1));
  } catch {
    hash = "";
  }
  const target = parseTarget(snapshot, hash);
  const before = state.selected;
  state.selected = target !== null ? (state.world.byAddress.get(target.address) ?? null) : null;
  state.selectedSub = target?.sub ?? null;
  for (const [address, item] of state.items) {
    const anchor = item.querySelector("a");
    if (address === target?.address) anchor?.setAttribute("aria-current", "true");
    else anchor?.removeAttribute("aria-current");
  }
  showCard(null);
  if (state.selected !== null) {
    renderDetail(state.selected, state.selectedSub);
    openPanel("detail", false);
  } else if (before !== null && state.panel === "detail") {
    closePanel(false);
  }
  aim();
  if (still) Object.assign(view, goal);
  touched();
}

// ---------------------------------------------------------------------------------------
// The panel: the list, a tau's card, or how to add your tau

function openPanel(mode: PanelMode, moveFocus = true): void {
  state.panel = mode;
  page.panel.hidden = false;
  page.roster.hidden = mode !== "list";
  page.detail.hidden = mode !== "detail";
  page.join.hidden = mode !== "join";
  page.back.hidden = mode === "list" || state.snapshot === null || state.snapshot.taus.length === 0;
  page.openList.setAttribute("aria-expanded", String(mode === "list"));
  page.openJoin.setAttribute("aria-expanded", String(mode === "join"));
  document.body.classList.add("is-panel-open");
  if (moveFocus) (mode === "join" ? page.joinTitle : page.rosterTitle).focus();
  layout();
}

function closePanel(clearSelection = true): void {
  state.panel = null;
  page.panel.hidden = true;
  page.openList.setAttribute("aria-expanded", "false");
  page.openJoin.setAttribute("aria-expanded", "false");
  document.body.classList.remove("is-panel-open");
  if (clearSelection && state.selected !== null) select(null);
  layout();
}

page.openList.addEventListener("click", () => {
  if (state.panel === "list") closePanel();
  else openPanel("list");
});
page.openJoin.addEventListener("click", () => {
  if (state.panel === "join") closePanel();
  else openPanel("join");
});
page.close.addEventListener("click", () => closePanel());
page.back.addEventListener("click", () => {
  if (state.selected !== null) select(null);
  openPanel("list");
});
page.skip?.addEventListener("click", (event) => {
  event.preventDefault();
  openPanel("list");
});

window.addEventListener("keydown", (event) => {
  if (event.key !== "Escape" || event.target === page.search) return;
  if (state.panel !== null) closePanel();
  else if (state.selected !== null) select(null);
});

function statusLine(tau: SnapshotTau, now: number): HTMLParagraphElement {
  const status = html("p", `detail-status kicker ${tau.online ? "is-online" : "is-offline"}`);
  status.append(
    html("span", `pip ${tau.online ? "pip-live" : "pip-off"}`),
    tau.online ? t.online : t.lastSeen(ago(tau.last_seen, now)),
  );
  return status;
}

function cardHead(seed: string, tau: SnapshotTau, name: string, now: number): HTMLElement {
  const head = html("div", "detail-head");
  const text = html("div", "detail-titles");
  text.append(statusLine(tau, now), html("h2", "detail-name", name));
  head.append(characterElement(seed, { size: 64, animated: !still }), text);
  return head;
}

function renderDetail(node: Tau, subName: string | null): void {
  const tau = node.tau;
  const snapshot = state.snapshot;
  if (tau === null || snapshot === null) return;
  const now = snapshot.generated_at;
  const card = page.detail;
  card.replaceChildren();
  const handle = handleOf(tau);

  const sub = subName !== null ? subOf(tau, subName) : undefined;
  if (sub !== undefined) {
    const id = `${tau.address}/${sub.name}`;
    card.append(cardHead(id, tau, `/${sub.name}`, now));
    const parent = html("p", "detail-parent");
    const back = html("a", undefined, tau.name);
    back.href = `#${tau.address}`;
    parent.append(`${t.subOf} `, back);
    const addressLine = html("p", "detail-address");
    addressLine.append(html("code", undefined, id));
    card.append(parent, addressLine);
    if (sub.web === true) card.append(html("p", "detail-tag", t.chatTag));
    if (sub.about.trim() !== "") card.append(html("p", "detail-about", sub.about));
    const own = subPath(sub, handle, language);
    if (own !== null) card.append(link(own, `${t.openPage} →`, "detail-page button button-primary"));
    return;
  }

  card.append(cardHead(tau.address, tau, tau.name, now));
  const addressLine = html("p", "detail-address");
  addressLine.append(html("code", undefined, tau.address));
  card.append(addressLine);
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

  const subs = subsOf(tau) as SnapshotSub[];
  if (subs.length > 0) {
    card.append(html("h3", "detail-heading", t.subTaus));
    const list = html("ul", "detail-subs");
    for (const each of subs) {
      const chip = html("a", `sub-chip${each.web === true && tau.online ? " is-live" : ""}`);
      chip.textContent = `/${each.name}`;
      chip.href = `#${tau.address}/${each.name}`;
      if (each.about.trim() !== "") chip.title = each.about;
      const item = html("li");
      item.append(chip);
      list.append(item);
    }
    card.append(list);
  }

  const links = snapshot.links
    .filter((entry) => entry.a === tau.address || entry.b === tau.address)
    .map((entry) => ({
      peer: entry.a === tau.address ? entry.b : entry.a,
      messages: entry.messages,
    }))
    .sort((x, y) => y.messages - x.messages);
  if (links.length === 0) {
    card.append(html("p", "detail-none", t.noLinks));
  } else {
    card.append(html("h3", "detail-heading", t.talksWith));
    const list = html("ul", "detail-links");
    for (const entry of links) {
      const peer = state.world.byAddress.get(entry.peer)?.tau ?? null;
      const item = html("li");
      const anchor = html("a", peer?.online ? "is-online" : undefined);
      anchor.append(
        html("span", `pip ${peer?.online ? "pip-live" : "pip-off"}`),
        peer?.name ?? entry.peer,
      );
      anchor.href = `#${entry.peer}`;
      item.append(anchor, html("span", "detail-count", count(t.msgs, entry.messages)));
      list.append(item);
    }
    card.append(list);
  }
  if (handle !== null) {
    card.append(
      link(personPath(handle, language), `${t.openPage} →`, "detail-page button button-primary"),
    );
  }
}

function renderList(snapshot: SiteSnapshot): void {
  page.list.replaceChildren();
  state.items.clear();
  const now = snapshot.generated_at;
  const degree = new Map<string, number>();
  for (const entry of snapshot.links) {
    degree.set(entry.a, (degree.get(entry.a) ?? 0) + 1);
    degree.set(entry.b, (degree.get(entry.b) ?? 0) + 1);
  }
  // The living first, then by name.
  const taus = [...snapshot.taus].sort(
    (a, b) => Number(b.online) - Number(a.online) || a.name.localeCompare(b.name, language),
  );
  for (const tau of taus) {
    const item = html("li");
    const row = html("a", `tau-card u-row ${tau.online ? "is-online" : "is-offline"}`);
    row.href = `#${tau.address}`;
    const titles = html("span", "u-row-titles");
    const name = html("span", "u-row-name");
    name.append(html("span", `pip ${tau.online ? "pip-live" : "pip-off"}`), tau.name);
    titles.append(name, html("span", "tau-card-address", tau.address));
    row.append(characterElement(tau.address, { size: 40, animated: false }), titles);
    const subs = subsOf(tau) as SnapshotSub[];
    if (subs.length > 0) {
      const chips = html("span", "u-row-subs");
      chips.append(html("span", "visually-hidden", `${t.subTaus}: `));
      for (const sub of subs) {
        const chip = html(
          "span",
          `sub-chip${sub.web === true && tau.online ? " is-live" : ""}`,
          `/${sub.name}`,
        );
        if (sub.about.trim() !== "") chip.title = sub.about;
        chips.append(chip, " ");
      }
      row.append(chips);
    }
    const meta = [
      tau.owner.trim() !== "" ? t.ownerLine(tau.owner) : null,
      tau.online ? null : t.lastSeen(ago(tau.last_seen, now)),
      count(t.links, degree.get(tau.address) ?? 0),
    ].filter((part): part is string => part !== null);
    row.append(html("span", "u-row-meta", meta.join(" · ")));
    item.append(row);
    page.list.append(item);
    state.items.set(tau.address, item);
  }
  filterList();
}

function filterList(): void {
  const snapshot = state.snapshot;
  if (snapshot === null) return;
  const total = snapshot.taus.length;
  let shown = 0;
  for (const tau of snapshot.taus) {
    const visible = matches(tau, state.query);
    const item = state.items.get(tau.address);
    if (item !== undefined) item.hidden = !visible;
    if (visible) shown++;
  }
  page.rosterCount.textContent =
    state.query === ""
      ? t.listed(numberFormat.format(total), numberFormat.format(snapshot.stats.online))
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

page.search.addEventListener("input", () => {
  state.query = page.search.value.trim().toLowerCase();
  filterList();
  if (state.query !== "" && state.panel === null) openPanel("list", false);
  touched();
});

page.search.addEventListener("keydown", (event) => {
  const snapshot = state.snapshot;
  if (snapshot === null) return;
  if (event.key === "Enter") {
    const first = snapshot.taus.find((tau) => matches(tau, state.query));
    if (first !== undefined) select(first.address);
  } else if (event.key === "Escape") {
    page.search.value = "";
    state.query = "";
    filterList();
    touched();
  }
});

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

// ---------------------------------------------------------------------------------------
// Loading

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
  const line = html("p", "u-command");
  line.append(...withCommand(t.runOnHub));
  return line;
}

async function load(): Promise<void> {
  showMessage([t.loadingUniverse]);
  page.count.textContent = t.loading;
  const result = await getJson<SiteSnapshot>("/api/universe");
  if (result.status !== 200 || result.data === null || !Array.isArray(result.data.taus)) {
    page.count.textContent = t.unavailable;
    showMessage([t.loadFailed], true);
    return;
  }
  if (!Array.isArray(result.data.links)) result.data.links = [];
  render(result.data);
}

function render(snapshot: SiteSnapshot): void {
  const { stats } = snapshot;
  state.snapshot = snapshot;
  state.world = buildWorld(snapshot, t.yourTau);
  state.selected = null;
  state.arrived = performance.now();
  page.count.textContent =
    stats.taus === 0
      ? t.empty
      : t.skyCount(
          count(t.msgs, stats.messages),
          numberFormat.format(stats.online),
          count(t.taus, stats.taus),
        );
  page.search.disabled = stats.taus === 0;
  page.legend.hidden = stats.taus === 0;
  page.listCount.textContent = numberFormat.format(stats.taus);
  renderList(snapshot);

  if (stats.taus === 0) {
    showMessage([t.empty, commandLine()]);
    page.note.hidden = true;
  } else {
    page.message.hidden = true;
    if (stats.taus < TINY_UNIVERSE) {
      page.note.replaceChildren(...withCommand(t.fewSoFar(count(t.taus, stats.taus))));
      page.note.hidden = false;
    } else {
      page.note.hidden = true;
    }
  }

  layout();
  // Arriving: the camera flies in from far away.
  if (!still) {
    view.dist = goal.dist * 4.5;
    lastDist = view.dist;
    view.cx = goal.cx;
    view.cy = goal.cy;
  }
  applyHash();
}

window.addEventListener("hashchange", applyHash);
window.addEventListener("resize", layout);

layout();
Object.assign(view, goal);
window.requestAnimationFrame(loop);
void load();
