/**
 * The signed request payloads of §1 of docs/reference/tau-universe.md: validation and the
 * sanitising of the free-text fields. `claim` (ADR 0013 §6) binds a handle to a tau.
 */

import { isAddress } from "./address";
import { isObject } from "./http";

export const KINDS = ["join", "report", "leave", "claim"] as const;
export type Kind = (typeof KINDS)[number];

export const MAX_OWNER_CHARS = 60;
export const MAX_ABOUT_CHARS = 200;
export const MAX_LINKS = 500;
/** A report lists at most this many public sub-taus. */
export const MAX_SUBS = 20;
/** A sub-tau name (ADR 0012): a slug shown as `/name`. */
export const SUB_NAME = /^[a-z][a-z0-9-]{1,30}$/;
/**
 * Sub-tau names that never reach the universe (ADR 0013 §3): they would collide with the
 * paths under an address (`<address>/net/inbox`, tau-host's `/app`, …). A report that lists
 * one is still valid; the universe drops that entry.
 */
export const RESERVED_SUB_NAMES: ReadonlySet<string> = new Set([
  "net",
  "app",
  "api",
  "auth",
  "claim",
  "hub",
]);
/** A web sub-tau suggests at most this many first messages, each 1–80 characters. */
export const MAX_STARTERS = 4;
export const MAX_STARTER_CHARS = 80;
/** A claim's single-use token: base64url or hex, 8–128 characters. */
export const NONCE = /^[A-Za-z0-9_-]{8,128}$/;
/** The clock window of join, report and leave, in seconds. */
export const CLOCK_WINDOW_SECONDS = 300;
/**
 * The clock window of a claim: the owner opens the claim link and signs in with GitHub in
 * between, so it is valid for an hour. Its nonce, not its `ts`, guards against replay.
 */
export const CLAIM_WINDOW_SECONDS = 3_600;
/** Card names are 1–80 characters on the spine (`PUT /hub/card`). */
export const MAX_NAME_CHARS = 80;

interface Common {
  v: 1;
  universe: string;
  address: string;
  ts: number;
}

export interface JoinPayload extends Common {
  kind: "join";
  owner: string;
  about: string;
}

/** A public sub-tau as a report lists it. */
export interface ReportedSub {
  name: string;
  about: string;
  /** Visitors can talk to it on its page (ADR 0013 §5); absent means false. */
  web: boolean;
  /** Suggested first messages; absent means none. */
  starters: string[];
}

export interface ReportPayload extends Common {
  kind: "report";
  links: { peer: string; messages: number }[];
  /** Absent in older reports, which means none. */
  subs: ReportedSub[];
}

export interface LeavePayload extends Common {
  kind: "leave";
}

/** Binds the GitHub account signed in on the claim page to this tau (ADR 0013 §6). */
export interface ClaimPayload extends Common {
  kind: "claim";
  /** Single use: a second claim with the same nonce is refused. */
  nonce: string;
}

export type Payload = JoinPayload | ReportPayload | LeavePayload | ClaimPayload;

export type Parsed<T> = { ok: true; value: T } | { ok: false; detail: string };

/** Length in Unicode code points, the way Python's `len()` counts a `str`. */
export function charCount(text: string): number {
  let count = 0;
  for (const _ of text) count++;
  return count;
}

function isKind(value: unknown): value is Kind {
  return typeof value === "string" && (KINDS as readonly string[]).includes(value);
}

/** An optional string field of at most `max` characters (absent means empty). */
function optionalText(
  p: Record<string, unknown>,
  name: string,
  max: number,
): { ok: true; value: string } | { ok: false; detail: string } {
  const value = p[name];
  if (value === undefined) return { ok: true, value: "" };
  if (typeof value !== "string") return { ok: false, detail: `${name} must be a string` };
  if (charCount(value) > max) {
    return { ok: false, detail: `${name} must be at most ${max} characters` };
  }
  return { ok: true, value };
}

/** Checks the common fields of §1, then the fields of the kind. */
export function parsePayload(value: unknown): Parsed<Payload> {
  if (!isObject(value)) return { ok: false, detail: "payload is not a JSON object" };
  const p = value;
  if (!Number.isInteger(p.v)) return { ok: false, detail: "v must be an integer" };
  if (p.v !== 1) return { ok: false, detail: "unsupported version" };
  if (!isKind(p.kind)) return { ok: false, detail: "unknown kind" };
  if (typeof p.universe !== "string") return { ok: false, detail: "universe must be a string" };
  if (!isAddress(p.address)) return { ok: false, detail: "address is not a valid address" };
  if (!Number.isSafeInteger(p.ts)) return { ok: false, detail: "ts must be an integer" };
  const common: Common = { v: 1, universe: p.universe, address: p.address, ts: p.ts as number };

  switch (p.kind) {
    case "join": {
      const owner = optionalText(p, "owner", MAX_OWNER_CHARS);
      if (!owner.ok) return owner;
      const about = optionalText(p, "about", MAX_ABOUT_CHARS);
      if (!about.ok) return about;
      return {
        ok: true,
        value: { ...common, kind: "join", owner: owner.value, about: about.value },
      };
    }
    case "report": {
      if (!Array.isArray(p.links)) return { ok: false, detail: "links must be a list" };
      if (p.links.length > MAX_LINKS) {
        return { ok: false, detail: `links must have at most ${MAX_LINKS} items` };
      }
      const links: ReportPayload["links"] = [];
      for (const item of p.links as unknown[]) {
        if (!isObject(item)) return { ok: false, detail: "every link must be an object" };
        if (!isAddress(item.peer)) return { ok: false, detail: "link peer is not a valid address" };
        if (!Number.isSafeInteger(item.messages) || (item.messages as number) < 0) {
          return { ok: false, detail: "link messages must be a non-negative integer" };
        }
        links.push({ peer: item.peer, messages: item.messages as number });
      }
      const subs = parseSubs(p.subs);
      if (!subs.ok) return subs;
      return { ok: true, value: { ...common, kind: "report", links, subs: subs.value } };
    }
    case "leave":
      return { ok: true, value: { ...common, kind: "leave" } };
    case "claim":
      if (typeof p.nonce !== "string" || !NONCE.test(p.nonce)) {
        return { ok: false, detail: "nonce must be 8-128 base64url characters" };
      }
      return { ok: true, value: { ...common, kind: "claim", nonce: p.nonce } };
  }
}

/**
 * The optional `subs` of a report: at most 20 `{name, about, web?, starters?}` items, each
 * name a sub-tau name, each about 0–200 characters (a missing about is empty), `web` a
 * boolean (missing is false) and `starters` at most 4 strings of 1–80 characters (missing is
 * none). Absent means none.
 */
export function parseSubs(value: unknown): Parsed<ReportedSub[]> {
  if (value === undefined) return { ok: true, value: [] };
  if (!Array.isArray(value)) return { ok: false, detail: "subs must be a list" };
  if (value.length > MAX_SUBS) {
    return { ok: false, detail: `subs must have at most ${MAX_SUBS} items` };
  }
  const subs: ReportedSub[] = [];
  for (const item of value as unknown[]) {
    if (!isObject(item)) return { ok: false, detail: "every sub must be an object" };
    if (typeof item.name !== "string" || !SUB_NAME.test(item.name)) {
      return { ok: false, detail: "sub name must match ^[a-z][a-z0-9-]{1,30}$" };
    }
    const about = optionalText(item, "about", MAX_ABOUT_CHARS);
    if (!about.ok) return { ok: false, detail: `sub ${about.detail}` };
    if (item.web !== undefined && typeof item.web !== "boolean") {
      return { ok: false, detail: "sub web must be a boolean" };
    }
    const starters = parseStarters(item.starters);
    if (!starters.ok) return starters;
    subs.push({
      name: item.name,
      about: about.value,
      web: item.web === true,
      starters: starters.value,
    });
  }
  return { ok: true, value: subs };
}

function parseStarters(value: unknown): Parsed<string[]> {
  if (value === undefined) return { ok: true, value: [] };
  if (!Array.isArray(value)) return { ok: false, detail: "sub starters must be a list" };
  if (value.length > MAX_STARTERS) {
    return { ok: false, detail: `sub starters must have at most ${MAX_STARTERS} items` };
  }
  for (const starter of value as unknown[]) {
    if (typeof starter !== "string" || starter === "" || charCount(starter) > MAX_STARTER_CHARS) {
      return {
        ok: false,
        detail: `every sub starter must be a string of 1-${MAX_STARTER_CHARS} characters`,
      };
    }
  }
  return { ok: true, value: value as string[] };
}

/**
 * The sub-taus a report stores: a reserved name is dropped, a repeated name keeps its last
 * entry, every about line and starter is sanitised (a starter left empty goes), and the list
 * is ordered by name.
 */
export function normalizeSubs(subs: readonly ReportedSub[]): ReportedSub[] {
  const byName = new Map<string, ReportedSub>();
  for (const sub of subs) {
    if (RESERVED_SUB_NAMES.has(sub.name)) continue;
    byName.set(sub.name, {
      name: sub.name,
      about: sanitizeText(sub.about, MAX_ABOUT_CHARS),
      web: sub.web,
      starters: sub.starters
        .map((starter) => sanitizeText(starter, MAX_STARTER_CHARS))
        .filter((starter) => starter !== ""),
    });
  }
  return [...byName.values()].sort((x, y) => (x.name < y.name ? -1 : x.name > y.name ? 1 : 0));
}

// C0 and C1 control characters (newlines and tabs included), plus the bidirectional
// embedding, override and isolate controls, which could make a name display as something
// it is not.
const CONTROLS = /[\u0000-\u001f\u007f-\u009f‪-‮⁦-⁩]/g;

/**
 * Plain text for display: control characters become spaces, runs of white space collapse,
 * the ends are trimmed, and the result is cut to `max` characters. The page still escapes
 * whatever is left.
 */
export function sanitizeText(text: string, max: number): string {
  const clean = text.replace(CONTROLS, " ").replace(/\s+/g, " ").trim();
  if (charCount(clean) <= max) return clean;
  return Array.from(clean).slice(0, max).join("").trimEnd();
}
