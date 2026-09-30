/**
 * tau universe: tau's public site and the opt-in directory of taus.
 *
 * Contract: docs/reference/tau-universe.md (§1–§2). Decision: docs/adr/0010.
 *
 *   GET  /                        the landing page (static, public/index.html)
 *   GET  /how-it-works            how tau works, for newcomers (static)
 *   GET  /universe                the universe page (static; its script reads /api/universe)
 *   GET  /tr/, /tr/how-it-works, /tr/universe
 *                                 the same pages in Turkish (public/tr/)
 *   *    /api/*                   the directory API
 *
 * Everything else under public/ is served by the asset store before the Worker runs. The
 * hourly cron prunes the directory.
 *
 * Every export of this module is an entrypoint for the runtime, so it exports only the
 * handler and the Durable Object class.
 */

import { handleApi } from "./api";
import { directoryOf, type UniverseEnv } from "./env";
import { error, methodNotAllowed, nowSeconds } from "./http";
import { isPage, notFoundPage, servePage, withSecurityHeaders } from "./pages";

export { Directory } from "./directory";

async function route(request: Request, env: UniverseEnv): Promise<Response> {
  const url = new URL(request.url);
  const path = url.pathname;
  if (path === "/api" || path.startsWith("/api/")) return handleApi(request, env, url);
  if (request.method !== "GET" && request.method !== "HEAD") return methodNotAllowed(["GET"]);
  if (isPage(path) || path === "/tr") return servePage(request, env, url);
  return notFoundPage(request, env);
}

export default {
  async fetch(request: Request, env: UniverseEnv): Promise<Response> {
    let response: Response;
    try {
      response = await route(request, env);
    } catch (err) {
      const path = new URL(request.url).pathname;
      console.error(JSON.stringify({ event: "unhandled", path, error: String(err) }));
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
