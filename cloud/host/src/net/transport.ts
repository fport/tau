/**
 * How a hosted tau reaches other taus and the universe: a `fetch` with two detours.
 *
 * - **This host.** A card or inbox of another tau on this same host (`<net host>/@<handle>/…`)
 *   is answered by this Worker's own handler, in the same invocation, with the same checks as
 *   a request from outside. A Worker cannot rely on reaching its own public host with a
 *   subrequest (and behind the universe it would go the long way round), so two hosted taus
 *   talk to each other without one.
 * - **The universe's Worker.** When the `UNIVERSE_SERVICE` binding exists, requests to the
 *   universe's host go through it: on tau.getporti.com the universe and tau-host share a
 *   zone, where a plain subrequest to the public host is not guaranteed to reach the
 *   universe Worker.
 *
 * Everything else is the global `fetch`, never following redirects (the caller says so).
 */

import { type HostEnv, optionalEnv } from "../env";
import { handle } from "../router";

export type Fetcher = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;

/** A fetch for the tau of `netHost` (null: no local detour) and the universe `universe`. */
export function netFetcher(env: HostEnv, netHost: string | null, universe: string | null): Fetcher {
  return async (input, init) => {
    const request = new Request(input, init);
    const url = new URL(request.url);
    if (netHost !== null && url.host === netHost && url.pathname.startsWith("/@")) {
      return handle(request, env);
    }
    const service = optionalEnv(env).UNIVERSE_SERVICE;
    if (service !== undefined && universe !== null && url.host === universe) {
      return service.fetch(request);
    }
    return fetch(request);
  };
}
