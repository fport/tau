/**
 * The tests run the Worker, its Durable Objects and its static assets in the Workers runtime
 * (Miniflare), with the configuration as it ships (wrangler.example.jsonc).
 *
 * Bindings set here win over wrangler.example.jsonc and over a developer's `.dev.vars`. The
 * secrets are test values: VAULT_KEY is the bytes 0x00..0x1f, and GitHub is always a fetch
 * mock. DEV_LOGIN and FAKE_PROVIDER are on so the tests can sign in without GitHub and run
 * turns on the scripted provider; the tests that need them off pass their own env.
 */

import { cloudflareTest } from "@cloudflare/vitest-pool-workers";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [
    cloudflareTest({
      wrangler: { configPath: "./wrangler.example.jsonc" },
      miniflare: {
        bindings: {
          GITHUB_CLIENT_ID: "test-client-id",
          GITHUB_CLIENT_SECRET: "test-client-secret",
          VAULT_KEY: "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8",
          SIGNUP: "open",
          PUBLIC_HOST: "",
          DEV_LOGIN: "1",
          FAKE_PROVIDER: "1",
        },
      },
    }),
  ],
  server: {
    // The freshness test imports tau-core's templates with `?raw`.
    fs: { allow: ["../.."] },
  },
  test: {
    include: ["test/*.test.ts"],
  },
});
