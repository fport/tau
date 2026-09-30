#!/usr/bin/env node
// node scripts/gallery.mjs [--count N] [--seed PREFIX]
//
// Development only: writes a gallery of sigils (cloud/shared/character.ts) to
// .gallery/index.html, with the theme and the web fonts next to it, so the sigils can be
// looked at and screenshot side by side. Nothing here is built into the site or deployed:
// .gallery/ lies outside public/ and ignores itself (it writes its own `.gitignore`).
//
// The page shows every hue, the detail levels at graph and icon sizes, and then taus, each
// followed by its sub-taus (which burn in their tau's hue).
//
// Node 24 runs the TypeScript generator directly (type stripping).

import { copyFileSync, mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { character, describe, HUES, traits } from "../../shared/character.ts";
import { copyFonts } from "../../shared/fonts.mjs";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const out = join(root, ".gallery");

const argv = process.argv.slice(2);
const option = (name, fallback) => {
  const index = argv.indexOf(name);
  return index === -1 ? fallback : argv[index + 1];
};
const count = Math.max(1, Math.min(400, Number(option("--count", "48")) || 48));
const prefix = option("--seed", "");

const TAUS = [
  "alice.example.com",
  "bob.example.net",
  "tau.example.com/@carol",
  "dave.example.org",
  "tau.example.com/@erin",
  "frank.example.com",
  "127.0.0.1:8787",
  "tau.example.com/@grace",
  "heidi.example.com",
  "ivan.example.net",
  "tau.example.com/@judy",
  "mallory.example.org",
];
const SUBS = ["coach", "landing", "arm", "chef", "tutor", "scout", "poet", "critic"];

/** Seeds like the site's: each tau address, then two or three of its sub-taus. */
function seeds() {
  const list = [];
  if (prefix !== "") {
    for (let i = 0; i < count; i++) list.push(`${prefix}${i}`);
    return list;
  }
  for (let i = 0; list.length < count; i++) {
    const round = Math.floor(i / TAUS.length);
    const tau = round === 0 ? TAUS[i % TAUS.length] : `r${round}.${TAUS[i % TAUS.length]}`;
    list.push(tau);
    for (let j = 0; j < 1 + (i % 3); j++) list.push(`${tau}/${SUBS[(i + j) % SUBS.length]}`);
  }
  return list.slice(0, count);
}

const escape = (text) =>
  text.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");

const cells = seeds()
  .map((seed) => {
    const t = traits(seed);
    const facts = [
      t.kind,
      t.hue,
      t.frame,
      t.second === "none" ? "" : t.second,
      `${t.tongues}×flame`,
      `h${t.height}`,
      t.ticks > 0 ? `${t.ticks} ticks` : "",
      t.floor ? "floor" : "",
    ]
      .filter(Boolean)
      .join(" · ");
    return `<figure class="cell cell-${t.kind}">${character(seed, { size: 120 })}<figcaption><code>${escape(seed)}</code><span>${escape(facts)}</span></figcaption></figure>`;
  })
  .join("\n");

/** One tau of each hue, so the family can be seen at once. */
const family = HUES.map((hue) => {
  for (let i = 0; i < 4000; i++) {
    const seed = `hue-${i}.example.com`;
    if (traits(seed).hue === hue.name) {
      return `<figure class="hue">${character(seed, { size: 96 })}<figcaption>${escape(hue.word)}</figcaption></figure>`;
    }
  }
  return "";
}).join("");

const sizes = [16, 24, 32, 48, 64, 96, 160]
  .map(
    (size) =>
      `<figure class="size">${character("alice.example.com", { size, label: `tau at ${size} px` })}` +
      `${character("alice.example.com/coach", { size, label: `sub-tau at ${size} px` })}<figcaption>${size}px</figcaption></figure>`,
  )
  .join("");

const page = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>tau sigils</title>
<link rel="stylesheet" href="theme.css">
<link rel="stylesheet" href="gallery.css">
</head>
<body class="grid-bg">
<main>
<p class="kicker kicker-accent">dev only · cloud/shared/character.ts</p>
<h1 class="chrome">Ember sigils</h1>
<p class="lead">${count} seeds. Each is deterministic: the same seed draws the same sigil in the site and in tau-host. A tau carries a second triangle and a ring; its sub-taus follow it with a single flame in its hue. The first one's label: <em>${escape(describe(traits("alice.example.com")))}</em>.</p>
<h2 class="kicker">Hues</h2>
<section class="family" aria-label="Hues">${family}</section>
<h2 class="kicker">Sizes (tau and sub-tau)</h2>
<section class="sizes" aria-label="Sizes">${sizes}</section>
<h2 class="kicker">Taus and their sub-taus</h2>
<section class="cells">
${cells}
</section>
</main>
</body>
</html>
`;

const css = `main { max-width: 84rem; margin: 0 auto; padding: 2rem 1rem 4rem; }
h1 { font-size: 3rem; margin: .5rem 0; }
h2.kicker { margin: 1.75rem 0 .75rem; }
.lead { max-width: 48rem; color: var(--muted); margin-bottom: 1rem; }
.family, .sizes { display: flex; flex-wrap: wrap; align-items: flex-end; gap: 1.25rem; padding: 1rem; border: 1px solid var(--line); background: var(--bg); }
.hue, .size { display: grid; justify-items: center; gap: .35rem; margin: 0; }
.size { grid-auto-flow: column; align-items: end; }
.size figcaption { grid-column: 1 / span 2; }
.hue figcaption, .size figcaption { color: var(--muted); font-family: var(--font-mono); font-size: .7rem; letter-spacing: .1em; text-transform: uppercase; }
.cells { display: grid; grid-template-columns: repeat(auto-fill, minmax(10.5rem, 1fr)); gap: 0.5rem; }
.cell { display: grid; justify-items: center; gap: .4rem; margin: 0; padding: 1rem .5rem .8rem; border: 1px solid var(--line); background: var(--bg); }
.cell-tau { border-color: var(--line-2); }
.cell figcaption { display: grid; gap: .2rem; text-align: center; font-size: .72rem; color: var(--muted); }
.cell code { white-space: normal; overflow-wrap: anywhere; font-size: .7rem; }
`;

mkdirSync(out, { recursive: true });
writeFileSync(join(out, ".gitignore"), "# Generated by scripts/gallery.mjs; never tracked.\n*\n");
copyFileSync(join(root, "..", "shared", "theme.css"), join(out, "theme.css"));
copyFonts(join(out, "fonts"));
writeFileSync(join(out, "gallery.css"), css);
writeFileSync(join(out, "index.html"), page);
console.log(`Wrote ${join(out, "index.html")} (${count} sigils).`);
