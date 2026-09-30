/**
 * The shapes the pages read from the universe's APIs (ADR 0013 §5–§6, issues 160 and 163).
 *
 * The snapshot types come from src/snapshot.ts; the fields that schema v3 adds are optional
 * here, so the pages also read a universe that predates them. The pages check every field
 * they use before they use it.
 */

import type { PublicSub, PublicTau, Snapshot } from "../src/snapshot";

/** A public sub-tau in a snapshot, with the fields of schema v3 when the universe has them. */
export type SnapshotSub = PublicSub & {
  web?: boolean;
  starters?: string[];
  first_seen?: number;
  slug?: string | null;
  path?: string | null;
};

/** A tau in a snapshot, with its handle when the universe has one for it. */
export type SnapshotTau = Omit<PublicTau, "subs"> & {
  handle?: string | null;
  subs: SnapshotSub[];
};

export type SiteSnapshot = Omit<Snapshot, "taus"> & { taus: SnapshotTau[] };

/** A public sub-tau as the person and sub-tau APIs describe it. */
export interface PageSub {
  name: string;
  about: string;
  web: boolean;
  starters: string[];
  first_seen: number;
  /** Its short page `/<slug>`, when it holds one. */
  slug: string | null;
  /** Its page on this site (`/coach` or `/@alice/coach`), or null. */
  path: string | null;
  /** The same page as an absolute URL, or null. */
  url: string | null;
}

/** `GET /api/people/<handle>`: the person's tau at the top level. */
export interface PersonView {
  handle: string;
  github: string;
  building_since: number;
  counts: { subs: number; links: number; messages: number };
  address: string;
  name: string;
  owner: string;
  about: string;
  joined_at: number;
  last_seen: number;
  online: boolean;
  hosted: boolean;
  subs: PageSub[];
  /** The taus it is linked with (mutual links only). */
  links: { peer: string; messages: number; name: string; handle: string | null; online: boolean }[];
}

/** `GET /api/subs/<slug>` and `GET /api/subs/@<handle>/<name>`. */
export interface SubView extends PageSub {
  online: boolean;
  /** Run by a tau-host (answers at once) rather than by a hub (answers when it is online). */
  hosted: boolean;
  owner: { handle: string | null; name: string; address: string };
}

/** One message of a visitor thread. */
export interface ChatMessage {
  n: number;
  from: "visitor" | "sub";
  text: string;
  ts: number;
}

/** `POST /api/chat/<target>`: the thread, the visit's id and the message's number. */
export interface ChatSent {
  thread: string;
  id: string;
  n: number;
}

/** `GET /api/chat/<target>/<thread>?after=<n>&wait=<s>`. */
export interface ChatPoll {
  messages: ChatMessage[];
  /** The last message still awaits its answer. */
  pending: boolean;
  state: "open" | "resting" | "full" | "unavailable";
}

/** `POST /api/claim`: `{ok, handle, url, moved_from}`, or `{error}`. */
export interface ClaimResult {
  ok?: boolean;
  handle?: string;
  url?: string;
  /** The address the handle pointed to before, when the claim moved it. */
  moved_from?: string | null;
  error?: string;
  detail?: string;
}
