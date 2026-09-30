#!/usr/bin/env node
// pnpm run build   (also run by `wrangler dev`, `wrangler deploy` and `wrangler types`
// through the `build` section of the Wrangler configuration)
//
// Writes the gitignored public/app/:
//   universe.js    client/universe.ts bundled with d3-force and d3-polygon (no CDN: the
//                  pages' CSP only allows scripts from the site itself)
//   fonts/         the Jost variable font (latin, latin-ext) and its licence

import { copyFileSync, mkdirSync, rmSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const out = join(root, "public", "app");
const fontSource = join(root, "node_modules", "@fontsource-variable", "jost");

rmSync(out, { recursive: true, force: true });
mkdirSync(join(out, "fonts"), { recursive: true });

await build({
  entryPoints: [join(root, "client", "universe.ts")],
  outfile: join(out, "universe.js"),
  bundle: true,
  format: "esm",
  target: "es2022",
  minify: true,
  legalComments: "none",
  banner: {
    js: "/*! tau universe page. Includes d3-force and d3-polygon, ISC License, Copyright 2010-2021 Mike Bostock. */",
  },
  logLevel: "warning",
});

for (const subset of ["latin", "latin-ext"]) {
  const file = `jost-${subset}-wght-normal.woff2`;
  copyFileSync(join(fontSource, "files", file), join(out, "fonts", file));
}
copyFileSync(join(fontSource, "LICENSE"), join(out, "fonts", "OFL.txt"));

console.log("Built public/app/ (universe.js, fonts).");
