/**
 * Two test projects run the same Worker in the Workers runtime (Miniflare):
 *
 * - `local`: the local-mode configuration as it ships (TAU_MODE=local).
 * - `cloud`: the same configuration with TAU_MODE=cloud, for the store routes. It has no
 *   BRAIN binding: containers need Docker, which the tests never touch.
 *
 * Bindings set here win over wrangler.example.jsonc and over a developer's `.dev.vars`.
 */

import { cloudflareTest, readD1Migrations } from "@cloudflare/vitest-pool-workers";
import { defineConfig } from "vitest/config";

export const TEST_HUB_TOKEN = "test-hub-token";

export default defineConfig(async () => {
  const migrations = await readD1Migrations("migrations");

  const project = (name: "local" | "cloud", include: string[]) => ({
    plugins: [
      cloudflareTest({
        wrangler: { configPath: "./wrangler.example.jsonc" },
        miniflare: {
          bindings: {
            TEST_MIGRATIONS: migrations,
            TAU_MODE: name,
            ADDRESS: "",
            ALLOW_INSECURE_PEERS: "0",
            KEEP_AWAKE: "1",
            HUB_TOKEN: TEST_HUB_TOKEN,
          },
        },
      }),
    ],
    test: {
      name,
      include,
      setupFiles: ["./test/setup.ts"],
    },
  });

  return {
    test: {
      projects: [project("local", ["test/*.test.ts"]), project("cloud", ["test/cloud/*.test.ts"])],
    },
  };
});
