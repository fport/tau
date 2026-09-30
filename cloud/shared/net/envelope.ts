/**
 * Envelopes: signed by the sender, sealed to the recipient (§3 of
 * docs/reference/tau-network.md). The TypeScript twin of tau-net's `tau_net.envelope`.
 *
 * On the wire an envelope is `{"payload": b64u(payload bytes), "sig": b64u(signature)}`. The
 * payload bytes are compact UTF-8 JSON with the header fields (`v`, `id`, `kind`, `from`,
 * `to`, `ts`, `thread`, `reply_to`, `hops`) and the sealed `box` (seal.ts).
 *
 * - **Signature**: Ed25519 over `"tau-net/1\n" + payload_bytes`. openVerified checks it
 *   against the exact bytes decoded from `payload` and parses JSON only after that check;
 *   peekSender reads the unverified `from` only to find the key to verify with.
 * - **Kinds**: `contact_request`, `contact_accept`, `message` and `visit` (ADR 0013 §5: a
 *   universe relays an anonymous visitor's text to a hub-run web sub-tau).
 * - **Addresses**: both forms of address.ts (`host[:port]` and `host[:port]/@handle`).
 *
 * Every failure throws an EnvelopeError (errors.ts) whose `reason` is a fixed English phrase.
 */

import { isId, isAddress, isSubName } from "./address.ts";
import {
  b64uDecode,
  b64uEncode,
  b64uKey,
  charCount,
  compactJson,
  concatBytes,
  isB64u,
  isObject,
  parseJsonBytes,
  randomBytes,
  utf8Encode,
} from "./b64u.ts";
import { ed25519Verify } from "./crypto.ts";
import { BadSignature, BoxError, EnvelopeTooLarge, MalformedEnvelope } from "./errors.ts";
import type { Identity } from "./identity.ts";
import { aadFor, openBox, seal, type Box, type SealOptions } from "./seal.ts";

export const SIGNATURE_CONTEXT = utf8Encode("tau-net/1\n");
export const KINDS = ["contact_request", "contact_accept", "message", "visit"] as const;
export type Kind = (typeof KINDS)[number];
/** The largest `POST /net/inbox` body an inbox accepts. */
export const MAX_ENVELOPE_BYTES = 65_536;
/** The longest `message` (and `visit`) text, in characters (code points). */
export const MAX_MESSAGE_CHARS = 8_000;

/** The wire form: base64url payload bytes and signature. */
export interface WireEnvelope {
  payload: string;
  sig: string;
}

/** The signed header of an envelope, with the field names of the wire. */
export interface Payload {
  v: 1;
  id: string;
  kind: Kind;
  from: string;
  to: string;
  ts: number;
  thread: string;
  reply_to: string | null;
  hops: number;
  box: Box;
}

export interface ContactRequestContent {
  name: string;
  text: string;
}
export interface ContactAcceptContent {
  name: string;
}
/** `sub` is present only when the message names a sub-tau (ADR 0012). */
export interface MessageContent {
  text: string;
  sub?: string;
}
/** A visitor's text for the web sub-tau `sub` (ADR 0013 §5). */
export interface VisitContent {
  text: string;
  sub: string;
}
export type Content = ContactRequestContent | ContactAcceptContent | MessageContent | VisitContent;

export function isKind(value: unknown): value is Kind {
  return typeof value === "string" && (KINDS as readonly string[]).includes(value);
}

/** A fresh envelope id: 24 base64url characters (18 random bytes, like `token_urlsafe(18)`). */
export function newId(): string {
  return b64uEncode(randomBytes(18));
}

/** `"tau-net/1\n" + payload_bytes`: the exact bytes a sender signs. */
export function signedMessage(payloadBytes: Uint8Array): Uint8Array {
  return concatBytes(SIGNATURE_CONTEXT, payloadBytes);
}

// -- parsing -----------------------------------------------------------------------------------

/** The wire envelope of `value`: an object with string b64u `payload` and `sig`. */
export function parseWireEnvelope(value: unknown): WireEnvelope {
  if (!isObject(value)) throw new MalformedEnvelope("envelope is not a JSON object");
  const { payload, sig } = value;
  if (typeof payload !== "string" || typeof sig !== "string") {
    throw new MalformedEnvelope("envelope needs string payload and sig");
  }
  if (!isB64u(payload)) throw new MalformedEnvelope("envelope.payload is not base64url");
  if (!isB64u(sig)) throw new MalformedEnvelope("envelope.sig is not base64url");
  return { payload, sig };
}

const FIELDS = ["v", "id", "kind", "from", "to", "ts", "thread", "reply_to", "hops", "box"];

function parseBox(value: unknown): Box {
  if (!isObject(value)) throw new MalformedEnvelope("box is not an object");
  for (const name of ["epk", "nonce", "ct"]) {
    const field = value[name];
    if (typeof field !== "string") throw new MalformedEnvelope(`box.${name} is not a string`);
    if (!isB64u(field)) throw new MalformedEnvelope(`box.${name} is not base64url`);
  }
  return { epk: value.epk as string, nonce: value.nonce as string, ct: value.ct as string };
}

/** Validates every field of §3 (like tau-net's `Payload.from_json`); MalformedEnvelope names the first bad one. */
export function parsePayload(value: unknown): Payload {
  if (!isObject(value)) throw new MalformedEnvelope("payload is not a JSON object");
  const missing = FIELDS.filter((name) => !(name in value));
  if (missing.length > 0) throw new MalformedEnvelope(`payload misses ${missing.join(", ")}`);
  if (value.v !== 1) throw new MalformedEnvelope("payload.v is not 1");
  if (!isId(value.id)) throw new MalformedEnvelope("payload.id is not a valid id");
  if (!isKind(value.kind)) throw new MalformedEnvelope("payload.kind is unknown");
  if (!isAddress(value.from)) throw new MalformedEnvelope("payload.from is not an address");
  if (!isAddress(value.to)) throw new MalformedEnvelope("payload.to is not an address");
  if (!Number.isSafeInteger(value.ts)) throw new MalformedEnvelope("payload.ts is not an integer");
  if (!isId(value.thread)) throw new MalformedEnvelope("payload.thread is not a valid id");
  const replyTo = value.reply_to;
  if (replyTo !== null && !isId(replyTo)) {
    throw new MalformedEnvelope("payload.reply_to is neither null nor a valid id");
  }
  const hops = value.hops;
  if (!Number.isSafeInteger(hops) || (hops as number) < 0) {
    throw new MalformedEnvelope("payload.hops is not a non-negative integer");
  }
  return {
    v: 1,
    id: value.id,
    kind: value.kind,
    from: value.from,
    to: value.to,
    ts: value.ts as number,
    thread: value.thread,
    reply_to: replyTo,
    hops: hops as number,
    box: parseBox(value.box),
  };
}

/** The payload object with the field order of the protocol, as compact UTF-8 JSON. */
export function encodePayload(payload: Payload): Uint8Array {
  return compactJson({
    v: payload.v,
    id: payload.id,
    kind: payload.kind,
    from: payload.from,
    to: payload.to,
    ts: payload.ts,
    thread: payload.thread,
    reply_to: payload.reply_to,
    hops: payload.hops,
    box: { epk: payload.box.epk, nonce: payload.box.nonce, ct: payload.box.ct },
  });
}

/** The wire envelope as compact UTF-8 JSON: the body of `POST /net/inbox`. */
export function encodeEnvelope(envelope: WireEnvelope): Uint8Array {
  return compactJson({ payload: envelope.payload, sig: envelope.sig });
}

/**
 * The sealed plaintext of `kind` with the right types (like tau-net's `parse_content`);
 * BoxError otherwise. Keys the protocol does not name are ignored, which is how v1 grows.
 *
 * - `contact_request`: `{name, text}`; `contact_accept`: `{name}`;
 * - `message`: `{text}` of at most MAX_MESSAGE_CHARS, plus `sub` when it names a sub-tau
 *   (absent or null means none);
 * - `visit`: `{text, sub}`, text of at most MAX_MESSAGE_CHARS and a sub-tau name.
 */
export function parseContent(kind: string, content: Record<string, unknown>): Content {
  const text = (name: string): string => {
    const value = content[name];
    if (typeof value !== "string") throw new BoxError(`${kind} content needs a string '${name}'`);
    return value;
  };
  const shortText = (): string => {
    const value = text("text");
    if (charCount(value) > MAX_MESSAGE_CHARS) {
      throw new BoxError(`${kind} text is longer than ${MAX_MESSAGE_CHARS} characters`);
    }
    return value;
  };
  switch (kind) {
    case "contact_request": {
      const name = text("name");
      return { name, text: text("text") };
    }
    case "contact_accept":
      return { name: text("name") };
    case "message": {
      const parsed: MessageContent = { text: shortText() };
      const sub = content.sub;
      if (sub !== undefined && sub !== null) {
        if (!isSubName(sub)) throw new BoxError("message sub is not a sub-tau name");
        parsed.sub = sub;
      }
      return parsed;
    }
    case "visit": {
      const parsed = shortText();
      if (!isSubName(content.sub)) throw new BoxError("visit sub is not a sub-tau name");
      return { text: parsed, sub: content.sub };
    }
    default:
      throw new BoxError(`unknown kind ${JSON.stringify(kind)}`);
  }
}

// -- signing -----------------------------------------------------------------------------------

/** The signature of an envelope: over `"tau-net/1\n" + payload_bytes`. */
export function signPayload(identity: Identity, payloadBytes: Uint8Array): Promise<Uint8Array> {
  return identity.sign(signedMessage(payloadBytes));
}

/**
 * Whether `signature` is the Ed25519 signature of `"tau-net/1\n" + payload_bytes` by
 * `signKey` (raw 32 bytes or b64u). Malformed keys and signatures simply do not verify.
 */
export async function verifySignature(
  signKey: Uint8Array | string,
  payloadBytes: Uint8Array,
  signature: Uint8Array,
): Promise<boolean> {
  const key = typeof signKey === "string" ? b64uKey(signKey) : signKey;
  if (key === null) return false;
  return ed25519Verify(key, signature, signedMessage(payloadBytes));
}

/**
 * The claimed `from` of an unverified envelope, only to pick the key to verify with. Nothing
 * else from an unverified payload is used; openVerified parses it again from verified bytes.
 */
export function peekSender(envelope: WireEnvelope): string {
  const bytes = b64uDecode(envelope.payload);
  const data = bytes === null ? undefined : parseJsonBytes(bytes);
  if (data === undefined) throw new MalformedEnvelope("payload is not UTF-8 JSON");
  const sender = isObject(data) ? data.from : undefined;
  if (!isAddress(sender)) throw new MalformedEnvelope("payload.from is not an address");
  return sender;
}

/** Verifies the signature over the exact payload bytes, then parses and validates them. */
export async function openVerified(
  envelope: WireEnvelope,
  signKey: Uint8Array | string,
): Promise<Payload> {
  const payloadBytes = b64uDecode(envelope.payload);
  const sig = b64uDecode(envelope.sig);
  if (payloadBytes === null || sig === null) {
    throw new MalformedEnvelope("envelope is not base64url");
  }
  if (!(await verifySignature(signKey, payloadBytes, sig))) throw new BadSignature("bad signature");
  const data = parseJsonBytes(payloadBytes);
  if (data === undefined) throw new MalformedEnvelope("payload is not UTF-8 JSON");
  return parsePayload(data);
}

/** A verified envelope with its opened, validated content. */
export interface OpenedEnvelope {
  payload: Payload;
  /** The content with the types of its kind (parseContent). */
  content: Content;
  /** The whole sealed object, unknown keys included. */
  raw: Record<string, unknown>;
}

/**
 * Verifies `envelope` with the sender's `signKey`, then opens its box with `identity` and
 * checks the content of its kind. The caller still checks `payload.to` against its own
 * address, the clock window and duplicates.
 */
export async function openEnvelope(
  envelope: WireEnvelope,
  signKey: Uint8Array | string,
  identity: Identity,
): Promise<OpenedEnvelope> {
  const payload = await openVerified(envelope, signKey);
  const aad = aadFor(payload.id, payload.kind, payload.from, payload.to);
  const raw = await openBox(payload.box, identity, aad);
  return { payload, content: parseContent(payload.kind, raw), raw };
}

// -- building ----------------------------------------------------------------------------------

export interface BuildOptions {
  /** The sender's address (this tau's). */
  from: string;
  /** The recipient's address. */
  to: string;
  /** The recipient's box key from its card (raw 32 bytes or b64u). */
  recipientBoxKey: Uint8Array | string;
  kind: Kind;
  /** The plaintext; checked with parseContent before it is sealed. */
  content: Record<string, unknown>;
  /** The envelope id; a fresh one by default. */
  id?: string;
  /** The conversation; a new one (the envelope's own id) by default. */
  thread?: string | null;
  replyTo?: string | null;
  hops?: number;
  /** Unix seconds; now by default. */
  ts?: number;
  /** Fixed randomness for test vectors only. */
  seal?: SealOptions;
}

/** A built envelope: the wire form, its header and the exact signed payload bytes. */
export interface BuiltEnvelope {
  envelope: WireEnvelope;
  payload: Payload;
  payloadBytes: Uint8Array;
}

/**
 * Seals `content`, signs the payload and returns the wire envelope with its header (like
 * tau-net's `build_envelope`). The header gets the recipient's own validation before
 * anything is sent; EnvelopeTooLarge when the result would not fit an inbox.
 */
export async function buildEnvelope(
  identity: Identity,
  options: BuildOptions,
): Promise<BuiltEnvelope> {
  const { from, to, kind, content } = options;
  if (!isKind(kind)) throw new MalformedEnvelope(`unknown kind ${JSON.stringify(kind)}`);
  parseContent(kind, content); // the same checks the recipient makes
  const id = options.id ?? newId();
  const box = await seal(
    content,
    options.recipientBoxKey,
    aadFor(id, kind, from, to),
    options.seal,
  );
  const payload = parsePayload({
    v: 1,
    id,
    kind,
    from,
    to,
    ts: options.ts ?? Math.floor(Date.now() / 1000),
    thread: options.thread ?? id,
    reply_to: options.replyTo ?? null,
    hops: options.hops ?? 0,
    box,
  });
  const payloadBytes = encodePayload(payload);
  const sig = await signPayload(identity, payloadBytes);
  const envelope = { payload: b64uEncode(payloadBytes), sig: b64uEncode(sig) };
  if (encodeEnvelope(envelope).length > MAX_ENVELOPE_BYTES) {
    throw new EnvelopeTooLarge(`envelope is larger than ${MAX_ENVELOPE_BYTES} bytes`);
  }
  return { envelope, payload, payloadBytes };
}
