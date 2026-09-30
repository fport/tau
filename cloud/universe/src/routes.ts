/**
 * The site's routes in one place (§2 of docs/reference/tau-universe.md, ADR 0013 §6):
 * which paths go to tau-host, which are handle and sub-tau pages, and which names a sub-tau
 * can never take as its short page `/<slug>`.
 *
 * Pure: no bindings, no storage. src/index.ts dispatches on what these functions return.
 */

import { isHandle } from "./address";
import { RESERVED_SUB_NAMES, SUB_NAME } from "./protocol";

/**
 * Names a slug can never be, because the site uses them itself: every page and template,
 * every top-level file or directory under public/ (and public/app/, the build output),
 * every path prefix of the Worker and of tau-host, and a few names kept for later. A test
 * checks that every top-level entry of public/ is listed here.
 */
export const RESERVED_NAMES: ReadonlySet<string> = new Set([
  // Pages, templates and their files under public/.
  "index",
  "universe",
  "how-it-works",
  "tr",
  "claim",
  "person",
  "sub",
  "404",
  "soon",
  "brand",
  "styles",
  "app",
  "fonts",
  "static",
  "assets",
  "favicon.ico",
  "robots.txt",
  ".well-known",
  "_headers",
  // The Worker's paths and tau-host's (forwarded).
  "api",
  "auth",
  "net",
  "hub",
  // Kept for the site.
  "docs",
  "about",
  "login",
  "logout",
  "settings",
  "new",
  "help",
]);

export function isReservedName(name: string): boolean {
  return RESERVED_NAMES.has(name);
}

/** Whether a sub-tau with this name can own the short page `/<name>`. */
export function isSlugCandidate(name: string): boolean {
  return SUB_NAME.test(name) && !isReservedName(name);
}

/**
 * Paths tau-host answers on the universe's host, through the `HOST` binding: the owner's
 * app, sign-in, tau-host's own API, and the card and inbox of every hosted tau.
 */
export function isForwarded(path: string): boolean {
  if (path === "/app" || path.startsWith("/app/")) return true;
  if (path.startsWith("/auth/") || path.startsWith("/api/host/")) return true;
  const match = /^\/@([^/]+)(\/.*)$/.exec(path);
  if (match === null || !isHandle(match[1])) return false;
  const rest = match[2]!;
  return rest === "/.well-known/tau.json" || rest.startsWith("/net/");
}

export type PageLanguage = "en" | "tr";

/** A page the Worker serves from a template after it looked the target up. */
export type PageRoute =
  | { kind: "claim"; lang: PageLanguage }
  | { kind: "person"; lang: PageLanguage; handle: string }
  | { kind: "sub"; lang: PageLanguage; handle: string; name: string }
  | { kind: "slug"; lang: PageLanguage; slug: string }
  /** `/@Alice` and the like: the same page at the lower-case handle. */
  | { kind: "redirect"; location: string }
  /** A template asked for by its own name (`/person`, `/sub`): never served bare. */
  | { kind: "template" };

/** The template file of each page kind, under public/ and public/tr/. */
export const TEMPLATES = { claim: "claim", person: "person", sub: "sub", slug: "sub" } as const;

/**
 * Which page a path is: `/claim`, `/@<handle>`, `/@<handle>/<name>` or `/<slug>`, each also
 * under `/tr/`. Null for every other path, including the static pages of `PAGES`.
 */
export function pageRoute(path: string): PageRoute | null {
  const turkish = path.startsWith("/tr/");
  const lang: PageLanguage = turkish ? "tr" : "en";
  const prefix = turkish ? "/tr" : "";
  const rest = turkish ? path.slice(3) : path;

  if (rest === "/claim") return { kind: "claim", lang };
  if (rest === "/person" || rest === "/sub") return { kind: "template" };

  const person = /^\/@([A-Za-z0-9-]+)$/.exec(rest);
  if (person !== null) {
    const handle = person[1]!.toLowerCase();
    if (!isHandle(handle)) return null;
    if (handle !== person[1]) return { kind: "redirect", location: `${prefix}/@${handle}` };
    return { kind: "person", lang, handle };
  }

  const sub = /^\/@([A-Za-z0-9-]+)\/([a-z][a-z0-9-]*)$/.exec(rest);
  if (sub !== null) {
    const handle = sub[1]!.toLowerCase();
    const name = sub[2]!;
    if (!isHandle(handle) || !SUB_NAME.test(name) || RESERVED_SUB_NAMES.has(name)) return null;
    if (handle !== sub[1]) return { kind: "redirect", location: `${prefix}/@${handle}/${name}` };
    return { kind: "sub", lang, handle, name };
  }

  const slug = /^\/([a-z][a-z0-9-]*)$/.exec(rest);
  if (slug !== null && isSlugCandidate(slug[1]!)) return { kind: "slug", lang, slug: slug[1]! };
  return null;
}
