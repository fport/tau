/**
 * The optional `HOST` service binding to tau-host (ADR 0013 §2, §6).
 *
 * On a universe with a tau-host behind it (tau.getporti.com), the universe stays the front
 * door: it forwards tau-host's paths (`isForwarded` in src/routes.ts) through the binding
 * unchanged, and asks tau-host who is signed in when a handle is claimed. Without the
 * binding those paths are 404 and claims are 501.
 */

import { isHandle } from "./address";
import type { UniverseEnv } from "./env";
import { error, isObject, parseJson } from "./http";

/**
 * Passes a request to tau-host as it came (method, URL, headers with the cookies, body) and
 * its answer back as it is: tau-host sets its own headers.
 */
export async function forward(request: Request, host: Fetcher): Promise<Response> {
  try {
    return await host.fetch(request);
  } catch (err) {
    const path = new URL(request.url).pathname;
    console.error(JSON.stringify({ event: "host_failed", path, error: String(err) }));
    return error(502, "host_unavailable");
  }
}

/** The GitHub account signed in on tau-host: the lower-case login and the numeric id. */
export interface GitHubAccount {
  handle: string;
  github_id: string;
}

export type WhoAmI =
  | { ok: true; account: GitHubAccount }
  | { ok: false; status: 401 | 502; error: "not_signed_in" | "host_unavailable" };

/**
 * `GET /api/host/whoami` on tau-host with the request's cookies: `200 {handle, github_id}`
 * or `401`. Anything else, or an answer of the wrong shape, is `host_unavailable`.
 */
export async function whoami(request: Request, env: UniverseEnv, url: URL): Promise<WhoAmI> {
  const unavailable = { ok: false, status: 502, error: "host_unavailable" } as const;
  if (env.HOST === undefined) return unavailable;
  const headers: Record<string, string> = { accept: "application/json" };
  const cookie = request.headers.get("cookie");
  if (cookie !== null) headers.cookie = cookie;
  let response: Response;
  try {
    response = await env.HOST.fetch(new URL("/api/host/whoami", url).href, { headers });
  } catch (err) {
    console.error(JSON.stringify({ event: "whoami_failed", error: String(err) }));
    return unavailable;
  }
  if (response.status === 401) {
    await response.body?.cancel();
    return { ok: false, status: 401, error: "not_signed_in" };
  }
  if (response.status !== 200) {
    await response.body?.cancel();
    return unavailable;
  }
  const body = parseJson(await response.text());
  if (!isObject(body) || typeof body.handle !== "string") return unavailable;
  const handle = body.handle.toLowerCase();
  const id = body.github_id;
  const githubId =
    typeof id === "number" && Number.isSafeInteger(id) && id > 0
      ? String(id)
      : typeof id === "string" && /^[1-9][0-9]{0,19}$/.test(id)
        ? id
        : null;
  if (!isHandle(handle) || githubId === null) return unavailable;
  return { ok: true, account: { handle, github_id: githubId } };
}
