/**
 * The tau-universe Worker (ADR 0016): the server in front (src/server.ts) decides every
 * request, and vinext renders the pages of app/.
 *
 * Each page gets a fresh CSP nonce. The nonce goes into the request's policy, where vinext
 * reads it and puts it on every script and style it writes, and into the response's policy,
 * which the browser enforces. `vite dev` serves pages without the policy, because Vite's own
 * development scripts carry no nonce.
 *
 * Every export of this module is an entrypoint for the runtime, so it exports only the
 * handlers and the Durable Object classes.
 */

import vinext from "vinext/server/fetch-handler";
import { newNonce, pageSecurityPolicy, type RenderPage } from "../src/pages";
import { createUniverse } from "../src/server";

export { Directory } from "../src/directory";
export { Relay } from "../src/relay";

const renderWithVinext: RenderPage = async (request, target, env, ctx) => {
  const url = new URL(request.url);
  url.pathname = target.path;
  const headers = new Headers(request.headers);
  const policy = import.meta.env.DEV ? null : pageSecurityPolicy(newNonce());
  if (policy !== null) headers.set("content-security-policy", policy);
  // vinext renders GET; the server drops the body of a HEAD answer itself.
  const page = await vinext.fetch(new Request(url, { method: "GET", headers }), env, ctx);
  const response = new Response(page.body, page);
  if (policy !== null) response.headers.set("content-security-policy", policy);
  return response;
};

const universe = createUniverse(renderWithVinext);

/** `vite dev`: pages without a policy (the server would add the strict one). */
async function withoutPagePolicy(
  request: Request,
  env: Parameters<typeof universe.fetch>[1],
  ctx?: ExecutionContext,
): Promise<Response> {
  const response = await universe.fetch(request, env, ctx);
  if (!response.headers.get("content-type")?.startsWith("text/html")) return response;
  const open = new Response(response.body, response);
  open.headers.delete("content-security-policy");
  return open;
}

export default import.meta.env.DEV ? { ...universe, fetch: withoutPagePolicy } : universe;
