/**
 * tau spine: the Worker behind a tau's address.
 *
 * Contract: docs/reference/tau-network.md (§1–§5). Decision: docs/adr/0007.
 *
 *   GET  /                        plain text "tau spine <address>"
 *   GET  /.well-known/tau.json    the card
 *   POST /net/inbox               signed envelopes from other taus
 *   *    /hub/*                   the owner's hub (bearer token)
 *
 * The cron prunes the mailbox and the replay guard, and in cloud mode keeps the brain awake.
 *
 * Every export of this module is an entrypoint for the runtime, so it exports only the
 * handler and the Durable Object classes.
 */

import { ownAddress } from "./address";
import { runCron } from "./cron";
import type { SpineEnv } from "./env";
import { handleHub } from "./hub";
import { error, methodNotAllowed, notFound } from "./http";
import { receiveEnvelope, serveCard } from "./net";

export { TauBrain } from "./brain";
export { HubSignal } from "./signal";

async function route(request: Request, env: SpineEnv): Promise<Response> {
  const url = new URL(request.url);
  const path = url.pathname;
  if (path === "/") {
    if (request.method !== "GET" && request.method !== "HEAD") return methodNotAllowed(["GET"]);
    return new Response(`tau spine ${ownAddress(env, url)}`, {
      headers: { "content-type": "text/plain; charset=utf-8" },
    });
  }
  if (path === "/.well-known/tau.json") {
    if (request.method !== "GET" && request.method !== "HEAD") return methodNotAllowed(["GET"]);
    return serveCard(env, url);
  }
  if (path === "/net/inbox") {
    if (request.method !== "POST") return methodNotAllowed(["POST"]);
    return receiveEnvelope(request, env, url);
  }
  if (path === "/hub" || path.startsWith("/hub/")) return handleHub(request, env, url);
  return notFound();
}

export default {
  async fetch(request: Request, env: SpineEnv): Promise<Response> {
    try {
      return await route(request, env);
    } catch (err) {
      const path = new URL(request.url).pathname;
      console.error(JSON.stringify({ event: "unhandled", path, error: String(err) }));
      return error(500, "internal");
    }
  },

  async scheduled(_controller: ScheduledController, env: SpineEnv): Promise<void> {
    await runCron(env);
  },
} satisfies ExportedHandler<SpineEnv>;
