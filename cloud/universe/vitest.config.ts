/**
 * The tests run the Worker, its Durable Object and its static assets in the Workers
 * runtime (Miniflare), with the configuration as it ships (wrangler.example.jsonc).
 *
 * Bindings set here win over wrangler.example.jsonc and over a developer's `.dev.vars`:
 * UNIVERSE is empty (the universe is the request host), insecure peers are off, and there is
 * no UNIVERSE_IDENTITY (the tests that need one pass their own).
 */

import { cloudflareTest } from "@cloudflare/vitest-pool-workers";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [
    cloudflareTest({
      wrangler: { configPath: "./wrangler.example.jsonc" },
      miniflare: {
        bindings: {
          UNIVERSE: "",
          ALLOW_INSECURE_PEERS: "0",
          UNIVERSE_IDENTITY: "",
        },
      },
    }),
  ],
  test: {
    include: ["test/*.test.ts"],
  },
});
