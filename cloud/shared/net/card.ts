/**
 * The card: a tau's public JSON at `<scheme>://<address>/.well-known/tau.json` (§2 and §4 of
 * docs/reference/tau-network.md).
 *
 *     {"v": 1, "address": "tau.example.com", "name": "Alice's tau", "sign_key": "<b64u>",
 *      "box_key": "<b64u>", "inbox": "https://tau.example.com/net/inbox",
 *      "software": "tau-spine/0.1.0"}
 *
 * parseCard holds the checks a receiver makes on a fetched card (`v == 1`, `address` equal to
 * the address it was fetched for, 32-byte keys), and fetchCard fetches one within the limits
 * of §4: 5 s, at most 8 KiB, no redirects.
 */

import { cardUrl, inboxUrl } from "./address.ts";
import { b64uKey, isObject, parseJsonBytes } from "./b64u.ts";

export const MAX_CARD_BYTES = 8_192;
export const MAX_NAME_CHARS = 80;
export const CARD_FETCH_TIMEOUT_MS = 5_000;

export interface Card {
  v: 1;
  address: string;
  name: string;
  sign_key: string;
  box_key: string;
  inbox: string;
  software: string;
}

/** The card a tau at `address` serves; the inbox URL follows from the address. */
export function makeCard(fields: {
  address: string;
  name: string;
  signKey: string;
  boxKey: string;
  software: string;
  allowInsecure?: boolean;
}): Card {
  return {
    v: 1,
    address: fields.address,
    name: fields.name,
    sign_key: fields.signKey,
    box_key: fields.boxKey,
    inbox: inboxUrl(fields.address, fields.allowInsecure ?? false),
    software: fields.software,
  };
}

/**
 * The card of `address` from parsed JSON, or null when it is not usable: not an object,
 * `v != 1`, another address, or keys that are not 32 bytes of b64u. Like tau-net's
 * `parse_card`, a name that is not a string becomes empty and is cut to 80 characters, and a
 * missing inbox or software becomes empty.
 */
export function parseCard(value: unknown, address: string): Card | null {
  if (!isObject(value) || value.v !== 1 || value.address !== address) return null;
  if (b64uKey(value.sign_key) === null || b64uKey(value.box_key) === null) return null;
  const name =
    typeof value.name === "string" ? Array.from(value.name).slice(0, MAX_NAME_CHARS).join("") : "";
  return {
    v: 1,
    address,
    name,
    sign_key: value.sign_key as string,
    box_key: value.box_key as string,
    inbox: typeof value.inbox === "string" ? value.inbox : "",
    software: typeof value.software === "string" ? value.software : "",
  };
}

/** Reads at most `limit` bytes of a body; null when it is longer. */
async function readLimited(
  body: ReadableStream<Uint8Array> | null,
  limit: number,
): Promise<Uint8Array | null> {
  if (body === null) return new Uint8Array(0);
  const reader = body.getReader();
  const chunks: Uint8Array[] = [];
  let length = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    length += value.length;
    if (length > limit) {
      await reader.cancel();
      return null;
    }
    chunks.push(value);
  }
  const out = new Uint8Array(length);
  let offset = 0;
  for (const chunk of chunks) {
    out.set(chunk, offset);
    offset += chunk.length;
  }
  return out;
}

export interface FetchCardOptions {
  /** `http` for `localhost`/`127.0.0.1` (development only). */
  allowInsecure?: boolean;
  timeoutMs?: number;
  /** The User-Agent of the request, e.g. `tau-host/0.1.0`. */
  userAgent?: string;
  /** The fetch to use; the global one by default (tests pass their own). */
  fetcher?: typeof fetch;
}

/**
 * Fetches and checks the card of `address`; null on any failure (network, timeout, a status
 * other than 200, a redirect, more than 8 KiB, bad JSON, a card parseCard refuses).
 */
export async function fetchCard(
  address: string,
  options: FetchCardOptions = {},
): Promise<Card | null> {
  const fetcher = options.fetcher ?? fetch;
  const headers: Record<string, string> = { accept: "application/json" };
  if (options.userAgent) headers["user-agent"] = options.userAgent;
  try {
    const response = await fetcher(cardUrl(address, options.allowInsecure ?? false), {
      headers,
      redirect: "manual",
      signal: AbortSignal.timeout(options.timeoutMs ?? CARD_FETCH_TIMEOUT_MS),
    });
    if (response.status !== 200) {
      await response.body?.cancel();
      return null;
    }
    const declared = Number(response.headers.get("content-length") ?? "0");
    if (declared > MAX_CARD_BYTES) {
      await response.body?.cancel();
      return null;
    }
    const bytes = await readLimited(response.body, MAX_CARD_BYTES);
    const data = bytes === null ? undefined : parseJsonBytes(bytes);
    return data === undefined ? null : parseCard(data, address);
  } catch {
    return null;
  }
}
