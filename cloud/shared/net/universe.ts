/**
 * Signed universe requests (§1 of docs/reference/tau-universe.md; `claim` from ADR 0013 §6).
 * The TypeScript twin of tau-net's `tau_net.universe` request half.
 *
 * The wire body has the shape of an envelope, `{"payload": b64u, "sig": b64u}`:
 *
 * - **Signature**: Ed25519 over `"tau-universe/1\n" + payload_bytes` with the tau's signing
 *   key. The prefix differs from envelopes (`tau-net/1`), so no signature is valid in both.
 * - **Payload**: compact UTF-8 JSON, at most 64 KiB: `v` (1), `kind`, `universe` (the
 *   universe's host), `address` (either address form), `ts`, then per kind:
 *   - `join`: `owner` (0–60 characters) and `about` (0–200);
 *   - `report`: `links` (at most 500 `{peer, messages}`) and an optional `subs` (at most 20
 *     `{name, about}` plus, from ADR 0013 §5, an optional `web` flag and up to 4 `starters`);
 *   - `leave`: nothing;
 *   - `claim`: `nonce` (16–64 base64url characters). A claim is valid for an hour
 *     (CLAIM_WINDOW_SECONDS) where the other kinds get five minutes; the owner opens
 *     `https://<universe>/claim#<b64u of the wire JSON>` (claimLink) and signs in with GitHub.
 */

import { baseUrl, isAddress, isId, isSubName } from "./address.ts";
import {
  b64uDecode,
  b64uEncode,
  b64uKey,
  charCount,
  compactJson,
  concatBytes,
  isObject,
  parseJsonBytes,
  utf8Encode,
} from "./b64u.ts";
import { ed25519Verify } from "./crypto.ts";
import { newId } from "./envelope.ts";
import type { Identity } from "./identity.ts";

export const UNIVERSE_CONTEXT = utf8Encode("tau-universe/1\n");
export const UNIVERSE_KINDS = ["join", "report", "leave", "claim"] as const;
export type UniverseKind = (typeof UNIVERSE_KINDS)[number];

/** The largest `POST` body a universe accepts. */
export const MAX_REQUEST_BYTES = 65_536;
export const MAX_PAYLOAD_BYTES = 64 * 1024;
export const OWNER_LIMIT = 60;
export const ABOUT_LIMIT = 200;
export const MAX_LINKS = 500;
export const MAX_SUBS = 20;
export const MAX_STARTERS = 4;
export const STARTER_LIMIT = 80;
/** How far `ts` may be from the universe's clock for join, report and leave. */
export const REQUEST_WINDOW_SECONDS = 300;
/** How long a claim link stays valid. */
export const CLAIM_WINDOW_SECONDS = 3_600;

/** The wire body of a universe request. */
export interface SignedRequest {
  payload: string;
  sig: string;
}

export interface Link {
  peer: string;
  messages: number;
}

/** A public sub-tau as a report lists it. `web` and `starters` are sent only when set. */
export interface ReportedSub {
  name: string;
  about: string;
  web?: boolean;
  starters?: string[];
}

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
  links: Link[];
  /** Absent when the tau lists no public sub-taus. */
  subs?: ReportedSub[];
}
export interface LeavePayload extends Common {
  kind: "leave";
}
export interface ClaimPayload extends Common {
  kind: "claim";
  nonce: string;
}
export type UniversePayload = JoinPayload | ReportPayload | LeavePayload | ClaimPayload;

/** A request body or payload that breaks §1; `reason` is a short English phrase. */
export class MalformedRequest extends Error {
  override name = "MalformedRequest";
  readonly reason: string;

  constructor(reason: string) {
    super(reason);
    this.reason = reason;
  }
}

export function isUniverseKind(value: unknown): value is UniverseKind {
  return typeof value === "string" && (UNIVERSE_KINDS as readonly string[]).includes(value);
}

/** How far `ts` may be from now for a request of `kind`. */
export function requestWindowSeconds(kind: UniverseKind): number {
  return kind === "claim" ? CLAIM_WINDOW_SECONDS : REQUEST_WINDOW_SECONDS;
}

/** Whether a request's `ts` is within the window of its kind at `now` (Unix seconds). */
export function isFresh(payload: { kind: UniverseKind; ts: number }, now: number): boolean {
  return Math.abs(now - payload.ts) <= requestWindowSeconds(payload.kind);
}

// -- payloads ----------------------------------------------------------------------------------

function text(value: unknown, name: string, limit: number): string {
  if (value === undefined) return "";
  if (typeof value !== "string" || charCount(value) > limit) {
    throw new MalformedRequest(`payload.${name} must be a string of 0-${limit} characters`);
  }
  return value;
}

function checkSub(item: unknown): ReportedSub {
  if (!isObject(item) || !isSubName(item.name)) {
    throw new MalformedRequest("payload.subs has an item without a sub-tau name");
  }
  const sub: ReportedSub = { name: item.name, about: text(item.about, "subs.about", ABOUT_LIMIT) };
  if (item.web !== undefined) {
    if (typeof item.web !== "boolean")
      throw new MalformedRequest("payload.subs web must be a boolean");
    sub.web = item.web;
  }
  if (item.starters !== undefined) {
    const starters = item.starters;
    if (
      !Array.isArray(starters) ||
      starters.length > MAX_STARTERS ||
      !starters.every(
        (s) => typeof s === "string" && charCount(s) >= 1 && charCount(s) <= STARTER_LIMIT,
      )
    ) {
      throw new MalformedRequest(
        `payload.subs starters must be at most ${MAX_STARTERS} strings of 1-${STARTER_LIMIT} characters`,
      );
    }
    sub.starters = [...(starters as string[])];
  }
  return sub;
}

/**
 * The field checks of §1 on a parsed payload (tau-net's `check_payload`, plus `claim` and the
 * sub-tau fields of ADR 0013); MalformedRequest names the first bad field. A missing `owner`
 * or `about` of a join, or `about` of a sub-tau, reads as empty, as a universe treats it.
 */
export function checkRequestPayload(data: unknown): UniversePayload {
  if (!isObject(data)) throw new MalformedRequest("payload is not a JSON object");
  if (data.v !== 1) throw new MalformedRequest("payload.v is not 1");
  const kind = data.kind;
  if (!isUniverseKind(kind)) throw new MalformedRequest("payload.kind is unknown");
  if (typeof data.universe !== "string" || data.universe === "") {
    throw new MalformedRequest("payload.universe is not a host");
  }
  if (!isAddress(data.address)) throw new MalformedRequest("payload.address is not an address");
  if (!Number.isSafeInteger(data.ts)) throw new MalformedRequest("payload.ts is not an integer");
  const common: Common = {
    v: 1,
    universe: data.universe,
    address: data.address,
    ts: data.ts as number,
  };
  switch (kind) {
    case "join":
      return {
        ...common,
        kind,
        owner: text(data.owner, "owner", OWNER_LIMIT),
        about: text(data.about, "about", ABOUT_LIMIT),
      };
    case "report": {
      const links = data.links;
      if (!Array.isArray(links) || links.length > MAX_LINKS) {
        throw new MalformedRequest(`payload.links must be a list of at most ${MAX_LINKS} items`);
      }
      const checked: Link[] = links.map((link: unknown) => {
        if (!isObject(link) || !isAddress(link.peer)) {
          throw new MalformedRequest("payload.links has an item without a peer address");
        }
        if (!Number.isSafeInteger(link.messages) || (link.messages as number) < 0) {
          throw new MalformedRequest("payload.links has an item without messages >= 0");
        }
        return { peer: link.peer, messages: link.messages as number };
      });
      const report: ReportPayload = { ...common, kind, links: checked };
      if (data.subs !== undefined && data.subs !== null) {
        if (!Array.isArray(data.subs) || data.subs.length > MAX_SUBS) {
          throw new MalformedRequest(`payload.subs must be a list of at most ${MAX_SUBS} items`);
        }
        report.subs = data.subs.map(checkSub);
      }
      return report;
    }
    case "leave":
      return { ...common, kind };
    case "claim":
      if (!isId(data.nonce)) {
        throw new MalformedRequest("payload.nonce must be 16-64 base64url characters");
      }
      return { ...common, kind, nonce: data.nonce };
  }
}

export interface PayloadFields {
  universe: string;
  address: string;
  ts: number;
  owner?: string;
  about?: string;
  links?: readonly Link[];
  subs?: readonly ReportedSub[];
  /** A claim's nonce; a fresh one by default. */
  nonce?: string;
}

/**
 * The payload object of `kind` with the field order of §1 (tau-net's `make_payload`), checked
 * like a universe checks it. A report carries `subs` only when there is at least one, and a
 * sub-tau carries `web` and `starters` only when they are given.
 */
export function makeRequestPayload(kind: UniverseKind, fields: PayloadFields): UniversePayload {
  const payload: Record<string, unknown> = {
    v: 1,
    kind,
    universe: fields.universe,
    address: fields.address,
    ts: fields.ts,
  };
  if (kind === "join") {
    payload.owner = fields.owner ?? "";
    payload.about = fields.about ?? "";
  } else if (kind === "report") {
    payload.links = (fields.links ?? []).map((link) => ({
      peer: link.peer,
      messages: link.messages,
    }));
    const subs = (fields.subs ?? []).map((sub) => {
      const item: Record<string, unknown> = { name: sub.name, about: sub.about };
      if (sub.web !== undefined) item.web = sub.web;
      if (sub.starters !== undefined) item.starters = [...sub.starters];
      return item;
    });
    if (subs.length > 0) payload.subs = subs;
  } else if (kind === "claim") {
    payload.nonce = fields.nonce ?? newId();
  }
  checkRequestPayload(payload);
  return payload as unknown as UniversePayload;
}

/** Compact UTF-8 JSON: the bytes that are signed and sent. */
export function encodeRequestPayload(
  payload: UniversePayload | Record<string, unknown>,
): Uint8Array {
  return compactJson(payload);
}

/** `"tau-universe/1\n" + payload_bytes`: the exact bytes a tau signs. */
export function signedRequestMessage(payloadBytes: Uint8Array): Uint8Array {
  return concatBytes(UNIVERSE_CONTEXT, payloadBytes);
}

/** Encodes and signs `payload` (tau-net's `build_request`). */
export async function signRequest(
  identity: Identity,
  payload: UniversePayload | Record<string, unknown>,
): Promise<SignedRequest> {
  const payloadBytes = encodeRequestPayload(payload);
  if (payloadBytes.length > MAX_PAYLOAD_BYTES) {
    throw new MalformedRequest(`payload is larger than ${MAX_PAYLOAD_BYTES} bytes`);
  }
  const sig = await identity.sign(signedRequestMessage(payloadBytes));
  return { payload: b64uEncode(payloadBytes), sig: b64uEncode(sig) };
}

/**
 * Whether `signature` signs `"tau-universe/1\n" + payload_bytes` with `signKey` (raw 32 bytes
 * or b64u). Malformed keys and signatures simply do not verify.
 */
export async function verifyRequest(
  signKey: Uint8Array | string,
  payloadBytes: Uint8Array,
  signature: Uint8Array,
): Promise<boolean> {
  const key = typeof signKey === "string" ? b64uKey(signKey) : signKey;
  if (key === null) return false;
  return ed25519Verify(key, signature, signedRequestMessage(payloadBytes));
}

/** A request body that passed the shape checks; its signature is not checked yet. */
export interface ParsedRequest {
  payload: UniversePayload;
  payloadBytes: Uint8Array;
  sig: Uint8Array;
}

/**
 * The wire body and payload checks a universe makes after the size check (tau-net's
 * `parse_request`): MalformedRequest for anything it answers `bad_request` to. `body` is the
 * raw bytes, or an already parsed JSON value.
 */
export function parseRequest(body: Uint8Array | unknown): ParsedRequest {
  const data = body instanceof Uint8Array ? parseJsonBytes(body) : body;
  if (data === undefined) throw new MalformedRequest("body is not UTF-8 JSON");
  if (!isObject(data)) throw new MalformedRequest("body is not a JSON object");
  const { payload, sig } = data;
  if (typeof payload !== "string" || typeof sig !== "string") {
    throw new MalformedRequest("body needs string payload and sig");
  }
  const payloadBytes = b64uDecode(payload);
  const sigBytes = b64uDecode(sig);
  if (payloadBytes === null || sigBytes === null) {
    throw new MalformedRequest("payload or sig is not base64url");
  }
  if (payloadBytes.length > MAX_PAYLOAD_BYTES) {
    throw new MalformedRequest(`payload is larger than ${MAX_PAYLOAD_BYTES} bytes`);
  }
  const parsed = parseJsonBytes(payloadBytes);
  if (parsed === undefined) throw new MalformedRequest("payload is not UTF-8 JSON");
  return { payload: checkRequestPayload(parsed), payloadBytes, sig: sigBytes };
}

/** The wire body as compact UTF-8 JSON: the body of a `POST`. */
export function encodeRequest(request: SignedRequest): Uint8Array {
  return compactJson({ payload: request.payload, sig: request.sig });
}

// -- claim links -------------------------------------------------------------------------------

/** The fragment of a claim link: b64u of the wire JSON. */
export function claimFragment(request: SignedRequest): string {
  return b64uEncode(encodeRequest(request));
}

/**
 * `https://<universe>/claim#<fragment>`: the link `tau net universe claim` prints (`http` only
 * for a development universe on `localhost`/`127.0.0.1` when insecure peers are allowed).
 */
export function claimLink(universe: string, request: SignedRequest, allowInsecure = false): string {
  return `${baseUrl(universe, allowInsecure)}/claim#${claimFragment(request)}`;
}

/**
 * The signed request of a claim link's fragment (with or without the leading `#`), or null
 * when it is not b64u of a wire body. The payload is not checked here: parseRequest does that.
 */
export function parseClaimFragment(fragment: string): SignedRequest | null {
  const bytes = b64uDecode(fragment.startsWith("#") ? fragment.slice(1) : fragment);
  const data = bytes === null ? undefined : parseJsonBytes(bytes);
  if (!isObject(data) || typeof data.payload !== "string" || typeof data.sig !== "string") {
    return null;
  }
  return { payload: data.payload, sig: data.sig };
}
