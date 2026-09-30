/**
 * The universe API (§2 of docs/reference/tau-universe.md):
 *
 *   GET  /api/universe                  the public snapshot
 *   GET  /api/taus/<address>            one tau with its visible links
 *   GET  /api/people/<handle>           a person page's data (ADR 0013 §6)
 *   GET  /api/subs/<slug>               a sub-tau page's data, by its short name
 *   GET  /api/subs/@<handle>/<name>     the same, by its tau's handle
 *   POST /api/join|report|leave         signed requests from taus
 *   POST /api/claim                     a signed claim plus the GitHub account signed in
 *   *    /api/chat/...                   the visitor chat with web sub-taus (src/chat.ts)
 *
 * A POST is checked in the reference's order. The Worker does everything that needs no
 * stored state (size, shape, universe, clock window, card, signature, the GitHub account);
 * the Directory judges the rest (replay, joined, rate limit, handle rules) and applies the
 * effect atomically.
 */

import { hostedHandle, isAddress, isHandle, universeHost } from "./address";
import { fetchCard } from "./card";
import { handleChat } from "./chat";
import { b64uDecode, signedMessage, verifyEd25519 } from "./crypto";
import type { Outcome, Refusal, SubRef } from "./directory";
import { directoryOf, type UniverseEnv } from "./env";
import { whoami } from "./host";
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
  CLAIM_WINDOW_SECONDS,
  CLOCK_WINDOW_SECONDS,
  type Kind,
  KINDS,
  MAX_ABOUT_CHARS,
  MAX_OWNER_CHARS,
  normalizeSubs,
  parsePayload,
  sanitizeText,
  SUB_NAME,
} from "./protocol";

export const MAX_BODY_BYTES = 65_536;

const PUBLIC_READ = {
  "access-control-allow-origin": "*",
  "access-control-allow-methods": "GET, HEAD, OPTIONS",
};

/** The person and sub-tau pages' data changes with reports, about once an hour. */
const PAGE_CACHE = "public, max-age=30";

const REFUSALS: Record<Refusal, number> = {
  stale: 400,
  not_joined: 404,
  rate_limited: 429,
  handle_taken: 409,
  handle_mismatch: 409,
};

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
  // 0. A claim needs tau-host to know who is signed in, and comes from the claim page.
  if (path === "claim") {
    if (env.HOST === undefined) return error(501, "claims_unavailable");
    if (request.headers.get("origin") !== url.origin) return error(403, "bad_origin");
  }

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

  // 4. Freshness: inside the clock window of the kind, and not a replay: newer than the
  //    last accepted request, or for a claim a nonce not used before.
  const now = nowSeconds();
  const window = payload.kind === "claim" ? CLAIM_WINDOW_SECONDS : CLOCK_WINDOW_SECONDS;
  if (Math.abs(now - payload.ts) > window) return error(400, "stale");
  const directory = directoryOf(env);
  if (payload.kind === "claim") {
    if (await directory.nonceUsed(payload.address, payload.nonce)) return error(400, "stale");
  } else {
    const last = await directory.lastTs(payload.address);
    if (last !== null && payload.ts <= last) return error(400, "stale");
  }

  // 5. The path names the payload's kind.
  if (payload.kind !== path) return badRequest(`kind ${payload.kind} does not match the path`);

  // 6. The tau's card.
  const card = await fetchCard(env, payload.address, self);
  if (card === null) return error(502, "card_unavailable");

  // 7. The signature, over the exact bytes decoded from `payload`.
  if (!(await verifyEd25519(card.signKeyBytes, sig, signedMessage(payloadBytes)))) {
    return error(403, "bad_signature");
  }

  // 8–9 (and for a claim the GitHub account first), then the effect.
  const signed = { address: payload.address, ts: payload.ts, now };
  const handle = hostedHandle(payload.address, self);
  let outcome: Outcome<object>;
  switch (payload.kind) {
    case "join":
      outcome = await directory.join({
        ...signed,
        name: card.name,
        sign_key: card.signKey,
        owner: sanitizeText(payload.owner, MAX_OWNER_CHARS),
        about: sanitizeText(payload.about, MAX_ABOUT_CHARS),
        handle,
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
        handle,
      });
      if (!reported.ok) return refused(reported);
      return json({ ok: true, visible_links: reported.visible_links });
    }
    case "leave":
      outcome = await directory.leave(signed);
      if (!outcome.ok) return refused(outcome);
      console.log(JSON.stringify({ event: "left", address: payload.address }));
      return json({ ok: true });
    case "claim": {
      const who = await whoami(request, env, url);
      if (!who.ok) return error(who.status, who.error);
      const claimed = await directory.claim({
        ...signed,
        universe: self,
        nonce: payload.nonce,
        handle: who.account.handle,
        github_id: who.account.github_id,
      });
      if (!claimed.ok) return refused(claimed);
      console.log(
        JSON.stringify({ event: "claimed", address: payload.address, handle: claimed.handle }),
      );
      return json({
        ok: true,
        handle: claimed.handle,
        url: `https://${self}/@${claimed.handle}`,
        moved_from: claimed.moved_from,
      });
    }
  }
}

/** A read of the API: the snapshot, a tau, a person or a sub-tau. */
type Read =
  | { kind: "universe" }
  | { kind: "tau"; address: string }
  | { kind: "person"; handle: string }
  | { kind: "sub"; ref: SubRef }
  /** A read path whose target cannot exist (bad address, handle or name). */
  | { kind: "missing" };

function readOf(path: string): Read | null {
  if (path === "/api/universe") return { kind: "universe" };
  if (path.startsWith("/api/taus/")) {
    let address: string;
    try {
      address = decodeURIComponent(path.slice("/api/taus/".length));
    } catch {
      return { kind: "missing" };
    }
    return isAddress(address) ? { kind: "tau", address } : { kind: "missing" };
  }
  if (path.startsWith("/api/people/")) {
    const handle = path.slice("/api/people/".length).toLowerCase();
    return isHandle(handle) ? { kind: "person", handle } : { kind: "missing" };
  }
  if (path.startsWith("/api/subs/")) {
    const rest = path.slice("/api/subs/".length);
    const byHandle = /^@([^/]+)\/([^/]+)$/.exec(rest);
    if (byHandle !== null) {
      const handle = byHandle[1]!.toLowerCase();
      const name = byHandle[2]!;
      return isHandle(handle) && SUB_NAME.test(name)
        ? { kind: "sub", ref: { handle, name } }
        : { kind: "missing" };
    }
    return SUB_NAME.test(rest) ? { kind: "sub", ref: { slug: rest } } : { kind: "missing" };
  }
  return null;
}

/** Every /api/* request that is not forwarded to tau-host. */
export async function handleApi(
  request: Request,
  env: UniverseEnv,
  url: URL,
  ctx?: ExecutionContext,
): Promise<Response> {
  const path = url.pathname;
  const method = request.method;

  if (path === "/api/chat" || path.startsWith("/api/chat/")) {
    return handleChat(request, env, url, ctx);
  }

  for (const kind of KINDS) {
    if (path === `/api/${kind}`) {
      if (method !== "POST") return methodNotAllowed(["POST"]);
      return receive(kind, request, env, url);
    }
  }

  const read = readOf(path);
  if (read === null) return notFound();
  if (method === "OPTIONS") return new Response(null, { status: 204, headers: PUBLIC_READ });
  if (method !== "GET" && method !== "HEAD") return methodNotAllowed(["GET", "HEAD", "OPTIONS"]);

  const now = nowSeconds();
  const self = universeHost(env, url);
  const missing = () => json({ error: "not_found" }, 404, PUBLIC_READ);
  switch (read.kind) {
    case "universe": {
      const snapshot = await directoryOf(env).snapshot(self, now);
      return json(snapshot, 200, { ...PUBLIC_READ, "cache-control": "public, max-age=60" });
    }
    case "tau": {
      const tau = await directoryOf(env).tau(read.address, now);
      if (tau === null) return missing();
      return json(tau, 200, { ...PUBLIC_READ, "cache-control": "no-store" });
    }
    case "person": {
      const person = await directoryOf(env).person(read.handle, self, now);
      if (person === null) return missing();
      return json(person, 200, { ...PUBLIC_READ, "cache-control": PAGE_CACHE });
    }
    case "sub": {
      const sub = await directoryOf(env).sub(read.ref, self, now);
      if (sub === null) return missing();
      return json(sub, 200, { ...PUBLIC_READ, "cache-control": PAGE_CACHE });
    }
    case "missing":
      return missing();
  }
}
