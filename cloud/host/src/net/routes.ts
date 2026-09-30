/**
 * A hosted tau's public side on the tau network (ADR 0013 §3, §4):
 *
 *   GET  /@<handle>/.well-known/tau.json   the card: {v, address, name, sign_key, box_key,
 *                                          inbox, software}; CORS `*`, cached 300 s
 *   POST /@<handle>/net/inbox              a signed envelope from another tau
 *
 * The inbox keeps the spine's checks, in the spine's order and with its error codes
 * (docs/reference/tau-network.md §4):
 *
 *   415 unsupported_media_type   not `Content-Type: application/json` (the body is not read)
 *   413 too_large                more than 65 536 bytes
 *   400 bad_request              not an envelope of protocol v1 (`visit` is a known kind)
 *   400 wrong_recipient          `to` is not `<net host>/@<handle>`
 *   400 stale                    `ts` more than 300 s from the host's clock
 *   429 rate_limited             60 envelopes a minute per client IP, 30 per sender and tau
 *                                (Rate Limiting bindings, skipped without them)
 *   404 not_found                no tau with this handle (after the cheap checks)
 *   502 sender_card_unavailable  ┐
 *   403 bad_signature            │ in the tau's Durable Object (src/net/node.ts): the card
 *   200 {"status": "duplicate"}  │ cached an hour, the signature over the exact payload
 *   429 rate_limited             │ bytes, `(from, id)` seen before, 60 an hour per sender,
 *   503 mailbox_full             ┘ 1 000 envelopes waiting
 *
 * and answers `202 {"status": "accepted", "id"}`: the envelope is handled right after, in
 * the tau's object. Senders count any 202 as delivered, as they do a spine's `queued`.
 */

import {
  b64uDecode,
  EnvelopeError,
  MAX_ENVELOPE_BYTES,
  parseJsonBytes,
  parsePayload,
  parseWireEnvelope,
  type Payload,
} from "../../../shared/net/index.ts";
import { HANDLE_RE } from "../accounts";
import { accountsOf, type HostEnv, tauOf } from "../env";
import { badRequest, error, json, methodNotAllowed, notFound, nowSeconds, readLimited } from "../http";
import { CLOCK_SKEW_SECONDS, hostedAddress, netHost } from "./config";
import { clientKey, withinLimit } from "./limits";

const CARD_HEADERS = { "access-control-allow-origin": "*", "cache-control": "public, max-age=300" };

/** GET /@<handle>/.well-known/tau.json */
export async function serveCard(env: HostEnv, url: URL, handle: string): Promise<Response> {
  if (!HANDLE_RE.test(handle)) return notFound();
  if (netHost(env, url.host) === null) return error(503, "not_configured");
  if ((await accountsOf(env).account(handle)) === null) return notFound();
  const card = await tauOf(env, handle).card(url.host);
  if (card === null) return notFound();
  return json(card, 200, CARD_HEADERS);
}

function isJsonRequest(request: Request): boolean {
  const type = (request.headers.get("content-type") ?? "").split(";")[0]?.trim().toLowerCase();
  return type === "application/json";
}

/** POST /@<handle>/net/inbox */
export async function receiveEnvelope(request: Request, env: HostEnv, url: URL, handle: string): Promise<Response> {
  if (request.method !== "POST") return methodNotAllowed(["POST"]);
  if (!HANDLE_RE.test(handle)) {
    await request.body?.cancel();
    return notFound();
  }
  const host = netHost(env, url.host);
  if (host === null) {
    await request.body?.cancel();
    return error(503, "not_configured");
  }

  // 0. Media type: only a JSON body is read at all.
  if (!isJsonRequest(request)) {
    await request.body?.cancel();
    return error(415, "unsupported_media_type");
  }

  // 1. Size.
  const body = await readLimited(request.body, MAX_ENVELOPE_BYTES, request.headers.get("content-length"));
  if (body === null) return error(413, "too_large");

  // 2. Shape: {payload, sig}, both b64u; the payload a JSON object with every field of §3.
  let payload: Payload;
  let wire: { payload: string; sig: string };
  try {
    wire = parseWireEnvelope(parseJsonBytes(body));
    const bytes = b64uDecode(wire.payload);
    payload = parsePayload(bytes === null ? undefined : parseJsonBytes(bytes));
  } catch (err) {
    if (err instanceof EnvelopeError) return badRequest(err.reason);
    throw err;
  }

  // 3. Recipient: this tau's own address.
  if (payload.to !== hostedAddress(host, handle)) return error(400, "wrong_recipient");

  // 4. Freshness.
  if (Math.abs(nowSeconds() - payload.ts) > CLOCK_SKEW_SECONDS) return error(400, "stale");

  // 4a. Flood guards before anything that costs a Durable Object call or a subrequest.
  const ip = clientKey(request.headers.get("cf-connecting-ip"));
  if (ip !== null && !(await withinLimit(env, "INBOX_IP_LIMIT", ip))) return error(429, "rate_limited");
  if (!(await withinLimit(env, "INBOX_SENDER_LIMIT", `${payload.from} ${handle}`))) return error(429, "rate_limited");

  // Only handles that exist reach a Tau object: a probe never creates one.
  if ((await accountsOf(env).account(handle)) === null) return notFound();

  // 5–9 in the tau's object.
  const answer = await tauOf(env, handle).inbox({ payload: wire.payload, sig: wire.sig }, url.host);
  return json(answer.body, answer.status);
}
