/**
 * The pages in both languages, the 404 pages, the language choice and the security headers.
 *
 * The pages are React pages (app/, site/; ADR 0016) that a renderer turns into HTML:
 * worker/index.ts asks vinext, with a fresh CSP nonce for each page. This module decides
 * which page a request gets and with which status and headers; the renderer only renders.
 *
 * The person, sub-tau and claim pages (ADR 0013 §6) are looked up first: `/@<handle>` renders
 * the internal page /page/person, `/<slug>` and `/@<handle>/<name>` render /page/sub, `/claim`
 * renders /claim (and the same under /tr/). An unknown handle or slug is the 404 page; the
 * page's script reads the data from /api/people or /api/subs.
 *
 * Language rules, kept small on purpose:
 * - A page link with `?lang=en` or `?lang=tr` (the switcher's links) stores that choice in
 *   the `lang` cookie and redirects to the same URL without the parameter. That click is the
 *   only way the site sets a cookie.
 * - `/` redirects to `/tr/` when the cookie says `tr`, or when there is no cookie and
 *   Accept-Language prefers Turkish to English. A stored choice always wins.
 * - No other page redirects: `/how-it-works` is English and `/tr/how-it-works` Turkish.
 */

import { directoryOf, type UniverseEnv } from "./env";
import type { PageRoute } from "./routes";

export const CONTENT_SECURITY_POLICY =
  "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; " +
  "connect-src 'self'; frame-ancestors 'none'";

/**
 * A page's policy: the same, with its nonce allowed for scripts and styles. React streams the
 * page's payload in inline scripts, and vinext puts the nonce on every script and style it
 * writes (ADR 0016 §5).
 */
export function pageSecurityPolicy(nonce: string): string {
  return (
    "default-src 'self'; img-src 'self' data:; " +
    `style-src 'self' 'nonce-${nonce}'; script-src 'self' 'nonce-${nonce}'; ` +
    "connect-src 'self'; frame-ancestors 'none'"
  );
}

/** A fresh nonce: 16 random bytes in base64. */
export function newNonce(): string {
  return btoa(String.fromCharCode(...crypto.getRandomValues(new Uint8Array(16))));
}

export const SECURITY_HEADERS: Readonly<Record<string, string>> = {
  "content-security-policy": CONTENT_SECURITY_POLICY,
  "x-content-type-options": "nosniff",
  "referrer-policy": "strict-origin-when-cross-origin",
};

export type Language = "en" | "tr";

export const LANGUAGES: readonly Language[] = ["en", "tr"];

/** The cookie the language switcher sets. */
export const LANGUAGE_COOKIE = "lang";

/** One year, in seconds. */
const LANGUAGE_COOKIE_MAX_AGE = 31_536_000;

/** Every page and its language. Each English page has a Turkish twin under /tr/. */
export const PAGES: Readonly<Record<string, Language>> = {
  "/": "en",
  "/how-it-works": "en",
  "/universe": "en",
  "/download": "en",
  "/soon": "en",
  "/tr/": "tr",
  "/tr/how-it-works": "tr",
  "/tr/universe": "tr",
  "/tr/download": "tr",
  "/tr/soon": "tr",
};

/** What a renderer is asked for: the app route to render, and the page's language. */
export interface PageTarget {
  /** A path of app/: the page's own path, or an internal one (`/page/person`, `/page/missing`). */
  path: string;
  lang: Language;
}

/** Renders a page of app/ for a request. The request keeps its own URL; `target` says what. */
export type RenderPage = (
  request: Request,
  target: PageTarget,
  env: UniverseEnv,
  ctx: ExecutionContext | undefined,
) => Promise<Response>;

/** The app route of a page path: the Turkish start page is `/tr` there (no trailing slash). */
function appPath(path: string): string {
  return path === "/tr/" ? "/tr" : path;
}

/**
 * Renders a page and gives it the status and headers this module decides: the language, and
 * no body for HEAD.
 */
async function rendered(
  request: Request,
  target: PageTarget,
  env: UniverseEnv,
  ctx: ExecutionContext | undefined,
  render: RenderPage,
  status = 200,
): Promise<Response> {
  const page = await render(request, target, env, ctx);
  const headers = new Headers(page.headers);
  headers.set("content-language", target.lang);
  if (status !== 200) headers.set("cache-control", "no-store");
  if (request.method === "HEAD") {
    await page.body?.cancel();
    return new Response(null, { status, headers });
  }
  return new Response(page.body, { status, headers });
}

export function isPage(path: string): boolean {
  return Object.hasOwn(PAGES, path);
}

/** The language of a path: Turkish under /tr, English everywhere else. */
export function languageOfPath(path: string): Language {
  return path === "/tr" || path.startsWith("/tr/") ? "tr" : "en";
}

function isLanguage(value: string | null | undefined): value is Language {
  return value === "en" || value === "tr";
}

/** The language stored by the switcher, or null. */
export function cookieLanguage(cookieHeader: string | null): Language | null {
  if (cookieHeader === null) return null;
  for (const part of cookieHeader.split(";")) {
    const eq = part.indexOf("=");
    if (eq === -1) continue;
    if (part.slice(0, eq).trim() !== LANGUAGE_COOKIE) continue;
    const value = part.slice(eq + 1).trim();
    return isLanguage(value) ? value : null;
  }
  return null;
}

/**
 * The site language an Accept-Language header prefers: the first of `en` and `tr` in the
 * order of the header's q-values (ties keep the header's order), or null when it names
 * neither. `tr-TR` counts as `tr`, `en-GB` as `en`; `q=0` means "not this one".
 */
export function preferredLanguage(acceptLanguage: string | null): Language | null {
  if (acceptLanguage === null) return null;
  const ranked: { lang: string; q: number; index: number }[] = [];
  acceptLanguage.split(",").forEach((entry, index) => {
    const [tag = "", ...params] = entry.trim().split(";");
    let q = 1;
    for (const param of params) {
      const [key, value] = param.trim().split("=");
      if (key?.trim().toLowerCase() === "q") {
        const parsed = Number(value);
        q = Number.isFinite(parsed) ? parsed : 0;
      }
    }
    const lang = tag.trim().toLowerCase().split("-")[0] ?? "";
    if (q > 0 && lang !== "") ranked.push({ lang, q, index });
  });
  ranked.sort((a, b) => b.q - a.q || a.index - b.index);
  for (const { lang } of ranked) if (isLanguage(lang)) return lang;
  return null;
}

/** A copy of `response` with the security headers set; a page keeps its own nonce policy. */
export function withSecurityHeaders(response: Response): Response {
  const secured = new Response(response.body, response);
  for (const [name, value] of Object.entries(SECURITY_HEADERS)) {
    if (name === "content-security-policy" && secured.headers.has(name)) continue;
    secured.headers.set(name, value);
  }
  return secured;
}

function redirect(location: string, extra: Record<string, string> = {}): Response {
  return new Response(null, {
    status: 302,
    headers: { location, "cache-control": "no-store", ...extra },
  });
}

/** The URL's path and query without `name`. */
function withoutParam(url: URL, name: string): string {
  const params = new URLSearchParams(url.search);
  params.delete(name);
  const query = params.toString();
  return query === "" ? url.pathname : `${url.pathname}?${query}`;
}

/**
 * The switcher's `?lang=en|tr`: stores the choice in the cookie and redirects to the URL
 * without the parameter. Null when the URL names no language the site has.
 */
function languageChoice(url: URL): Response | null {
  const chosen = url.searchParams.get(LANGUAGE_COOKIE);
  if (!isLanguage(chosen)) return null;
  const secure = url.protocol === "https:" ? "; Secure" : "";
  return redirect(withoutParam(url, LANGUAGE_COOKIE), {
    "set-cookie":
      `${LANGUAGE_COOKIE}=${chosen}; Path=/; Max-Age=${LANGUAGE_COOKIE_MAX_AGE}; ` +
      `SameSite=Lax; HttpOnly${secure}`,
  });
}

/**
 * A page (a path of PAGES, or `/tr`): the switcher's `?lang=`, the start page's language,
 * then the page itself.
 */
export async function servePage(
  request: Request,
  env: UniverseEnv,
  url: URL,
  ctx: ExecutionContext | undefined,
  render: RenderPage,
): Promise<Response> {
  const path = url.pathname;
  if (path === "/tr") return redirect(`/tr/${url.search}`);

  const choice = languageChoice(url);
  if (choice !== null) return choice;

  const start = path === "/";
  if (start) {
    const stored = cookieLanguage(request.headers.get("cookie"));
    const wanted = stored ?? preferredLanguage(request.headers.get("accept-language"));
    if (wanted === "tr") return redirect(`/tr/${url.search}`, { vary: "Accept-Language, Cookie" });
  }

  const response = await rendered(
    request,
    { path: appPath(path), lang: languageOfPath(path) },
    env,
    ctx,
    render,
  );
  if (start) response.headers.append("vary", "Accept-Language, Cookie");
  return response;
}

/**
 * Any path that matched neither a file nor a route: the 404 page of the path's language
 * (/page/missing, or /tr/page/missing under /tr/) with status 404.
 */
export async function notFoundPage(
  request: Request,
  env: UniverseEnv,
  ctx: ExecutionContext | undefined,
  render: RenderPage,
): Promise<Response> {
  const lang = languageOfPath(new URL(request.url).pathname);
  const target = { path: lang === "tr" ? "/tr/page/missing" : "/page/missing", lang };
  try {
    return await rendered(request, target, env, ctx, render, 404);
  } catch (err) {
    console.error(JSON.stringify({ event: "missing_page_failed", error: String(err) }));
    return new Response("Not found\n", {
      status: 404,
      headers: { "content-type": "text/plain; charset=utf-8" },
    });
  }
}

/** Hosts a development server answers on; production is never one of them. */
const LOCAL_HOSTS: ReadonlySet<string> = new Set(["localhost", "127.0.0.1", "[::1]"]);

/**
 * `?fixture=1` on a local development host shows a person or sub-tau page without the
 * lookup, so it can be looked at with the pages' built-in fixtures (client/api.ts).
 */
export function fixturePreview(url: URL): boolean {
  return LOCAL_HOSTS.has(url.hostname) && url.searchParams.get("fixture") === "1";
}

/** The app route each looked-up page renders. */
const TEMPLATE_PATHS = {
  claim: "/claim",
  person: "/page/person",
  sub: "/page/sub",
  slug: "/page/sub",
} as const;

/**
 * A looked-up page (`pageRoute` in src/routes.ts): the switcher's `?lang=`, then the lookup
 * of its handle or slug, then the page, or the 404 page when the directory has no such
 * person or sub-tau.
 */
export async function serveRoute(
  request: Request,
  env: UniverseEnv,
  url: URL,
  ctx: ExecutionContext | undefined,
  route: PageRoute,
  render: RenderPage,
): Promise<Response> {
  if (route.kind === "redirect") {
    return new Response(null, {
      status: 301,
      headers: { location: `${route.location}${url.search}` },
    });
  }
  if (route.kind === "template") return notFoundPage(request, env, ctx, render);

  const choice = languageChoice(url);
  if (choice !== null) return choice;

  if (route.kind !== "claim" && !fixturePreview(url)) {
    const exists = await directoryOf(env).pageExists(
      route.kind === "person"
        ? { handle: route.handle }
        : route.kind === "sub"
          ? { handle: route.handle, name: route.name }
          : { slug: route.slug },
    );
    if (!exists) return notFoundPage(request, env, ctx, render);
  }

  const prefix = route.lang === "tr" ? "/tr" : "";
  return rendered(
    request,
    { path: `${prefix}${TEMPLATE_PATHS[route.kind]}`, lang: route.lang },
    env,
    ctx,
    render,
  );
}
