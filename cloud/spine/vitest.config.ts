/**
 * Two test projects run the same Worker in the Workers runtime (Miniflare), both from
 * wrangler.example.jsonc:
 *
 * - `local`: the local-mode configuration as it ships (TAU_MODE=local). It has no D1
 *   database at all: KV, the Mailbox Durable Object and the cron are everything local mode
 *   needs.
 * - `cloud`: the same configuration with TAU_MODE=cloud plus the D1 database `DB` of the
 *   cloud configuration, for the store routes. It has no BRAIN binding: containers need
 *   Docker, which the tests never touch.
 *
 * Bindings set here win over wrangler.example.jsonc and over a developer's `.dev.vars`.
 */

import { cloudflareTest, readD1Migrations } from "@cloudflare/vitest-pool-workers";
import { defineConfig } from "vitest/config";

export const TEST_HUB_TOKEN = "test-hub-token";

export default defineConfig(async () => {
  const migrations = await readD1Migrations("migrations");

  const bindings = (mode: "local" | "cloud") => ({
    TAU_MODE: mode,
    ADDRESS: "",
    ALLOW_INSECURE_PEERS: "0",
    KEEP_AWAKE: "1",
    HUB_TOKEN: TEST_HUB_TOKEN,
  });

  const local = {
    plugins: [
      cloudflareTest({
        wrangler: { configPath: "./wrangler.example.jsonc" },
        miniflare: { bindings: bindings("local") },
      }),
    ],
    test: { name: "local", include: ["test/*.test.ts"] },
  };

  const cloud = {
    plugins: [
      cloudflareTest({
        wrangler: { configPath: "./wrangler.example.jsonc" },
        miniflare: {
          d1Databases: { DB: "tau-spine" },
          bindings: { ...bindings("cloud"), TEST_MIGRATIONS: migrations },
        },
      }),
    ],
    test: {
      name: "cloud",
      include: ["test/cloud/*.test.ts"],
      setupFiles: ["./test/cloud/setup.ts"],
    },
  };

  return { test: { projects: [local, cloud] } };
});
