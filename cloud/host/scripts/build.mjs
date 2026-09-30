#!/usr/bin/env node
// pnpm run build   (also run by `wrangler dev`, `wrangler deploy` and `wrangler types`
// through the `build` section of the Wrangler configuration)
//
// Writes the gitignored public/app/assets/:
//   app.js      client/app.ts bundled: the owner's app
//   visit.js    client/visit.ts bundled: the chat page of a web sub-tau
//   host.css    client/host.css
//   theme.css   the shared theme, cloud/shared/theme.css, when it exists; else tau-host's own
//               tokens (client/theme-fallback.css) with the same names
//
// Characters: the scripts import `tau-character`. The shared generator,
// cloud/shared/character.ts (`character(seed, opts) → SVG`), is bundled when it exists;
// else the placeholder client/character-placeholder.ts with the same signature. No CDN:
// the pages' CSP only allows scripts from the host itself.

import { copyFileSync, existsSync, mkdirSync, rmSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const client = join(root, "client");
const out = join(root, "public", "app", "assets");
const shared = join(root, "..", "shared");

const sharedCharacter = join(shared, "character.ts");
const character = existsSync(sharedCharacter) ? sharedCharacter : join(client, "character-placeholder.ts");
const sharedTheme = join(shared, "theme.css");
const theme = existsSync(sharedTheme) ? sharedTheme : join(client, "theme-fallback.css");

rmSync(out, { recursive: true, force: true });
mkdirSync(out, { recursive: true });

const characterAlias = {
  name: "tau-character",
  setup(builder) {
    builder.onResolve({ filter: /^tau-character$/ }, () => ({ path: character }));
  },
};

await build({
  entryPoints: { app: join(client, "app.ts"), visit: join(client, "visit.ts") },
  outdir: out,
  bundle: true,
  format: "esm",
  target: "es2022",
  minify: true,
  legalComments: "none",
  plugins: [characterAlias],
  logLevel: "warning",
});

copyFileSync(join(client, "host.css"), join(out, "host.css"));
copyFileSync(theme, join(out, "theme.css"));

const from = (path) => path.slice(join(root, "..").length + 1);
console.log(`Built public/app/assets/ (app.js, visit.js, host.css; theme from ${from(theme)}, character from ${from(character)}).`);
