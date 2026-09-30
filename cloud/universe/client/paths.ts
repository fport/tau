/**
 * The site's page paths, without the DOM: reading a handle, a slug or a sub-tau from the
 * URL, and building the links between pages in either language.
 *
 * - `/@<handle>` is a person page, `/<slug>` and `/@<handle>/<name>` a sub-tau page, all
 *   also under `/tr/` (ADR 0013 §6).
 * - A handle is a GitHub login in lower case; a slug is a sub-tau name.
 */

import type { PageLanguage } from "./messages";

/** GitHub's login rules, lower case (ADR 0013 §3). */
export const HANDLE = /^[a-z0-9](?:[a-z0-9-]{0,37}[a-z0-9])?$/;
/** A sub-tau name (ADR 0012), which is also what a slug looks like. */
export const SUB_NAME = /^[a-z][a-z0-9-]{1,30}$/;

/** The path without a leading `/tr` and without trailing slashes, and its language. */
export function splitLanguage(pathname: string): { lang: PageLanguage; rest: string } {
  let path = pathname;
  let lang: PageLanguage = "en";
  if (path === "/tr" || path.startsWith("/tr/")) {
    lang = "tr";
    path = path.slice(3);
  }
  path = path.replace(/\/+$/, "");
  return { lang, rest: path === "" ? "/" : path };
}

function decode(segment: string): string | null {
  try {
    return decodeURIComponent(segment);
  } catch {
    return null;
  }
}

/** `/@alice` (or `/tr/@alice`) → `alice`; anything else → null. Handles compare in lower case. */
export function personFromPath(pathname: string): string | null {
  const { rest } = splitLanguage(pathname);
  const match = /^\/@([^/]+)$/.exec(rest);
  if (match === null) return null;
  const handle = decode(match[1]!)?.toLowerCase() ?? "";
  return HANDLE.test(handle) ? handle : null;
}

/** A sub-tau page's target: a global slug, or a handle and a name. */
export type SubTarget =
  | { kind: "slug"; slug: string }
  | { kind: "handle"; handle: string; name: string };

/** `/coach` or `/@alice/coach` (either under `/tr/`) → the sub-tau; anything else → null. */
export function subFromPath(pathname: string): SubTarget | null {
  const { rest } = splitLanguage(pathname);
  const byHandle = /^\/@([^/]+)\/([^/]+)$/.exec(rest);
  if (byHandle !== null) {
    const handle = decode(byHandle[1]!)?.toLowerCase() ?? "";
    const name = decode(byHandle[2]!) ?? "";
    return HANDLE.test(handle) && SUB_NAME.test(name) ? { kind: "handle", handle, name } : null;
  }
  const bySlug = /^\/([^/@]+)$/.exec(rest);
  if (bySlug !== null) {
    const slug = decode(bySlug[1]!) ?? "";
    return SUB_NAME.test(slug) ? { kind: "slug", slug } : null;
  }
  return null;
}

/** What the APIs call a sub-tau: `coach` or `@alice/coach`. */
export function targetKey(target: SubTarget): string {
  return target.kind === "slug" ? target.slug : `@${target.handle}/${target.name}`;
}

/** A site path in the page's language: `/universe` or `/tr/universe`. */
export function localPath(path: string, lang: PageLanguage): string {
  if (lang === "en") return path;
  return path === "/" ? "/tr/" : `/tr${path}`;
}

export function personPath(handle: string, lang: PageLanguage): string {
  return localPath(`/@${handle}`, lang);
}

/** A tau's place on the universe page, where it is pinned. */
export function universePath(address: string, lang: PageLanguage): string {
  return `${localPath("/universe", lang)}#${address}`;
}

/**
 * A path the API gave for a page (`path`), when it is a plain path on this site: it starts
 * with one `/`, has no backslash, no scheme and nothing a browser would read as another
 * host. Anything else is null, and the page builds the path itself.
 */
export function sitePath(path: unknown): string | null {
  if (typeof path !== "string" || path.length > 300) return null;
  if (!path.startsWith("/") || path.startsWith("//")) return null;
  // Only the characters a page path of this site can have; no controls or backslashes.
  if (!/^\/[A-Za-z0-9@/._~%-]*$/.test(path)) return null;
  return path;
}

/** A sub-tau's page: the API's `path` when it is a site path, else built from what is known. */
export function subPath(
  sub: { name: string; slug?: string | null; path?: unknown },
  handle: string | null,
  lang: PageLanguage,
): string | null {
  const given = sitePath(sub.path);
  if (given !== null) return localPath(given, lang);
  if (typeof sub.slug === "string" && SUB_NAME.test(sub.slug)) {
    return localPath(`/${sub.slug}`, lang);
  }
  if (handle !== null && HANDLE.test(handle)) return localPath(`/@${handle}/${sub.name}`, lang);
  return null;
}

/** `https://github.com/<handle>` for a valid handle; null for anything else. */
export function githubUrl(value: unknown, handle: string): string | null {
  const expected = `https://github.com/${handle}`;
  if (typeof value === "string" && value.toLowerCase() === expected) return value;
  return HANDLE.test(handle) ? expected : null;
}
