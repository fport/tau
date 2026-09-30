/**
 * The two pages, the 404 page and the security headers.
 *
 * The pages are static files in public/, served through the ASSETS binding. The Worker
 * runs first for `/` and `/universe` (see `run_worker_first`) only to add the headers of
 * §2; every other static file gets the same headers from public/_headers.
 */

import type { UniverseEnv } from "./env";

export const CONTENT_SECURITY_POLICY =
  "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; " +
  "connect-src 'self'; frame-ancestors 'none'";

export const SECURITY_HEADERS: Readonly<Record<string, string>> = {
  "content-security-policy": CONTENT_SECURITY_POLICY,
  "x-content-type-options": "nosniff",
  "referrer-policy": "strict-origin-when-cross-origin",
};

/** A copy of `response` with the security headers set. */
export function withSecurityHeaders(response: Response): Response {
  const secured = new Response(response.body, response);
  for (const [name, value] of Object.entries(SECURITY_HEADERS)) secured.headers.set(name, value);
  return secured;
}

/** `/` and `/universe`: the static page as the asset store serves it. */
export function servePage(request: Request, env: UniverseEnv): Promise<Response> {
  return env.ASSETS.fetch(request);
}

/** Any path that matched neither a file nor a route: public/404.html with status 404. */
export async function notFoundPage(request: Request, env: UniverseEnv): Promise<Response> {
  const page = await env.ASSETS.fetch(new URL("/404", request.url));
  if (page.status !== 200) {
    await page.body?.cancel();
    return new Response("Not found\n", {
      status: 404,
      headers: { "content-type": "text/plain; charset=utf-8" },
    });
  }
  return new Response(request.method === "HEAD" ? null : page.body, {
    status: 404,
    headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-store" },
  });
}
