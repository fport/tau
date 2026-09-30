/**
 * tau-host: a Worker that hosts taus (ADR 0013 §2, §4, §5). The routes are in src/router.ts.
 *
 * Every export of this module is an entrypoint for the runtime, so it exports only the
 * handler and the Durable Object classes.
 */

import type { HostEnv } from "./env";
import { handle } from "./router";

export { Accounts } from "./accounts";
export { Tau } from "./tau";

export default {
  fetch(request: Request, env: HostEnv): Promise<Response> {
    return handle(request, env);
  },
} satisfies ExportedHandler<HostEnv>;
