/**
 * tau universe: tau's public site and the opt-in directory of taus.
 *
 * Contract: docs/reference/tau-universe.md (§1–§2, §5). Decisions: docs/adr/0010, 0013.
 *
 *   GET  /                        the landing page (static, public/index.html)
 *   GET  /how-it-works            how tau works, for newcomers (static)
 *   GET  /universe                the universe page (static; its script reads /api/universe)
 *   GET  /tr/, /tr/how-it-works, /tr/universe
 *                                 the same pages in Turkish (public/tr/)
 *   GET  /@<handle>               a person page (public/person.html)
 *   GET  /<slug>, /@<handle>/<name>
 *                                 a sub-tau page (public/sub.html)
 *   GET  /claim                   the claim page (public/claim.html); all three under /tr/ too
 *   *    /api/*                   the directory API and the visitor chat (/api/chat/*)
 *   GET  /.well-known/tau.json    the universe's own card (ADR 0013 §5), with UNIVERSE_IDENTITY
 *   POST /net/inbox               hubs' answers to the visits the universe relayed
 *   *    /app, /app/*, /auth/*, /api/host/*, /@<handle>/.well-known/tau.json, /@<handle>/net/*
 *                                 tau-host's, forwarded through the HOST binding when bound
 *
 * Everything else under public/ is served by the asset store before the Worker runs. The
 * hourly cron prunes the directory.
 *
 * Every export of this module is an entrypoint for the runtime, so it exports only the
 * handler and the Durable Object classes.
 */

import { handleApi } from "./api";
import { directoryOf, type UniverseEnv } from "./env";
import { forward } from "./host";
import { error, methodNotAllowed, notFound, nowSeconds } from "./http";
import { serveCard } from "./identity";
import { receiveInbox } from "./inbox";
import { isPage, notFoundPage, servePage, serveRoute, withSecurityHeaders } from "./pages";
import { isForwarded, pageRoute } from "./routes";

export { Directory } from "./directory";
export { Relay } from "./relay";

async function route(
  request: Request,
  env: UniverseEnv,
  url: URL,
  ctx: ExecutionContext | undefined,
): Promise<Response> {
  const path = url.pathname;
  const read = request.method === "GET" || request.method === "HEAD";
  // The universe's own network identity: its card and its inbox.
  if (path === "/.well-known/tau.json") return serveCard(request, env, url);
  if (path === "/net/inbox") return receiveInbox(request, env, url);
  // tau-host's paths on a universe without tau-host.
  if (isForwarded(path)) {
    return read && !path.startsWith("/api/") ? notFoundPage(request, env) : notFound();
  }
  if (path === "/api" || path.startsWith("/api/")) return handleApi(request, env, url, ctx);
  if (!read) return methodNotAllowed(["GET"]);
  if (isPage(path) || path === "/tr") return servePage(request, env, url);
  const page = pageRoute(path);
  if (page !== null) return serveRoute(request, env, url, page);
  return notFoundPage(request, env);
}

export default {
  async fetch(request: Request, env: UniverseEnv, ctx?: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);
    // tau-host answers its own paths, with its own headers.
    if (env.HOST !== undefined && isForwarded(url.pathname)) return forward(request, env.HOST);
    let response: Response;
    try {
      response = await route(request, env, url, ctx);
    } catch (err) {
      console.error(JSON.stringify({ event: "unhandled", path: url.pathname, error: String(err) }));
      response = error(500, "internal");
    }
    return withSecurityHeaders(response);
  },

  async scheduled(_controller: ScheduledController, env: UniverseEnv): Promise<void> {
    const pruned = await directoryOf(env).prune(nowSeconds());
    if (Object.values(pruned).some((count) => count > 0)) {
      console.log(JSON.stringify({ event: "pruned", ...pruned }));
    }
  },
} satisfies ExportedHandler<UniverseEnv>;
