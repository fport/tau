/**
 * The pages in both languages, the 404 pages, the language choice and the security headers.
 *
 * The pages are static files in public/ (English) and public/tr/ (Turkish), served through
 * the ASSETS binding. The Worker runs first for every page path (see `run_worker_first`) to
 * add the headers of §2, to pick the start page's language and to remember the language
 * switcher's choice; every other static file gets the same headers from public/_headers.
 *
 * The person, sub-tau and claim pages (ADR 0013 §6) are templates: `/@<handle>` serves
 * public/person.html, `/<slug>` and `/@<handle>/<name>` serve public/sub.html, `/claim`
 * serves public/claim.html (and the same under /tr/). The Worker looks the handle or slug up
 * in the directory first, so an unknown one is the 404 page; the page's script reads the
 * data from /api/people or /api/subs.
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
import { type PageRoute, TEMPLATES } from "./routes";

export const CONTENT_SECURITY_POLICY =
  "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; " +
  "connect-src 'self'; frame-ancestors 'none'";

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
  "/tr/": "tr",
  "/tr/how-it-works": "tr",
  "/tr/universe": "tr",
  "/tr/download": "tr",
};

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

/** A copy of `response` with the security headers set. */
export function withSecurityHeaders(response: Response): Response {
  const secured = new Response(response.body, response);
  for (const [name, value] of Object.entries(SECURITY_HEADERS)) secured.headers.set(name, value);
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
 * then the static file as the asset store serves it.
 */
export async function servePage(request: Request, env: UniverseEnv, url: URL): Promise<Response> {
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

  const page = await env.ASSETS.fetch(request);
  const response = new Response(page.body, page);
  if (page.status === 200) response.headers.set("content-language", languageOfPath(path));
  if (start) response.headers.append("vary", "Accept-Language, Cookie");
  return response;
}

/**
 * Any path that matched neither a file nor a route: the 404 page of the path's language
 * (public/404.html, or public/tr/404.html under /tr/) with status 404.
 */
export async function notFoundPage(request: Request, env: UniverseEnv): Promise<Response> {
  const lang = languageOfPath(new URL(request.url).pathname);
  const page = await env.ASSETS.fetch(new URL(lang === "tr" ? "/tr/404" : "/404", request.url));
  if (page.status !== 200) {
    await page.body?.cancel();
    return new Response("Not found\n", {
      status: 404,
      headers: { "content-type": "text/plain; charset=utf-8" },
    });
  }
  if (request.method === "HEAD") await page.body?.cancel();
  return new Response(request.method === "HEAD" ? null : page.body, {
    status: 404,
    headers: {
      "content-type": "text/html; charset=utf-8",
      "content-language": lang,
      "cache-control": "no-store",
    },
  });
}

/**
 * A template page (`pageRoute` in src/routes.ts): the switcher's `?lang=`, then the lookup
 * of its handle or slug, then public/<template>.html (public/tr/ in Turkish), or the 404
 * page when the directory has no such person or sub-tau.
 */
export async function serveRoute(
  request: Request,
  env: UniverseEnv,
  url: URL,
  route: PageRoute,
): Promise<Response> {
  if (route.kind === "redirect") {
    return new Response(null, {
      status: 301,
      headers: { location: `${route.location}${url.search}` },
    });
  }
  if (route.kind === "template") return notFoundPage(request, env);

  const choice = languageChoice(url);
  if (choice !== null) return choice;

  if (route.kind !== "claim") {
    const exists = await directoryOf(env).pageExists(
      route.kind === "person"
        ? { handle: route.handle }
        : route.kind === "sub"
          ? { handle: route.handle, name: route.name }
          : { slug: route.slug },
    );
    if (!exists) return notFoundPage(request, env);
  }

  const template = TEMPLATES[route.kind];
  const file = route.lang === "tr" ? `/tr/${template}` : `/${template}`;
  const page = await env.ASSETS.fetch(new Request(new URL(file, url), request));
  if (page.status === 404) {
    // The template is missing from this deployment: the page does not exist either.
    await page.body?.cancel();
    return notFoundPage(request, env);
  }
  const response = new Response(page.body, page);
  if (page.status === 200) response.headers.set("content-language", route.lang);
  return response;
}
