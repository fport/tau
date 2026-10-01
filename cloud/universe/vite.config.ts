/**
 * The Worker's build (ADR 0016): vinext renders the pages of app/, and the Cloudflare plugin
 * builds worker/index.ts, the server in front, into dist/server/, with the static files and
 * the pages' bundles in dist/client/. `wrangler deploy` deploys that build.
 *
 * The configuration is the owner's own `wrangler.jsonc` (`bun run configure`), or without it
 * the one as it ships.
 */

import { existsSync } from "node:fs";
import { cloudflare } from "@cloudflare/vite-plugin";
import vinext from "vinext";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [
    vinext(),
    cloudflare({
      configPath: existsSync("wrangler.jsonc") ? "wrangler.jsonc" : "wrangler.example.jsonc",
      viteEnvironment: { name: "rsc", childEnvironments: ["ssr"] },
    }),
  ],
});
