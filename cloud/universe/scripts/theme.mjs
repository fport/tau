#!/usr/bin/env node
// node scripts/theme.mjs   (the first step of `bun run build` and `bun run dev`)
//
// Writes the gitignored public/static/, served at /static/ (`/app` belongs to tau-host,
// ADR 0013 §6). Vite copies public/ into the build as it is.
//   theme.css      cloud/shared/theme.css: the tokens, fonts and primitives of the hard theme
//   fonts/         Chakra Petch, IBM Plex Sans and JetBrains Mono (latin, latin-ext) and their
//                  licences (cloud/shared/fonts.mjs), next to theme.css, whose @font-face URLs
//                  are relative
//
// The pages and their scripts are built by Vite (vite.config.ts, ADR 0016).

import { copyFileSync, mkdirSync, rmSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { copyFonts } from "../../shared/fonts.mjs";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const out = join(root, "public", "static");
const shared = join(root, "..", "shared");

rmSync(out, { recursive: true, force: true });
mkdirSync(join(out, "fonts"), { recursive: true });

copyFileSync(join(shared, "theme.css"), join(out, "theme.css"));
copyFonts(join(out, "fonts"));

console.log("Wrote public/static/ (theme.css, fonts).");
