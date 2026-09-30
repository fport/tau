/**
 * The universe page's layout data, without the DOM: owner groups, search matching and the
 * public sub-taus that circle their tau.
 *
 * A sub-tau is drawn like one of tiny's small agents around its builder: a small node at a
 * fixed offset from its tau, so it follows the tau wherever the simulation moves it and
 * stays inside the owner's hull. The offsets keep clear of the top of the orbit, where the
 * owner's name sits over the hull, and of its bottom, where the tau's name sits.
 *
 * This module is pure (no DOM, no d3), so the Worker's tests can check it.
 */

import type { PublicSub, PublicTau, Snapshot } from "../src/snapshot";

/** The radius of a tau's disc, in the graph's units. */
export const NODE_RADIUS = 15;
/** The radius of a sub-tau's disc. */
export const SUB_RADIUS = 6.5;
/** The shortest distance from a tau's centre to its sub-taus' centres. */
export const MIN_ORBIT = NODE_RADIUS + 14;
/** The space between two neighbouring sub-taus on an orbit. */
const SUB_SPACING = 2 * SUB_RADIUS + 5;
/** The gap between a sub-tau's disc and its `/name` label: clear of the selection ring. */
const LABEL_GAP = 7;

/** One public sub-tau, placed relative to its tau. */
export interface SubNodeData {
  /** `<address>/<name>`: the sub-tau's network address, and its `#` in the page's URL. */
  id: string;
  /** The address of the tau it belongs to. */
  parent: string;
  name: string;
  /** `/name`. */
  label: string;
  about: string;
  /** Its direction from the tau, in radians (SVG: 0 is right, π/2 is down). */
  angle: number;
  /** Its centre relative to the tau's centre. */
  dx: number;
  dy: number;
  /** Where its label goes, relative to its own centre, and how the label is anchored. */
  labelX: number;
  labelY: number;
  anchor: "start" | "middle" | "end";
}

/** The subs of a tau from any snapshot (an older universe sent none). */
export function subsOf(tau: Pick<PublicTau, "subs">): PublicSub[] {
  return Array.isArray(tau.subs) ? tau.subs : [];
}

/** The orbit of `count` sub-taus: wide enough that neighbours never touch. */
export function orbitRadius(count: number): number {
  if (count <= 0) return 0;
  return Math.max(MIN_ORBIT, (count * SUB_SPACING) / (2 * Math.PI));
}

/** How far a tau's drawing reaches from its centre: its disc, or its sub-taus. */
export function reach(count: number): number {
  return count > 0 ? orbitRadius(count) + SUB_RADIUS : NODE_RADIUS;
}

/**
 * The direction of the `index`-th of `count` sub-taus: evenly spread from the right, never
 * straight up or down. A count divisible by four would put one on each, so it turns by half
 * a step.
 */
export function subAngle(index: number, count: number): number {
  const step = (2 * Math.PI) / Math.max(1, count);
  return (count % 4 === 0 ? step / 2 : 0) + index * step;
}

function round(value: number): number {
  return Math.round(value * 100) / 100;
}

/** The sub-taus of one tau, in the order the snapshot lists them (by name). */
export function tauSubNodes(tau: Pick<PublicTau, "address" | "subs">): SubNodeData[] {
  const subs = subsOf(tau);
  const orbit = orbitRadius(subs.length);
  return subs.map((sub, index) => {
    const angle = subAngle(index, subs.length);
    const ux = Math.cos(angle);
    const uy = Math.sin(angle);
    const out = SUB_RADIUS + LABEL_GAP;
    return {
      id: `${tau.address}/${sub.name}`,
      parent: tau.address,
      name: sub.name,
      label: `/${sub.name}`,
      about: sub.about,
      angle,
      dx: round(ux * orbit),
      dy: round(uy * orbit),
      labelX: round(ux * out),
      // Text hangs from its baseline: below the disc it needs a line's height, beside it half.
      labelY: round(uy * out + (uy > 0.4 ? 8 : uy < -0.4 ? -1 : 3.5)),
      anchor: ux > 0.35 ? "start" : ux < -0.35 ? "end" : "middle",
    };
  });
}

/** Every public sub-tau of a snapshot, tau by tau. */
export function subNodes(snapshot: Pick<Snapshot, "taus">): SubNodeData[] {
  return snapshot.taus.flatMap((tau) => tauSubNodes(tau));
}

/** Where a tau's name goes under it: below its disc and below its lowest sub-tau. */
export function nameOffset(subs: readonly Pick<SubNodeData, "dy">[]): number {
  const lowest = Math.max(-Infinity, ...subs.map((sub) => sub.dy + SUB_RADIUS + 12));
  return Math.max(NODE_RADIUS + 16, lowest);
}

/** The group a tau is drawn in: its owner's, or a group of its own without an owner. */
export function groupKey(tau: Pick<PublicTau, "owner" | "address">): string {
  const owner = tau.owner.trim().replace(/\s+/g, " ").toLowerCase();
  return owner === "" ? `tau:${tau.address}` : `owner:${owner}`;
}

/** Whether a tau matches a lower-case search: its name, owner, address or a sub-tau name. */
export function matches(
  tau: Pick<PublicTau, "name" | "owner" | "address" | "subs">,
  query: string,
): boolean {
  if (query === "") return true;
  const fields = [tau.name, tau.owner, tau.address, ...subsOf(tau).map((sub) => `/${sub.name}`)];
  return fields.some((field) => field.toLowerCase().includes(query));
}

/** A deterministic number in [0, 1) from a string, for stable starting positions. */
export function hash01(text: string): number {
  let h = 2166136261;
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return (h >>> 0) / 4294967296;
}

/**
 * The `#` of the page's URL: a tau (`<address>`) or one of its sub-taus
 * (`<address>/<name>`), when the snapshot lists it; otherwise null.
 */
export function parseTarget(
  snapshot: Pick<Snapshot, "taus">,
  hash: string,
): { address: string; sub: string | null } | null {
  if (hash === "") return null;
  if (snapshot.taus.some((tau) => tau.address === hash)) return { address: hash, sub: null };
  const slash = hash.lastIndexOf("/");
  if (slash <= 0) return null;
  const address = hash.slice(0, slash);
  const name = hash.slice(slash + 1);
  const tau = snapshot.taus.find((candidate) => candidate.address === address);
  if (tau === undefined || !subsOf(tau).some((sub) => sub.name === name)) return null;
  return { address, sub: name };
}
