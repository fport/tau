/**
 * Base64url and byte helpers of the tau network protocol (§1 of docs/reference/tau-network.md).
 *
 * `b64u` is RFC 4648 §5 without padding. Decoders accept input with or without padding and
 * reject anything else (other alphabets, white space, a stray `=`), like tau-net's
 * `b64u_decode`. Web APIs only (atob/btoa, TextEncoder, crypto.getRandomValues), so the module
 * runs in workerd, in browsers and in Node.
 */

const B64U = /^[A-Za-z0-9_-]*={0,2}$/;

const encoder = new TextEncoder();
// fatal: invalid UTF-8 is an error; ignoreBOM: a leading BOM stays in the text (and makes
// JSON.parse fail), as Python's `bytes.decode("utf-8")` + `json.loads` treat it.
const decoder = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true });

/** `bytes` as base64url without padding. */
export function b64uEncode(bytes: Uint8Array): string {
  let binary = "";
  for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i] as number);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

/** Decodes base64url with or without padding; null when `text` is not valid base64url. */
export function b64uDecode(text: unknown): Uint8Array | null {
  if (typeof text !== "string" || !B64U.test(text)) return null;
  const bare = text.replace(/=+$/, "");
  if (bare.length % 4 === 1) return null;
  if (bare.length !== text.length && text.length % 4 !== 0) return null;
  const b64 = bare.replace(/-/g, "+").replace(/_/g, "/");
  let binary: string;
  try {
    binary = atob(b64 + "=".repeat((4 - (b64.length % 4)) % 4));
  } catch {
    return null;
  }
  const out = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) out[i] = binary.charCodeAt(i);
  return out;
}

/** A b64u string that decodes to exactly `length` bytes (a public key), or null. */
export function b64uKey(value: unknown, length = 32): Uint8Array | null {
  const bytes = b64uDecode(value);
  return bytes !== null && bytes.length === length ? bytes : null;
}

/** Whether `value` is a b64u string. */
export function isB64u(value: unknown): value is string {
  return b64uDecode(value) !== null;
}

/** `text` as UTF-8 bytes. */
export function utf8Encode(text: string): Uint8Array {
  return encoder.encode(text);
}

/** UTF-8 bytes as text; null when they are not valid UTF-8. */
export function utf8Decode(bytes: Uint8Array): string | null {
  try {
    return decoder.decode(bytes);
  } catch {
    return null;
  }
}

/** The parts one after the other. */
export function concatBytes(...parts: Uint8Array[]): Uint8Array {
  let length = 0;
  for (const part of parts) length += part.length;
  const out = new Uint8Array(length);
  let offset = 0;
  for (const part of parts) {
    out.set(part, offset);
    offset += part.length;
  }
  return out;
}

/** Byte-wise equality (not constant time: for public values only). */
export function bytesEqual(a: Uint8Array, b: Uint8Array): boolean {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return false;
  return true;
}

/** `length` bytes from the platform's cryptographic random source. */
export function randomBytes(length: number): Uint8Array {
  return crypto.getRandomValues(new Uint8Array(length));
}

/** Length in Unicode code points, the way Python's `len()` counts a `str`. */
export function charCount(text: string): number {
  let count = 0;
  for (const _ of text) count++;
  return count;
}

/**
 * Compact JSON as UTF-8 bytes: what tau-net's `json.dumps(value, separators=(",", ":"),
 * ensure_ascii=False)` writes for the same object (keys in insertion order, non-ASCII text as
 * is), so signed payloads and sealed contents are byte-identical in both halves.
 */
export function compactJson(value: unknown): Uint8Array {
  return encoder.encode(JSON.stringify(value));
}

/** Parses UTF-8 JSON bytes; undefined when they are not UTF-8 or not JSON. */
export function parseJsonBytes(bytes: Uint8Array): unknown {
  const text = utf8Decode(bytes);
  if (text === null) return undefined;
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return undefined;
  }
}

/** A plain JSON object (not null, not an array). */
export function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
