/**
 * The universe API (§2 of docs/reference/tau-universe.md):
 *
 *   GET  /api/universe          the public snapshot
 *   GET  /api/taus/<address>    one tau with its visible links
 *   POST /api/join|report|leave signed requests from taus
 *
 * A POST is checked in the reference's order. The Worker does everything that needs no
 * stored state (size, shape, universe, clock window, card, signature); the Directory judges
 * the rest (replay, joined, rate limit) and applies the effect atomically.
 */

import { isAddress, universeHost } from "./address";
import { fetchCard } from "./card";
import { b64uDecode, signedMessage, verifyEd25519 } from "./crypto";
import type { Outcome, Refusal } from "./directory";
import { directoryOf, type UniverseEnv } from "./env";
import {
  badRequest,
  error,
  isObject,
  json,
  methodNotAllowed,
  notFound,
  nowSeconds,
  parseJson,
  readLimited,
  utf8,
} from "./http";
import {
  type Kind,
  KINDS,
  MAX_ABOUT_CHARS,
  MAX_OWNER_CHARS,
  normalizeSubs,
  parsePayload,
  sanitizeText,
} from "./protocol";

export const MAX_BODY_BYTES = 65_536;
export const MAX_CLOCK_SKEW_SECONDS = 300;

const PUBLIC_READ = {
  "access-control-allow-origin": "*",
  "access-control-allow-methods": "GET, HEAD, OPTIONS",
};

const REFUSALS: Record<Refusal, number> = { stale: 400, not_joined: 404, rate_limited: 429 };

function refused(outcome: { ok: false; error: Refusal }): Response {
  return error(REFUSALS[outcome.error], outcome.error);
}

/** POST /api/<kind> */
export async function receive(
  path: Kind,
  request: Request,
  env: UniverseEnv,
  url: URL,
): Promise<Response> {
  // 1. Size.
  const body = await readLimited(
    request.body,
    MAX_BODY_BYTES,
    request.headers.get("content-length"),
  );
  if (body === null) return error(413, "too_large");

  // 2. Shape: {payload, sig}, both b64u; the payload a JSON object with the fields of §1.
  const text = utf8(body);
  const wire = text === null ? undefined : parseJson(text);
  if (!isObject(wire)) return badRequest("body must be a JSON object");
  if (typeof wire.payload !== "string" || typeof wire.sig !== "string") {
    return badRequest("payload and sig must be strings");
  }
  const payloadBytes = b64uDecode(wire.payload);
  const sig = b64uDecode(wire.sig);
  if (payloadBytes === null || sig === null) return badRequest("payload and sig must be base64url");
  const payloadText = utf8(payloadBytes);
  const parsed = parsePayload(payloadText === null ? undefined : parseJson(payloadText));
  if (!parsed.ok) return badRequest(parsed.detail);
  const payload = parsed.value;

  // 3. The universe the request was signed for.
  const self = universeHost(env, url);
  if (payload.universe.toLowerCase() !== self) return error(400, "wrong_universe");

  // 4. Freshness: inside the clock window and newer than the last accepted request.
  const now = nowSeconds();
  if (Math.abs(now - payload.ts) > MAX_CLOCK_SKEW_SECONDS) return error(400, "stale");
  const directory = directoryOf(env);
  const last = await directory.lastTs(payload.address);
  if (last !== null && payload.ts <= last) return error(400, "stale");

  // 5. The path names the payload's kind.
  if (payload.kind !== path) return badRequest(`kind ${payload.kind} does not match the path`);

  // 6. The tau's card.
  const card = await fetchCard(env, payload.address);
  if (card === null) return error(502, "card_unavailable");

  // 7. The signature, over the exact bytes decoded from `payload`.
  if (!(await verifyEd25519(card.signKeyBytes, sig, signedMessage(payloadBytes)))) {
    return error(403, "bad_signature");
  }

  // 8–9 and the effect.
  const signed = { address: payload.address, ts: payload.ts, now };
  let outcome: Outcome<object>;
  switch (payload.kind) {
    case "join":
      outcome = await directory.join({
        ...signed,
        name: card.name,
        sign_key: card.signKey,
        owner: sanitizeText(payload.owner, MAX_OWNER_CHARS),
        about: sanitizeText(payload.about, MAX_ABOUT_CHARS),
      });
      if (!outcome.ok) return refused(outcome);
      console.log(JSON.stringify({ event: "joined", address: payload.address }));
      return json({
        ok: true,
        // Always https, also in development (the contract of §2).
        url: `https://${self}/universe#${payload.address}`,
      });
    case "report": {
      const reported = await directory.report({
        ...signed,
        name: card.name,
        sign_key: card.signKey,
        links: payload.links,
        subs: normalizeSubs(payload.subs),
      });
      if (!reported.ok) return refused(reported);
      return json({ ok: true, visible_links: reported.visible_links });
    }
    case "leave":
      outcome = await directory.leave(signed);
      if (!outcome.ok) return refused(outcome);
      console.log(JSON.stringify({ event: "left", address: payload.address }));
      return json({ ok: true });
  }
}

/** Every /api/* request. */
export async function handleApi(request: Request, env: UniverseEnv, url: URL): Promise<Response> {
  const path = url.pathname;
  const method = request.method;

  for (const kind of KINDS) {
    if (path === `/api/${kind}`) {
      if (method !== "POST") return methodNotAllowed(["POST"]);
      return receive(kind, request, env, url);
    }
  }

  const isRead = path === "/api/universe" || path.startsWith("/api/taus/");
  if (!isRead) return notFound();
  if (method === "OPTIONS") return new Response(null, { status: 204, headers: PUBLIC_READ });
  if (method !== "GET" && method !== "HEAD") return methodNotAllowed(["GET", "HEAD", "OPTIONS"]);

  const now = nowSeconds();
  if (path === "/api/universe") {
    const snapshot = await directoryOf(env).snapshot(universeHost(env, url), now);
    return json(snapshot, 200, { ...PUBLIC_READ, "cache-control": "public, max-age=60" });
  }

  let address: string;
  try {
    address = decodeURIComponent(path.slice("/api/taus/".length));
  } catch {
    return json({ error: "not_found" }, 404, PUBLIC_READ);
  }
  const tau = isAddress(address) ? await directoryOf(env).tau(address, now) : null;
  if (tau === null) return json({ error: "not_found" }, 404, PUBLIC_READ);
  return json(tau, 200, { ...PUBLIC_READ, "cache-control": "no-store" });
}
