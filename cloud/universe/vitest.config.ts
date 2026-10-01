/**
 * Two runs, both in the Workers runtime (Miniflare):
 *
 * - `server`: the server of src/server.ts with a stand-in page renderer (test/worker.ts), its
 *   Durable Objects and the static assets of public/, with the configuration as it ships
 *   (wrangler.example.jsonc).
 * - `site`: the built Worker (`bun run build` first, dist/server/), so the rendered pages are
 *   checked as they ship: their words, their nonces, their routes. The build may come from the
 *   owner's own configuration; the bindings below win over it.
 *
 * Bindings set here win over wrangler.example.jsonc and over a developer's `.dev.vars`:
 * UNIVERSE is empty (the universe is the request host), insecure peers are off, and there is
 * no UNIVERSE_IDENTITY (the tests that need one pass their own).
 */

import { cloudflareTest } from "@cloudflare/vitest-pool-workers";
import { defineConfig } from "vitest/config";

const bindings = {
  UNIVERSE: "",
  ALLOW_INSECURE_PEERS: "0",
  UNIVERSE_IDENTITY: "",
};

export default defineConfig({
  test: {
    projects: [
      {
        plugins: [
          cloudflareTest({
            main: "./test/worker.ts",
            wrangler: { configPath: "./wrangler.example.jsonc" },
            miniflare: { bindings },
          }),
        ],
        test: { name: "server", include: ["test/*.test.ts"], exclude: ["test/site.test.ts"] },
      },
      {
        plugins: [
          cloudflareTest({
            wrangler: { configPath: "./dist/server/wrangler.json" },
            miniflare: {
              bindings,
              // A build from the owner's own configuration binds tau-host; its paths are not
              // part of these tests.
              serviceBindings: {
                HOST: () => new Response("tau-host is not part of these tests", { status: 502 }),
              },
            },
          }),
        ],
        test: { name: "site", include: ["test/site.test.ts"] },
      },
    ],
  },
});
