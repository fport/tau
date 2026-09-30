/**
 * The signed request payloads of §1 of docs/reference/tau-universe.md: validation and the
 * sanitising of the free-text fields.
 */

import { isAddress } from "./address";
import { isObject } from "./http";

export const KINDS = ["join", "report", "leave"] as const;
export type Kind = (typeof KINDS)[number];

export const MAX_OWNER_CHARS = 60;
export const MAX_ABOUT_CHARS = 200;
export const MAX_LINKS = 500;
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

export interface ReportPayload extends Common {
  kind: "report";
  links: { peer: string; messages: number }[];
}

export interface LeavePayload extends Common {
  kind: "leave";
}

export type Payload = JoinPayload | ReportPayload | LeavePayload;

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
      return { ok: true, value: { ...common, kind: "report", links } };
    }
    case "leave":
      return { ok: true, value: { ...common, kind: "leave" } };
  }
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
