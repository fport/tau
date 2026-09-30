/**
 * The shared modules run in two places, so every test runs in both:
 *
 * - `workerd`: the Workers runtime (Miniflare), where tau-host and the universe import them.
 *   It proves the modules use nothing but Web APIs (WebCrypto, TextEncoder, atob/btoa).
 * - `node`: Node's WebCrypto, where `bun run vectors` runs them to write the TypeScript
 *   vectors that tau-net checks (net/ts-vectors.json).
 *
 * The compatibility date is the newest the test runtime supports, the same as the Workers.
 */

import { cloudflareTest } from "@cloudflare/vitest-pool-workers";
import { defineConfig } from "vitest/config";

const include = ["**/*.test.ts"];
const exclude = ["**/node_modules/**", "**/.wrangler/**"];

export default defineConfig({
  test: {
    projects: [
      {
        plugins: [
          cloudflareTest({
            miniflare: { compatibilityDate: "2026-08-22", compatibilityFlags: [] },
          }),
        ],
        test: { name: "workerd", include, exclude },
      },
      {
        test: { name: "node", environment: "node", include, exclude },
      },
    ],
  },
});
