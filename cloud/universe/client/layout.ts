/**
 * The universe page's data helpers, without the DOM: a tau's sub-taus, search matching and
 * the `#` of the page's URL. Pure, so the Worker's tests can check it.
 */

import type { PublicSub, PublicTau, Snapshot } from "../src/snapshot";

/** The subs of a tau from any snapshot (an older universe sent none). */
export function subsOf(tau: Pick<PublicTau, "subs">): PublicSub[] {
  return Array.isArray(tau.subs) ? tau.subs : [];
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
