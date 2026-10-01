/**
 * tau universe: tau's public site and the opt-in directory of taus. This is the server in
 * front of the pages: it decides what every request is, answers everything that is not a
 * page itself, and asks a renderer for the pages (worker/index.ts renders them with vinext;
 * the tests use a stand-in).
 *
 * Contract: docs/reference/tau-universe.md (§1–§2, §5). Decisions: docs/adr/0010, 0013, 0016.
 *
 *   GET  /                        the landing page
 *   GET  /how-it-works            how tau works, for newcomers
 *   GET  /universe                the universe page (its script reads /api/universe)
 *   GET  /download, /soon         the download page; "opening soon" for sign-in without tau-host
 *   GET  /tr/, /tr/how-it-works, /tr/universe, /tr/download, /tr/soon
 *                                 the same pages in Turkish
 *   GET  /@<handle>               a person page (rendered from /page/person)
 *   GET  /<slug>, /@<handle>/<name>
 *                                 a sub-tau page (rendered from /page/sub)
 *   GET  /claim                   the claim page; all three under /tr/ too
 *   GET  /download/*              the tau app's downloads, from the DOWNLOADS bucket
 *   *    /api/*                   the directory API and the visitor chat (/api/chat/*)
 *   GET  /.well-known/tau.json    the universe's own card (ADR 0013 §5), with UNIVERSE_IDENTITY
 *   POST /net/inbox               hubs' answers to the visits the universe relayed
 *   *    /app, /app/*, /auth/*, /api/host/*, /@<handle>/.well-known/tau.json, /@<handle>/net/*
 *                                 tau-host's, forwarded through the HOST binding when bound,
 *                                 untouched: its body streams through and it keeps its headers
 *
 * Every other path is the 404 page of its language (rendered from /page/missing). Static
 * files (styles, brand SVGs, fonts, the page bundles, install.sh) are served by the asset
 * store before the Worker runs. The hourly cron prunes the directory.
 */

import { handleApi } from "./api";
import { DOWNLOAD_PREFIX, serveDownload } from "./downloads";
import { directoryOf, type UniverseEnv } from "./env";
import { forward } from "./host";
import { error, methodNotAllowed, notFound, nowSeconds } from "./http";
import { serveCard } from "./identity";
import { receiveInbox } from "./inbox";
import {
  cookieLanguage,
  isPage,
  notFoundPage,
  preferredLanguage,
  type RenderPage,
  servePage,
  serveRoute,
  withSecurityHeaders,
} from "./pages";
import { isForwarded, pageRoute } from "./routes";

async function route(
  request: Request,
  env: UniverseEnv,
  url: URL,
  ctx: ExecutionContext | undefined,
  render: RenderPage,
): Promise<Response> {
  const path = url.pathname;
  const read = request.method === "GET" || request.method === "HEAD";
  // The universe's own network identity: its card and its inbox.
  if (path === "/.well-known/tau.json") return serveCard(request, env, url);
  if (path === "/net/inbox") return receiveInbox(request, env, url);
  // tau-host's paths on a universe without tau-host. Sign-in explains that hosted taus
  // are not open here yet instead of answering 404.
  if (path === "/auth/login" && read) return signInSoon(request);
  if (isForwarded(path)) {
    return read && !path.startsWith("/api/") ? notFoundPage(request, env, ctx, render) : notFound();
  }
  if (path === "/api" || path.startsWith("/api/")) return handleApi(request, env, url, ctx);
  // The tau app's downloads from R2 (src/downloads.ts); anything else under /download/ is 404.
  if (path.startsWith(DOWNLOAD_PREFIX)) {
    const download = await serveDownload(request, env, url);
    if (download !== null) return download;
  }
  if (!read) return methodNotAllowed(["GET"]);
  if (isPage(path) || path === "/tr") return servePage(request, env, url, ctx, render);
  const page = pageRoute(path);
  if (page !== null) return serveRoute(request, env, url, ctx, page, render);
  return notFoundPage(request, env, ctx, render);
}

/** `/auth/login` without tau-host: the "opening soon" page in the visitor's language. */
function signInSoon(request: Request): Response {
  const lang =
    cookieLanguage(request.headers.get("cookie")) ??
    preferredLanguage(request.headers.get("accept-language")) ??
    "en";
  const location = lang === "tr" ? "/tr/soon" : "/soon";
  return new Response(null, { status: 302, headers: { location, "cache-control": "no-store" } });
}

/**
 * The Worker's handlers around a page renderer: `fetch` for every request, `scheduled` for
 * the hourly prune.
 */
export function createUniverse(render: RenderPage) {
  return {
    async fetch(request: Request, env: UniverseEnv, ctx?: ExecutionContext): Promise<Response> {
      const url = new URL(request.url);
      // tau-host answers its own paths, with its own headers.
      if (env.HOST !== undefined && isForwarded(url.pathname)) return forward(request, env.HOST);
      let response: Response;
      try {
        response = await route(request, env, url, ctx, render);
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
}
