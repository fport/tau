/**
 * The public snapshot (§2 of docs/reference/tau-universe.md), built from the rows the
 * Directory keeps, and the views of the person and sub-tau pages (ADR 0013 §6). Pure: no
 * storage, no clock. The link rule lives here and only here.
 *
 * The page scripts (client/) import these types, so this module stays free of Worker APIs.
 */

/** A tau is online when it reported within the last two hours (hubs report hourly). */
export const ONLINE_WINDOW_SECONDS = 2 * 3_600;

/** A public sub-tau of a tau, as its last report listed it. */
export interface PublicSub {
  name: string;
  about: string;
  /** Visitors can talk to it on its page. */
  web: boolean;
  /** Suggested first messages, at most 4. */
  starters: string[];
  /** The `ts` of the first report that listed it (since it was last absent). */
  first_seen: number;
  /** `name` when this sub-tau holds the short page `/<name>`, else null. */
  slug: string | null;
}

/** A row of the `taus` table, as far as the public sees it. */
export type TauRow = {
  address: string;
  name: string;
  owner: string;
  about: string;
  joined_at: number;
  last_seen: number;
  /** A GitHub login proven by a claim, or taken from a hosted address; absent means none. */
  handle?: string | null;
  /** From the last report; absent means none. */
  subs?: readonly PublicSub[];
};

/** One reported link: `reporter` says it exchanged `messages` envelopes with `peer`. */
export type ReportRow = {
  reporter: string;
  peer: string;
  messages: number;
};

export interface PublicTau extends Omit<TauRow, "subs" | "handle"> {
  online: boolean;
  handle: string | null;
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

/** A public sub-tau with the path and URL of its page (null when it has none). */
export interface PageSub extends PublicSub {
  path: string | null;
  url: string | null;
}

/** A linked tau on a person page. */
export interface PersonLink {
  peer: string;
  messages: number;
  name: string;
  handle: string | null;
  online: boolean;
}

/** `GET /api/people/<handle>`: the person page. */
export interface PersonView {
  handle: string;
  github: string;
  /** When their tau first joined the universe. */
  building_since: number;
  counts: { subs: number; links: number; messages: number };
  address: string;
  name: string;
  owner: string;
  about: string;
  joined_at: number;
  last_seen: number;
  online: boolean;
  /** The tau lives in tau-host on the universe's own host. */
  hosted: boolean;
  subs: PageSub[];
  links: PersonLink[];
}

/** `GET /api/subs/<slug>` and `GET /api/subs/@<handle>/<name>`: the sub-tau page. */
export interface SubView extends PageSub {
  online: boolean;
  hosted: boolean;
  owner: { handle: string | null; name: string; address: string };
}

export function isOnline(lastSeen: number, now: number): boolean {
  return lastSeen >= now - ONLINE_WINDOW_SECONDS;
}

function compare(x: string, y: string): number {
  return x < y ? -1 : x > y ? 1 : 0;
}

function publicSubs(subs: readonly PublicSub[] | undefined): PublicSub[] {
  return (subs ?? [])
    .map((sub) => ({
      name: sub.name,
      about: sub.about,
      web: sub.web,
      starters: [...sub.starters],
      first_seen: sub.first_seen,
      slug: sub.slug,
    }))
    .sort((x, y) => compare(x.name, y.name));
}

/**
 * The snapshot of `taus` and `reports`:
 *
 * - taus ordered by `joined_at` (then address), each with `online`, its handle and its
 *   public sub-taus ordered by name;
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
      handle: tau.handle ?? null,
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

/**
 * The page of a sub-tau: `/<slug>` when it holds its short name, else `/@<handle>/<name>`
 * when its tau has a handle, else none. `url` is the same on `https://<universe>`.
 */
export function subPage(
  universe: string,
  handle: string | null,
  sub: PublicSub,
): { path: string | null; url: string | null } {
  const path =
    sub.slug !== null ? `/${sub.slug}` : handle !== null ? `/@${handle}/${sub.name}` : null;
  return { path, url: path === null ? null : `https://${universe}${path}` };
}

function pageSub(universe: string, handle: string | null, sub: PublicSub): PageSub {
  return { ...sub, ...subPage(universe, handle, sub) };
}

/**
 * The person page of the tau at `address` in `snapshot` (which must hold the tau, its
 * links and the taus on their other ends), or null when the tau has no handle.
 */
export function personView(
  snapshot: Snapshot,
  address: string,
  hosted: boolean,
): PersonView | null {
  const view = tauView(snapshot, address);
  if (view === null || view.handle === null) return null;
  const handle = view.handle;
  const byAddress = new Map(snapshot.taus.map((tau) => [tau.address, tau]));
  const links = view.links.map((link): PersonLink => {
    const peer = byAddress.get(link.peer);
    return {
      peer: link.peer,
      messages: link.messages,
      name: peer?.name ?? link.peer,
      handle: peer?.handle ?? null,
      online: peer?.online ?? false,
    };
  });
  return {
    handle,
    github: `https://github.com/${handle}`,
    building_since: view.joined_at,
    counts: {
      subs: view.subs.length,
      links: links.length,
      messages: links.reduce((sum, link) => sum + link.messages, 0),
    },
    address: view.address,
    name: view.name,
    owner: view.owner,
    about: view.about,
    joined_at: view.joined_at,
    last_seen: view.last_seen,
    online: view.online,
    hosted,
    subs: view.subs.map((sub) => pageSub(snapshot.universe, handle, sub)),
    links,
  };
}

/** The page of the sub-tau `name` of `tau`, or null when the tau does not list it. */
export function subView(
  universe: string,
  tau: PublicTau,
  name: string,
  hosted: boolean,
): SubView | null {
  const sub = tau.subs.find((candidate) => candidate.name === name);
  if (sub === undefined) return null;
  return {
    ...pageSub(universe, tau.handle, sub),
    online: tau.online,
    hosted,
    owner: { handle: tau.handle, name: tau.name, address: tau.address },
  };
}
