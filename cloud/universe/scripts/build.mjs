#!/usr/bin/env node
// bun run build   (also run by `wrangler dev`, `wrangler deploy` and `wrangler types`
// through the `build` section of the Wrangler configuration)
//
// Writes the gitignored public/static/, served at /static/ (`/app` belongs to tau-host,
// ADR 0013 §6):
//   landing.js     the landing page's hero: the universe on a canvas, opened through the portal
//   universe.js    the universe page (/universe): the full-page universe on the same canvas
//                  engine (client/painter.ts)
//   person.js      the person page (/@handle)
//   sub.js         the sub-tau page and its visitor chat (/<slug>, /@handle/<name>)
//   claim.js       the claim page (/claim#…)
//   how.js         how it works: the star field and the storyline's current station
//   sky.js         the star field alone, for the pages with no other script
//   chunks/        code the pages share (the character generator, the strings), and the
//                  development fixtures, which only localhost ever loads (client/api.ts)
//   theme.css      cloud/shared/theme.css: the tokens, fonts and primitives of the hard theme
//   fonts/         Chakra Petch, IBM Plex Sans and JetBrains Mono (latin, latin-ext) and their
//                  licences (cloud/shared/fonts.mjs), next to theme.css, whose @font-face URLs are
//                  relative

import { copyFileSync, mkdirSync, rmSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";
import { copyFonts } from "../../shared/fonts.mjs";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const out = join(root, "public", "static");
const shared = join(root, "..", "shared");

rmSync(out, { recursive: true, force: true });
mkdirSync(join(out, "fonts"), { recursive: true });

await build({
  entryPoints: ["landing", "universe", "person", "sub", "claim", "how", "sky"].map((name) => ({
    in: join(root, "client", `${name}.ts`),
    out: name,
  })),
  outdir: out,
  bundle: true,
  splitting: true,
  chunkNames: "chunks/[name]-[hash]",
  format: "esm",
  target: "es2022",
  minify: true,
  legalComments: "none",
  logLevel: "warning",
});

copyFileSync(join(shared, "theme.css"), join(out, "theme.css"));
copyFonts(join(out, "fonts"));

console.log("Built public/static/ (page scripts, theme.css, fonts).");
