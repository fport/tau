/**
 * The public snapshot (§2 of docs/reference/tau-universe.md), built from the rows the
 * Directory keeps. Pure: no storage, no clock. The link rule lives here and only here.
 */

/** A tau is online when it reported within the last two hours (hubs report hourly). */
export const ONLINE_WINDOW_SECONDS = 2 * 3_600;

/** A public sub-tau of a tau, as its last report listed it. */
export interface PublicSub {
  name: string;
  about: string;
}

/** A row of the `taus` table, as far as the public sees it. */
export type TauRow = {
  address: string;
  name: string;
  owner: string;
  about: string;
  joined_at: number;
  last_seen: number;
  /** From the last report; absent means none. */
  subs?: readonly PublicSub[];
};

/** One reported link: `reporter` says it exchanged `messages` envelopes with `peer`. */
export type ReportRow = {
  reporter: string;
  peer: string;
  messages: number;
};

export interface PublicTau extends Omit<TauRow, "subs"> {
  online: boolean;
  /** Ordered by name; `[]` when the tau reported none. */
  subs: PublicSub[];
}

export interface PublicLink {
  a: string;
  b: string;
  messages: number;
}

export interface Snapshot {
  universe: string;
  generated_at: number;
  stats: { taus: number; online: number; messages: number };
  taus: PublicTau[];
  links: PublicLink[];
}

/** One tau with its visible links (`GET /api/taus/<address>`). */
export interface TauView extends PublicTau {
  links: { peer: string; messages: number }[];
}

export function isOnline(lastSeen: number, now: number): boolean {
  return lastSeen >= now - ONLINE_WINDOW_SECONDS;
}

function compare(x: string, y: string): number {
  return x < y ? -1 : x > y ? 1 : 0;
}

function publicSubs(subs: readonly PublicSub[] | undefined): PublicSub[] {
  return (subs ?? [])
    .map((sub) => ({ name: sub.name, about: sub.about }))
    .sort((x, y) => compare(x.name, y.name));
}

/**
 * The snapshot of `taus` and `reports`:
 *
 * - taus ordered by `joined_at` (then address), each with `online` and its public
 *   sub-taus ordered by name;
 * - a link between `a < b` only when `a` reports `b`, `b` reports `a` and both are
 *   joined; its count is the smaller of the two claims;
 * - `stats.messages` is the sum over the visible links.
 */
export function buildSnapshot(
  universe: string,
  now: number,
  taus: readonly TauRow[],
  reports: readonly ReportRow[],
): Snapshot {
  const joined = new Set(taus.map((tau) => tau.address));
  const claims = new Map<string, number>();
  for (const report of reports) claims.set(`${report.reporter}\n${report.peer}`, report.messages);

  const links: PublicLink[] = [];
  for (const report of reports) {
    const { reporter: a, peer: b } = report;
    if (!(a < b) || !joined.has(a) || !joined.has(b)) continue;
    const back = claims.get(`${b}\n${a}`);
    if (back === undefined) continue;
    links.push({ a, b, messages: Math.min(report.messages, back) });
  }
  links.sort((x, y) => compare(x.a, y.a) || compare(x.b, y.b));

  const publicTaus = [...taus]
    .sort((x, y) => x.joined_at - y.joined_at || compare(x.address, y.address))
    .map((tau): PublicTau => ({
      address: tau.address,
      name: tau.name,
      owner: tau.owner,
      about: tau.about,
      joined_at: tau.joined_at,
      last_seen: tau.last_seen,
      online: isOnline(tau.last_seen, now),
      subs: publicSubs(tau.subs),
    }));

  return {
    universe,
    generated_at: now,
    stats: {
      taus: publicTaus.length,
      online: publicTaus.filter((tau) => tau.online).length,
      messages: links.reduce((sum, link) => sum + link.messages, 0),
    },
    taus: publicTaus,
    links,
  };
}

/** One tau of a snapshot with its visible links (by peer), or null when it is not listed. */
export function tauView(snapshot: Snapshot, address: string): TauView | null {
  const tau = snapshot.taus.find((candidate) => candidate.address === address);
  if (tau === undefined) return null;
  const links = snapshot.links
    .filter((link) => link.a === address || link.b === address)
    .map((link) => ({ peer: link.a === address ? link.b : link.a, messages: link.messages }))
    .sort((x, y) => compare(x.peer, y.peer));
  return { ...tau, links };
}
