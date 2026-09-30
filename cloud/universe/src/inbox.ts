/**
 * POST /net/inbox: the universe's inbox (ADR 0013 §5; §5 of docs/reference/tau-universe.md).
 *
 * It takes one thing only: a hub's answer to a `visit` the universe sent, a `message` whose
 * `reply_to` is that visit's id, whose `thread` is the visitor's thread, and whose `from` is
 * the address the visit went to. The checks follow the spine's inbox (§4 of
 * docs/reference/tau-network.md) in its order, with the same status codes; the universe's
 * own rule comes before the card fetch, so an envelope it never asked for costs no
 * subrequest:
 *
 *   0. an identity                           503 not_configured
 *   1. Content-Type: application/json        415 unsupported_media_type
 *   2. body ≤ 65 536 bytes                   413 too_large
 *   3. the shape of an envelope              400 bad_request
 *   4. `to` is the universe's host           400 wrong_recipient
 *   5. `ts` within 300 s                     400 stale
 *   6. per client IP, per sender             429 rate_limited
 *   7. a `message` answering a pending or
 *      answered visit sent to `from`         400 bad_request
 *   8. the sender's card                     502 sender_card_unavailable
 *   9. the signature                         403 bad_signature
 *  10. the box opens with the universe's
 *      identity; `sub` names the visited
 *      sub-tau                               400 bad_request
 *  11. not the answer already taken          200 {"status": "duplicate", "id"}
 *
 * Then the answer joins the visitor's thread: `202 {"status": "delivered", "id"}`.
 */

import {
  BadSignature,
  EnvelopeError,
  fetchCard,
  MAX_ENVELOPE_BYTES,
  openEnvelope,
  parseJsonBytes,
  parsePayload,
  parseWireEnvelope,
  b64uDecode,
  type MessageContent,
  type Payload,
  type WireEnvelope,
} from "../../shared/net/index.ts";
import { insecurePeersAllowed, universeHost } from "./address";
import { relayOf, type UniverseEnv } from "./env";
import {
  badRequest,
  error,
  json,
  methodNotAllowed,
  nowSeconds,
  parseJson,
  readLimited,
  utf8,
} from "./http";
import { universeIdentity } from "./identity";
import { clientKey, withinLimit } from "./limits";
import { SOFTWARE } from "./version";

/** How far `ts` may be from the universe's clock (the spine's window). */
export const MAX_CLOCK_SKEW_SECONDS = 300;

function isJsonRequest(request: Request): boolean {
  const type = request.headers.get("content-type") ?? "";
  return type.split(";", 1)[0]!.trim().toLowerCase() === "application/json";
}

/** The wire envelope and its validated header, or the 400 answer. */
function parseEnvelope(
  text: string | null,
): { ok: true; wire: WireEnvelope; payload: Payload } | { ok: false; response: Response } {
  const value = text === null ? undefined : parseJson(text);
  try {
    const wire = parseWireEnvelope(value);
    const bytes = b64uDecode(wire.payload);
    const data = bytes === null ? undefined : parseJsonBytes(bytes);
    return { ok: true, wire, payload: parsePayload(data) };
  } catch (err) {
    const detail = err instanceof EnvelopeError ? err.reason : "body is not an envelope";
    return { ok: false, response: badRequest(detail) };
  }
}

export async function receiveInbox(
  request: Request,
  env: UniverseEnv,
  url: URL,
): Promise<Response> {
  if (request.method !== "POST") return methodNotAllowed(["POST"]);

  // 0. Without an identity the universe sends no visits, so it takes no answers.
  const identity = await universeIdentity(env);
  if (identity === null) {
    await request.body?.cancel();
    return error(503, "not_configured");
  }

  // 1. Media type: only a JSON body is read at all.
  if (!isJsonRequest(request)) {
    await request.body?.cancel();
    return error(415, "unsupported_media_type");
  }

  // 2. Size.
  const body = await readLimited(
    request.body,
    MAX_ENVELOPE_BYTES,
    request.headers.get("content-length"),
  );
  if (body === null) return error(413, "too_large");

  // 3. Shape: {payload, sig}, both b64u; the payload a JSON object with every field.
  const parsed = parseEnvelope(utf8(body));
  if (!parsed.ok) return parsed.response;
  const { wire, payload } = parsed;

  // 4. Recipient.
  const self = universeHost(env, url);
  if (payload.to !== self) return error(400, "wrong_recipient");

  // 5. Freshness.
  const now = nowSeconds();
  if (Math.abs(now - payload.ts) > MAX_CLOCK_SKEW_SECONDS) return error(400, "stale");

  // 6. Flood guards: the client IP, then the claimed sender.
  const ip = clientKey(request.headers.get("cf-connecting-ip"));
  if (ip !== null && !(await withinLimit(env, "INBOX_IP_LIMIT", ip))) {
    return error(429, "rate_limited");
  }
  if (!(await withinLimit(env, "INBOX_SENDER_LIMIT", payload.from))) {
    return error(429, "rate_limited");
  }

  // 7. Only answers to the universe's own visits.
  if (payload.kind !== "message" || payload.reply_to === null) {
    return badRequest("the universe takes only answers to its visits");
  }
  const relay = relayOf(env, payload.thread);
  const visit = payload.reply_to;
  const expected = await relay.expect({ visit, from: payload.from, now });
  if (!expected.ok) {
    return badRequest(
      expected.error === "wrong_sender"
        ? "the visit went to another address"
        : "no visit of this universe has this reply_to",
    );
  }

  // 8. The sender's card.
  const card = await fetchCard(payload.from, {
    allowInsecure: insecurePeersAllowed(env),
    userAgent: SOFTWARE,
  });
  if (card === null) return error(502, "sender_card_unavailable");

  // 9–10. The signature over the exact payload bytes, then the box.
  let content: MessageContent;
  try {
    const opened = await openEnvelope(wire, card.sign_key, identity);
    content = opened.content as MessageContent;
  } catch (err) {
    if (err instanceof BadSignature) return error(403, "bad_signature");
    const detail = err instanceof EnvelopeError ? err.reason : "box does not open";
    return badRequest(detail);
  }
  if (content.sub !== expected.sub) {
    return badRequest("sub does not name the visited sub-tau");
  }

  // 11. Into the thread, once.
  const outcome = await relay.reply({
    visit,
    from: payload.from,
    id: payload.id,
    text: content.text,
    now,
  });
  switch (outcome) {
    case "delivered":
      console.log(JSON.stringify({ event: "visit_answered", from: payload.from }));
      return json({ status: "delivered", id: payload.id }, 202);
    case "duplicate":
      return json({ status: "duplicate", id: payload.id });
    case "answered":
      return badRequest("the visit was already answered");
    case "wrong_sender":
      return badRequest("the visit went to another address");
    case "unknown":
      return badRequest("no visit of this universe has this reply_to");
  }
}
