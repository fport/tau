/**
 * tau-host: a Worker that hosts taus (ADR 0013 §2, §5).
 *
 *   GET  /                          the landing page; signed in → /app
 *   GET  /app, /app/*               the owner's app (sign in first)
 *   GET  /app/assets/*              its scripts and styles (the asset store)
 *   *    /auth/*                    GitHub sign-in, sign-out, development sign-in (src/auth.ts)
 *   *    /api/host/*                the owner's API and whoami (src/api.ts)
 *   *    /api/visit/<handle>/<name> the visitor API of public web sub-taus (src/api.ts)
 *   GET  /@<handle>/<name>          the chat page of a public web sub-tau
 *
 * `/@<handle>/.well-known/tau.json` and `/@<handle>/net/*` belong to the network (issue 162)
 * and answer 404 until then.
 *
 * Every export of this module is an entrypoint for the runtime, so it exports only the
 * handler and the Durable Object classes.
 */

import { handleHostApi, handleVisitApi } from "./api";
import { callback, currentUser, devLogin, login, logout } from "./auth";
import { HANDLE_RE } from "./accounts";
import { NAME_RE } from "./agent/subs";
import { accountsOf, devLoginEnabled, type HostEnv, tauOf } from "./env";
import { error, methodNotAllowed, notFound, redirect } from "./http";
import { appPage, landingPage, notFoundPage, visitPage, withSecurityHeaders } from "./pages";

export { Accounts } from "./accounts";
export { Tau } from "./tau";

function isRead(method: string): boolean {
  return method === "GET" || method === "HEAD";
}

async function route(request: Request, env: HostEnv): Promise<Response> {
  const url = new URL(request.url);
  const path = url.pathname;
  const method = request.method;

  if (path.startsWith("/api/")) {
    if (path.startsWith("/api/host/")) return handleHostApi(request, env, url);
    if (path.startsWith("/api/visit/")) return handleVisitApi(request, env, url);
    return notFound();
  }

  if (path.startsWith("/auth/")) {
    switch (path) {
      case "/auth/login":
        return isRead(method) ? login(request, env, url) : methodNotAllowed(["GET"]);
      case "/auth/callback":
        return isRead(method) ? callback(request, env, url) : methodNotAllowed(["GET"]);
      case "/auth/logout":
        return method === "POST" ? logout(request, env, url) : methodNotAllowed(["POST"]);
      case "/auth/dev":
        return method === "POST" ? devLogin(request, env, url) : methodNotAllowed(["POST"]);
      default:
        return notFoundPage(request);
    }
  }

  if (path.startsWith("/app/assets/")) return env.ASSETS.fetch(request);
  if (!isRead(method)) return methodNotAllowed(["GET"]);

  if (path === "/") {
    const who = await currentUser(request, env);
    if (who !== null) return redirect("/app");
    return landingPage(request, { devLogin: devLoginEnabled(env, url) });
  }

  if (path === "/app" || path.startsWith("/app/")) {
    const who = await currentUser(request, env);
    if (who === null) return redirect(`/auth/login?next=${encodeURIComponent(path)}`);
    return appPage(request, { handle: who.handle, dev: env.FAKE_PROVIDER === "1" });
  }

  const visit = /^\/@([^/]+)\/([^/]+)$/.exec(path);
  if (visit) {
    const [, handle = "", name = ""] = visit;
    if (!HANDLE_RE.test(handle) || !NAME_RE.test(name)) return notFoundPage(request);
    if ((await accountsOf(env).account(handle)) === null) return notFoundPage(request);
    const info = await tauOf(env, handle).visitInfo(name);
    return info === null ? notFoundPage(request) : visitPage(request, info);
  }

  return notFoundPage(request);
}

export default {
  async fetch(request: Request, env: HostEnv): Promise<Response> {
    let response: Response;
    try {
      response = await route(request, env);
    } catch (err) {
      const path = new URL(request.url).pathname;
      // The error's name only: a message could carry a provider's answer.
      console.error(JSON.stringify({ event: "unhandled", path, error: err instanceof Error ? err.name : "error" }));
      response = error(500, "internal");
    }
    return withSecurityHeaders(response);
  },
} satisfies ExportedHandler<HostEnv>;
