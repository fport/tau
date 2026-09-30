/**
 * The JSON API.
 *
 * The owner's API lives under /api/host/ so that a universe in front of the host (ADR 0013
 * §6: it forwards /app, /app/*, /auth/* and /api/host/* over its `HOST` service binding)
 * reaches all of it. Every route needs a session, and every state-changing request an
 * `Origin` equal to the host:
 *
 *   GET    /api/host/whoami                 {handle, github_id} or 401 (for the universe)
 *   GET    /api/host/state                  settings (key as provider + last 4), budget,
 *                                           sub-taus, sessions, pending approvals, defaults
 *   POST   /api/host/onboard                {provider, key, language, universe}
 *   PATCH  /api/host/settings               {provider?, key?, models?, budget_usd?,
 *                                            language?, persona?, profile?, universe?}
 *   GET    /api/host/sessions[?sub=NAME]    the owner's sessions
 *   POST   /api/host/sessions               {sub?} a new session
 *   GET    /api/host/sessions/<id>          a session with its messages and approvals
 *   DELETE /api/host/sessions/<id>
 *   POST   /api/host/chat                   {session?, sub?, text} → NDJSON stream
 *   GET    /api/host/approvals              recent approvals
 *   POST   /api/host/approvals/<id>         {decision: approve|deny} → NDJSON stream
 *   GET    /api/host/subs                   sub-taus
 *   POST   /api/host/subs                   create one
 *   GET    /api/host/subs/<name>
 *   PUT    /api/host/subs/<name>            change one (the name stays)
 *   DELETE /api/host/subs/<name>
 *   GET    /api/host/subs/<name>/visits     its visitor threads of the last 24 hours
 *   POST   /api/host/draft                  {name, description} → {about, persona}
 *   GET    /api/host/templates              starting points for a new sub-tau
 *   GET    /api/host/export                 everything as one JSON file
 *   POST   /api/host/account/delete         {confirm: <handle>} deletes the tau and the account
 *
 * The visitor API is public (no session) and serves public web sub-taus only:
 *
 *   GET    /api/visit/<handle>/<name>       {handle, name, about, starters} or 404
 *   POST   /api/visit/<handle>/<name>       {visitor, thread?, text} → {thread, reply: {id, text, ts}}
 */

import { HANDLE_RE, type Who } from "./accounts";
import { clearedCookie, currentUser, originAllowed, SESSION_COOKIE } from "./auth";
import { sha256b64u } from "./crypto";
import { accountsOf, fakeProviderEnabled, type HostEnv, hostOrigin, tauOf } from "./env";
import { error, json, methodNotAllowed, notFound, readJsonObject, unauthorized } from "./http";
import { NAME_RE } from "./agent/subs";
import type { Outcome } from "./tau";

const SMALL_BODY = 16 * 1024;
const LARGE_BODY = 160 * 1024;

function answer<T>(outcome: Outcome<T>, status = 200): Response {
  if (outcome.ok) return json(outcome.value, status);
  return error(outcome.status, outcome.error, outcome.detail);
}

function isWrite(method: string): boolean {
  return method !== "GET" && method !== "HEAD";
}

export async function handleHostApi(request: Request, env: HostEnv, url: URL): Promise<Response> {
  const parts = url.pathname.split("/").slice(3); // ["", "api", "host", ...]
  const [head = "", second, third, ...rest] = parts;
  const method = request.method;

  const who = await currentUser(request, env);
  if (head === "whoami") {
    if (method !== "GET") return methodNotAllowed(["GET"]);
    return who === null ? unauthorized() : json({ handle: who.handle, github_id: who.github_id });
  }
  if (who === null) return unauthorized();
  if (isWrite(method) && !originAllowed(request, env, url)) return error(403, "bad_origin");
  const tau = tauOf(env, who.handle);
  const fake = fakeProviderEnabled(env);

  switch (head) {
    case "state":
      if (method !== "GET") return methodNotAllowed(["GET"]);
      return json(await tau.state());

    case "onboard": {
      if (method !== "POST") return methodNotAllowed(["POST"]);
      const body = await readJsonObject(request, SMALL_BODY);
      if (!body.ok) return body.response;
      return answer(await tau.onboard(body.value, fake));
    }

    case "settings": {
      if (method !== "PATCH") return methodNotAllowed(["PATCH"]);
      const body = await readJsonObject(request, LARGE_BODY);
      if (!body.ok) return body.response;
      return answer(await tau.updateSettings(body.value, fake));
    }

    case "sessions": {
      if (second === undefined) {
        if (method === "GET") {
          const sub = url.searchParams.get("sub");
          return json(await tau.listSessions(sub === null ? undefined : sub));
        }
        if (method === "POST") {
          const body = await readJsonObject(request, SMALL_BODY);
          if (!body.ok) return body.response;
          const sub = body.value.sub ?? "";
          if (typeof sub !== "string") return error(400, "bad_request", "sub must be text");
          return answer(await tau.newSession(sub), 201);
        }
        return methodNotAllowed(["GET", "POST"]);
      }
      if (third !== undefined) return notFound();
      if (method === "GET") return answer(await tau.session(second));
      if (method === "DELETE") return answer(await tau.deleteSession(second));
      return methodNotAllowed(["GET", "DELETE"]);
    }

    case "chat": {
      if (method !== "POST" || second !== undefined) return method !== "POST" ? methodNotAllowed(["POST"]) : notFound();
      const body = await readJsonObject(request, LARGE_BODY);
      if (!body.ok) return body.response;
      return tau.chat(body.value);
    }

    case "approvals": {
      if (second === undefined) {
        if (method !== "GET") return methodNotAllowed(["GET"]);
        return json(await tau.listApprovals());
      }
      if (third !== undefined) return notFound();
      if (method !== "POST") return methodNotAllowed(["POST"]);
      const body = await readJsonObject(request, SMALL_BODY);
      if (!body.ok) return body.response;
      return tau.decide(second, body.value.decision);
    }

    case "subs": {
      if (second === undefined) {
        if (method === "GET") return json(await tau.listSubs());
        if (method === "POST") {
          const body = await readJsonObject(request, LARGE_BODY);
          if (!body.ok) return body.response;
          return answer(await tau.createSub(body.value), 201);
        }
        return methodNotAllowed(["GET", "POST"]);
      }
      if (!NAME_RE.test(second)) return notFound();
      if (third === "visits" && rest.length === 0) {
        if (method !== "GET") return methodNotAllowed(["GET"]);
        return answer(await tau.visitorThreads(second));
      }
      if (third !== undefined) return notFound();
      if (method === "GET") return answer(await tau.getSub(second));
      if (method === "PUT") {
        const body = await readJsonObject(request, LARGE_BODY);
        if (!body.ok) return body.response;
        return answer(await tau.updateSub(second, body.value));
      }
      if (method === "DELETE") return answer(await tau.deleteSub(second));
      return methodNotAllowed(["GET", "PUT", "DELETE"]);
    }

    case "draft": {
      if (method !== "POST") return methodNotAllowed(["POST"]);
      const body = await readJsonObject(request, SMALL_BODY);
      if (!body.ok) return body.response;
      return answer(await tau.draft(body.value.name, body.value.description));
    }

    case "templates":
      if (method !== "GET") return methodNotAllowed(["GET"]);
      return json(await tau.templates());

    case "export": {
      if (method !== "GET") return methodNotAllowed(["GET"]);
      const data = await tau.exportAll();
      return json(data, 200, {
        "content-disposition": `attachment; filename="tau-${who.handle}-export.json"`,
      });
    }

    case "account": {
      if (second !== "delete" || third !== undefined) return notFound();
      if (method !== "POST") return methodNotAllowed(["POST"]);
      const body = await readJsonObject(request, SMALL_BODY);
      if (!body.ok) return body.response;
      if (body.value.confirm !== who.handle) {
        return error(400, "bad_request", "confirm must be your handle");
      }
      return deleteAccount(env, who, url);
    }

    default:
      return notFound();
  }
}

async function deleteAccount(env: HostEnv, who: Who, url: URL): Promise<Response> {
  await tauOf(env, who.handle).destroy();
  await accountsOf(env).deleteAccount(who.handle);
  console.log(JSON.stringify({ event: "account_deleted", handle: who.handle }));
  return json({ ok: true }, 200, { "set-cookie": clearedCookie(SESSION_COOKIE, url) });
}

/** The public visitor API for web sub-taus. */
export async function handleVisitApi(request: Request, env: HostEnv, url: URL): Promise<Response> {
  const parts = url.pathname.split("/").slice(3); // ["", "api", "visit", handle, name]
  const [handle = "", name = "", ...rest] = parts;
  if (rest.length > 0 || !HANDLE_RE.test(handle) || !NAME_RE.test(name)) return notFound();
  // No session here; a browser on another site must not post in the name of this page.
  const origin = request.headers.get("origin");
  if (origin !== null && origin !== hostOrigin(env, url)) return error(403, "bad_origin");
  // Only handles that exist reach a Tau object: a probe never creates one.
  if ((await accountsOf(env).account(handle)) === null) return notFound();
  const tau = tauOf(env, handle);
  if (request.method === "GET") {
    const info = await tau.visitInfo(name);
    return info === null ? notFound() : json(info);
  }
  if (request.method !== "POST") return methodNotAllowed(["GET", "POST"]);
  const body = await readJsonObject(request, 16 * 1024);
  if (!body.ok) return body.response;
  const ip = request.headers.get("cf-connecting-ip");
  const ipHash = ip ? await sha256b64u(`visit|${ip}`) : null;
  return answer(await tau.visit(name, body.value, ipHash));
}
