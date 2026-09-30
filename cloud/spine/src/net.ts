/**
 * The public side of the spine: the card and the inbox (§2–§4 of
 * docs/reference/tau-network.md).
 *
 * The inbox checks every envelope in the order the reference prescribes and hands the ones
 * with a valid signature to the Mailbox Durable Object, which judges duplicates, the rate
 * limit and the mailbox cap, stores the envelope as it is (the spine never opens a box) and
 * wakes the hub's long poll or rings its doorbell. It answers every sender the same way,
 * whether or not the owner knows them.
 *
 * Flood hardening (the Workers Free plan has 100 000 Worker and Durable Object requests and
 * 1 000 KV writes a day): everything that costs more than CPU (the card fetch, KV, the
 * Mailbox) runs only after the cheap checks and after two Rate Limiting bindings, one keyed
 * by the client IP and one by the claimed sender. Anyone with a wildcard domain has endless
 * valid senders, so the per-sender limits alone would not stop a flood. A failing KV write
 * (the daily quota) never turns into an error: the card cache is only a cache.
 */

import { baseUrl, insecurePeersAllowed, isAddress, ownAddress } from "./address";
import { b64uDecode, b64uKey, signedMessage, verifyEd25519 } from "./crypto";
import type { SpineEnv } from "./env";
import {
  badRequest,
  error,
  isJsonRequest,
  isObject,
  json,
  nowSeconds,
  parseJson,
  readLimited,
  utf8,
} from "./http";
import { clientKey, warnOnce, withinLimit } from "./limits";
import { mailboxOf } from "./mailbox";
import { SOFTWARE } from "./version";

export const MAX_ENVELOPE_BYTES = 65_536;
export const MAX_CARD_BYTES = 8_192;
export const MAX_CLOCK_SKEW_SECONDS = 300;
export const CARD_FETCH_TIMEOUT_MS = 5_000;
export const PEER_CACHE_TTL_SECONDS = 3_600;

const CARD_KEY = "card";
const ENVELOPE_ID = /^[A-Za-z0-9_-]{16,64}$/;
const KINDS = new Set(["contact_request", "contact_accept", "message"]);

/** What the hub published with PUT /hub/card. */
export interface StoredCard {
  name: string;
  sign_key: string;
  box_key: string;
}

/** The public card (§2). */
export interface Card extends StoredCard {
  v: 1;
  address: string;
  inbox: string;
  software: string;
}

export async function readStoredCard(env: SpineEnv): Promise<StoredCard | null> {
  return env.TAU.get<StoredCard>(CARD_KEY, "json");
}

export async function writeStoredCard(env: SpineEnv, card: StoredCard): Promise<void> {
  await env.TAU.put(CARD_KEY, JSON.stringify(card));
}

export function publicCard(env: SpineEnv, address: string, stored: StoredCard): Card {
  return {
    v: 1,
    address,
    name: stored.name,
    sign_key: stored.sign_key,
    box_key: stored.box_key,
    inbox: `${baseUrl(address, insecurePeersAllowed(env))}/net/inbox`,
    software: SOFTWARE,
  };
}

/** GET /.well-known/tau.json */
export async function serveCard(env: SpineEnv, url: URL): Promise<Response> {
  const stored = await readStoredCard(env);
  if (stored === null) return error(404, "no_card");
  return json(publicCard(env, ownAddress(env, url), stored), 200, {
    "access-control-allow-origin": "*",
    "cache-control": "public, max-age=300",
  });
}

/** The payload fields of §3 after validation. */
export interface Payload {
  v: 1;
  id: string;
  kind: string;
  from: string;
  to: string;
  ts: number;
  thread: string;
  reply_to: string | null;
  hops: number;
  box: { epk: string; nonce: string; ct: string };
}

type Parsed<T> = { ok: true; value: T } | { ok: false; detail: string };

function isB64u(value: unknown): value is string {
  return typeof value === "string" && b64uDecode(value) !== null;
}

/** Checks every field of §3 for presence and type, `v == 1`, the kind and the sender. */
export function parsePayload(value: unknown): Parsed<Payload> {
  if (!isObject(value)) return { ok: false, detail: "payload is not a JSON object" };
  const p = value;
  if (!Number.isInteger(p.v)) return { ok: false, detail: "v must be an integer" };
  if (p.v !== 1) return { ok: false, detail: "unsupported version" };
  if (typeof p.id !== "string" || !ENVELOPE_ID.test(p.id)) {
    return { ok: false, detail: "id must match ^[A-Za-z0-9_-]{16,64}$" };
  }
  if (typeof p.kind !== "string" || !KINDS.has(p.kind)) {
    return { ok: false, detail: "unknown kind" };
  }
  if (!isAddress(p.from)) return { ok: false, detail: "from is not a valid address" };
  if (typeof p.to !== "string") return { ok: false, detail: "to must be a string" };
  if (!Number.isInteger(p.ts)) return { ok: false, detail: "ts must be an integer" };
  if (typeof p.thread !== "string") return { ok: false, detail: "thread must be a string" };
  if (p.reply_to !== null && typeof p.reply_to !== "string") {
    return { ok: false, detail: "reply_to must be a string or null" };
  }
  if (!Number.isInteger(p.hops) || (p.hops as number) < 0) {
    return { ok: false, detail: "hops must be a non-negative integer" };
  }
  const box = p.box;
  if (!isObject(box) || !isB64u(box.epk) || !isB64u(box.nonce) || !isB64u(box.ct)) {
    return { ok: false, detail: "box must be an object with b64u epk, nonce and ct" };
  }
  return {
    ok: true,
    value: {
      v: 1,
      id: p.id,
      kind: p.kind,
      from: p.from,
      to: p.to,
      ts: p.ts as number,
      thread: p.thread,
      reply_to: p.reply_to,
      hops: p.hops as number,
      box: { epk: box.epk, nonce: box.nonce, ct: box.ct },
    },
  };
}

/** A peer card is usable when `v == 1`, its address is the sender and its sign_key is 32 bytes. */
function peerSignKey(card: unknown, from: string): Uint8Array | null {
  if (!isObject(card) || card.v !== 1 || card.address !== from) return null;
  return b64uKey(card.sign_key);
}

/**
 * The sender's signing key from its card: KV cache first (`peer:<from>`, one hour), then
 * `GET <scheme>://<from>/.well-known/tau.json` with a 5 s timeout and an 8 KiB cap.
 */
async function senderSignKey(
  env: SpineEnv,
  from: string,
  self: string,
): Promise<Uint8Array | null> {
  if (from === self) {
    // Mail to ourselves: our own card is authoritative (and a Worker may not be able to
    // fetch its own hostname).
    const own = await readStoredCard(env);
    return own === null ? null : b64uKey(own.sign_key);
  }
  const cacheKey = `peer:${from}`;
  const cached = await cachedCard(env, cacheKey);
  const cachedKey = cached === null ? null : peerSignKey(cached, from);
  if (cachedKey !== null) return cachedKey;

  const url = `${baseUrl(from, insecurePeersAllowed(env))}/.well-known/tau.json`;
  let card: unknown;
  try {
    const response = await fetch(url, {
      headers: { accept: "application/json", "user-agent": SOFTWARE },
      redirect: "manual",
      signal: AbortSignal.timeout(CARD_FETCH_TIMEOUT_MS),
    });
    if (response.status !== 200) {
      await response.body?.cancel();
      return null;
    }
    const bytes = await readLimited(
      response.body,
      MAX_CARD_BYTES,
      response.headers.get("content-length"),
    );
    const text = bytes === null ? null : utf8(bytes);
    card = text === null ? undefined : parseJson(text);
  } catch (err) {
    console.warn(JSON.stringify({ event: "card_fetch_failed", from, error: String(err) }));
    return null;
  }
  const key = peerSignKey(card, from);
  if (key === null) return null;
  await cacheCard(env, cacheKey, card);
  return key;
}

/** A cached peer card; a failing KV read counts as a miss. */
async function cachedCard(env: SpineEnv, cacheKey: string): Promise<unknown> {
  try {
    return await env.TAU.get(cacheKey, "json");
  } catch (err) {
    warnOnce("card_cache_read_failed", { error: String(err) });
    return null;
  }
}

/**
 * Caches a peer card for an hour. A failing write is ignored: the Free plan allows 1 000 KV
 * writes a day, and a flood of new senders must not turn the quota into failed deliveries.
 */
async function cacheCard(env: SpineEnv, cacheKey: string, card: unknown): Promise<void> {
  try {
    await env.TAU.put(cacheKey, JSON.stringify(card), { expirationTtl: PEER_CACHE_TTL_SECONDS });
  } catch (err) {
    warnOnce("card_cache_write_failed", { error: String(err) });
  }
}

/** POST /net/inbox */
export async function receiveEnvelope(
  request: Request,
  env: SpineEnv,
  url: URL,
): Promise<Response> {
  // 0. Media type: only a JSON body is read at all.
  if (!isJsonRequest(request)) {
    await request.body?.cancel();
    return error(415, "unsupported_media_type");
  }

  // 1. Size.
  const body = await readLimited(
    request.body,
    MAX_ENVELOPE_BYTES,
    request.headers.get("content-length"),
  );
  if (body === null) return error(413, "too_large");

  // 2. Shape: {payload, sig}, both b64u; the payload a JSON object with every field.
  const text = utf8(body);
  const envelope = text === null ? undefined : parseJson(text);
  if (!isObject(envelope)) return badRequest("body must be a JSON object");
  if (typeof envelope.payload !== "string" || typeof envelope.sig !== "string") {
    return badRequest("payload and sig must be strings");
  }
  const payloadBytes = b64uDecode(envelope.payload);
  const sig = b64uDecode(envelope.sig);
  if (payloadBytes === null || sig === null) {
    return badRequest("payload and sig must be base64url");
  }
  const payloadText = utf8(payloadBytes);
  const parsed = parsePayload(payloadText === null ? undefined : parseJson(payloadText));
  if (!parsed.ok) return badRequest(parsed.detail);
  const payload = parsed.value;

  // 3. Recipient.
  const self = ownAddress(env, url);
  if (payload.to !== self) return error(400, "wrong_recipient");

  // 4. Freshness.
  const now = nowSeconds();
  if (Math.abs(now - payload.ts) > MAX_CLOCK_SKEW_SECONDS) return error(400, "stale");

  // 4a. Flood guards, before anything that costs a subrequest, KV or the Mailbox: the
  // client IP first (a wildcard domain makes senders free), then the claimed sender.
  const ip = clientKey(request.headers.get("cf-connecting-ip"));
  if (ip !== null && !(await withinLimit(env, "INBOX_IP_LIMIT", ip))) {
    return error(429, "rate_limited");
  }
  if (!(await withinLimit(env, "INBOX_SENDER_LIMIT", payload.from))) {
    return error(429, "rate_limited");
  }

  // 5. The sender's card.
  const signKey = await senderSignKey(env, payload.from, self);
  if (signKey === null) return error(502, "sender_card_unavailable");

  // 6. The signature, over the exact bytes decoded from `payload`.
  if (!(await verifyEd25519(signKey, sig, signedMessage(payloadBytes)))) {
    return error(403, "bad_signature");
  }

  // 7–9. Duplicate, rate limit, mailbox capacity, judged in that order by the Mailbox,
  // which then stores the envelope and wakes a waiting long poll in one step.
  const stored = JSON.stringify({ payload: envelope.payload, sig: envelope.sig });
  const delivery = await mailboxOf(env).deliver(payload.from, payload.id, now, stored);
  switch (delivery.status) {
    case "duplicate":
      return json({ status: "duplicate", id: payload.id });
    case "rate_limited":
      return error(429, "rate_limited");
    case "mailbox_full":
      return error(503, "mailbox_full");
  }

  console.log(JSON.stringify({ event: "envelope_queued", seq: delivery.seq, kind: payload.kind }));
  return json({ status: "queued", id: payload.id }, 202);
}
