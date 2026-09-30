/**
 * The owner's network API, under /api/host/net (the universe forwards /api/host/* to
 * tau-host). The session and the `Origin` of state-changing requests are checked by
 * src/api.ts before these run.
 *
 *   GET  /api/host/net                       address, card name, universe, contacts
 *   GET  /api/host/net/log[?address=A&limit=N]   the network log, oldest first
 *   POST /api/host/net/contacts              {address, note?} → 202 an approval card: a contact
 *                                            request, sent after the owner approves it
 *   POST /api/host/net/contacts/accept       {address} accept a pending request
 *   POST /api/host/net/contacts/decline      {address} forget a pending request, send nothing
 *   POST /api/host/net/contacts/block        {address}
 *   POST /api/host/net/contacts/remove       {address}
 *   POST /api/host/net/send                  {to, text} → 202 an approval card: a message to an
 *                                            accepted contact (`to` may name its sub-tau),
 *                                            sent after the owner approves it
 *   POST /api/host/net/universe              {join: true|false} join and report, or leave
 *
 * Errors: 400 bad_request, 409 `net` (the contact's state or the address; `detail` says
 * what), 409 universe_off, 413 too_large, 503 not_configured (no network address).
 */

import type { Who } from "../accounts";
import { type HostEnv, tauOf } from "../env";
import { error, json, methodNotAllowed, notFound, readJsonObject } from "../http";
import type { Outcome } from "../tau";

const BODY = 32 * 1024;

function answer<T>(outcome: Outcome<T>, status = 200): Response {
  if (outcome.ok) return json(outcome.value, status);
  return error(outcome.status, outcome.error, outcome.detail);
}

export async function handleNetApi(request: Request, env: HostEnv, url: URL, who: Who, parts: string[]): Promise<Response> {
  const tau = tauOf(env, who.handle);
  const method = request.method;
  const host = url.host;
  const [head, second, ...rest] = parts;

  if (head === undefined) {
    if (method !== "GET") return methodNotAllowed(["GET"]);
    return json(await tau.netState(host));
  }
  if (head === "log" && second === undefined) {
    if (method !== "GET") return methodNotAllowed(["GET"]);
    const address = url.searchParams.get("address");
    const limit = Number(url.searchParams.get("limit") ?? "") || undefined;
    return json(await tau.netLog(address ? address.trim().toLowerCase() : null, limit));
  }
  if (method !== "POST") return methodNotAllowed(["POST"]);
  if (rest.length > 0) return notFound();
  const body = await readJsonObject(request, BODY);
  if (!body.ok) return body.response;

  switch (head) {
    case "contacts":
      switch (second) {
        case undefined:
          return answer(await tau.netAdd(body.value, host), 202);
        case "accept":
          return answer(await tau.netAccept(body.value.address, host));
        case "block":
          return answer(await tau.netBlock(body.value.address));
        case "decline":
        case "remove":
          return answer(await tau.netRemove(body.value.address));
        default:
          return notFound();
      }
    case "send":
      if (second !== undefined) return notFound();
      return answer(await tau.netSend(body.value, host), 202);
    case "universe":
      if (second !== undefined) return notFound();
      return answer(await tau.netUniverse(body.value.join, host));
    default:
      return notFound();
  }
}
