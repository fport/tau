#!/usr/bin/env node
// bun run configure [--cloud] [--force]
// node scripts/configure.mjs --check-cloud    (run by `bun run deploy:cloud`)
//
// Writes the gitignored `wrangler.jsonc` from wrangler.example.jsonc (local mode) or
// wrangler.cloud.example.jsonc (--cloud), and creates `.dev.vars` with a random HUB_TOKEN
// when it is missing. The token is never printed.
//
// With --force an existing wrangler.jsonc is replaced; the ids Wrangler provisioned (KV,
// and in cloud mode D1 and R2), ADDRESS, SPINE_URL and routes are carried over, and the old
// file is kept as wrangler.jsonc.bak.

import { randomBytes } from "node:crypto";
import { copyFileSync, existsSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const args = new Set(process.argv.slice(2));
for (const arg of args) {
  if (!["--cloud", "--force", "--check-cloud", "--help", "-h"].includes(arg)) {
    console.error(`Unknown option: ${arg}`);
    process.exit(2);
  }
}
if (args.has("--help") || args.has("-h")) {
  console.log("Usage: bun run configure [--cloud] [--force]");
  process.exit(0);
}

const cloud = args.has("--cloud");
const force = args.has("--force");
const example = cloud ? "wrangler.cloud.example.jsonc" : "wrangler.example.jsonc";
const target = join(root, "wrangler.jsonc");
const devVars = join(root, ".dev.vars");
let failed = false;

/** JSONC to JSON: drops comments and trailing commas outside strings. */
function parseJsonc(text) {
  let out = "";
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (c === '"') {
      let j = i + 1;
      while (j < text.length && text[j] !== '"') j += text[j] === "\\" ? 2 : 1;
      out += text.slice(i, j + 1);
      i = j;
    } else if (c === "/" && text[i + 1] === "/") {
      while (i < text.length && text[i] !== "\n") i++;
      out += "\n";
    } else if (c === "/" && text[i + 1] === "*") {
      i = text.indexOf("*/", i + 2) + 1;
      if (i === 0) break;
    } else {
      out += c;
    }
  }
  return JSON.parse(out.replace(/,(\s*[}\]])/g, "$1"));
}

/** Carries the values Wrangler and the owner added from `old` into the example text. */
function carryOver(text, old) {
  const kept = [];
  const notes = [];
  const kvId = old.kv_namespaces?.find((kv) => kv.binding === "TAU")?.id;
  if (kvId) {
    text = text.replace(
      '{ "binding": "TAU" }',
      `{ "binding": "TAU", "id": ${JSON.stringify(kvId)} }`,
    );
    kept.push("KV namespace id");
  }
  // Only the cloud configuration has a D1 database. Going back to local mode drops the
  // binding; the database itself stays in the account.
  const d1Id = old.d1_databases?.find((db) => db.binding === "DB")?.database_id;
  if (d1Id && text.includes('"database_name": "tau-spine",')) {
    text = text.replace(
      '"database_name": "tau-spine",',
      `"database_name": "tau-spine",\n      "database_id": ${JSON.stringify(d1Id)},`,
    );
    kept.push("D1 database id");
  } else if (d1Id) {
    notes.push(
      "The local-mode config binds no D1 database. The cloud store (state, sessions) stays " +
        "in your account as the D1 database tau-spine until you delete it.",
    );
  }
  const bucket = old.r2_buckets?.find((r2) => r2.binding === "MEDIA")?.bucket_name;
  if (bucket && text.includes('{ "binding": "MEDIA" }')) {
    text = text.replace(
      '{ "binding": "MEDIA" }',
      `{ "binding": "MEDIA", "bucket_name": ${JSON.stringify(bucket)} }`,
    );
    kept.push("R2 bucket name");
  }
  for (const name of ["ADDRESS", "SPINE_URL"]) {
    const value = old.vars?.[name];
    if (value && text.includes(`"${name}": ""`)) {
      text = text.replace(`"${name}": ""`, `"${name}": ${JSON.stringify(value)}`);
      kept.push(name);
    }
  }
  if (Array.isArray(old.routes) && old.routes.length > 0) {
    text = text.replace(
      '  "triggers": {',
      `  "routes": ${JSON.stringify(old.routes)},\n  "triggers": {`,
    );
    kept.push("routes");
  }
  parseJsonc(text); // Still valid.
  return { text, kept, notes };
}

// --check-cloud: refuse a cloud deploy that would give the brain no way back to its spine.
if (args.has("--check-cloud")) {
  if (!existsSync(target)) {
    console.error("No wrangler.jsonc; run `bun run configure --cloud` first.");
    process.exit(1);
  }
  const config = parseJsonc(readFileSync(target, "utf8"));
  const problems = [];
  if (config.vars?.TAU_MODE !== "cloud") problems.push('vars.TAU_MODE is not "cloud"');
  if (!config.containers?.some((c) => c.class_name === "TauBrain")) {
    problems.push("the TauBrain container is missing");
  }
  if (!config.vars?.SPINE_URL && !config.vars?.ADDRESS) {
    problems.push("set vars.SPINE_URL to your deployed URL (or vars.ADDRESS)");
  }
  if (problems.length > 0) {
    console.error(`wrangler.jsonc is not ready for cloud mode:\n  - ${problems.join("\n  - ")}`);
    console.error('See README.md, "Cloud mode".');
    process.exit(1);
  }
  process.exit(0);
}

// 1. wrangler.jsonc
if (existsSync(target) && !force) {
  let mode = "unknown";
  try {
    mode = parseJsonc(readFileSync(target, "utf8")).vars?.TAU_MODE ?? "local";
  } catch {
    // Reported as unknown.
  }
  console.error(
    `wrangler.jsonc already exists (${mode} mode); left unchanged. ` +
      "Pass --force to replace it (provisioned ids are carried over).",
  );
  failed = true;
} else {
  let text = readFileSync(join(root, example), "utf8");
  let kept = [];
  let notes = [];
  if (existsSync(target)) {
    const oldText = readFileSync(target, "utf8");
    copyFileSync(target, `${target}.bak`);
    try {
      ({ text, kept, notes } = carryOver(text, parseJsonc(oldText)));
    } catch (err) {
      console.error(
        `Could not read the old wrangler.jsonc (${err.message}); nothing carried over.`,
      );
    }
    console.log("Replaced wrangler.jsonc; the old one is wrangler.jsonc.bak.");
    if (kept.length > 0) console.log(`Carried over: ${kept.join(", ")}.`);
    for (const note of notes) console.log(note);
  }
  writeFileSync(target, text);
  console.log(`Wrote wrangler.jsonc from ${example} (${cloud ? "cloud" : "local"} mode).`);
}

// 2. .dev.vars
if (existsSync(devVars)) {
  console.log(".dev.vars exists; left unchanged.");
} else {
  const token = randomBytes(32).toString("base64url");
  const text = readFileSync(join(root, ".dev.vars.example"), "utf8").replace(
    /^HUB_TOKEN=.*$/m,
    `HUB_TOKEN=${token}`,
  );
  writeFileSync(devVars, text, { mode: 0o600 });
  console.log(
    "Wrote .dev.vars with a random HUB_TOKEN for `wrangler dev` (cloud/spine/.dev.vars).\n" +
      "The hub needs the same value as TAU_SPINE_TOKEN in its .env; copy it from there.",
  );
}

// 3. Next steps
const steps = cloud
  ? [
      "Set SPINE_URL in wrangler.jsonc to your deployed URL (https://tau-spine.<subdomain>.workers.dev).",
      "Start Docker; the brain image is built on deploy.",
      "bunx wrangler login",
      "bun run deploy:cloud",
      "bunx wrangler secret put HUB_TOKEN  # and the model / Telegram secrets, see README.md",
      "tau cloud push                      # from the hub machine, with TAU_SPINE_URL and TAU_SPINE_TOKEN set",
    ]
  : [
      "bun run dev                         # local spine at http://127.0.0.1:8787",
      "Hub .env: TAU_SPINE_URL=http://127.0.0.1:8787, TAU_SPINE_TOKEN=<HUB_TOKEN from .dev.vars>",
      "To deploy: bunx wrangler login, bun run deploy, bunx wrangler secret put HUB_TOKEN",
    ];
console.log(`\nNext steps:\n${steps.map((step) => `  - ${step}`).join("\n")}`);
process.exit(failed ? 1 : 0);
