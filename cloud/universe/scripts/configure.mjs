#!/usr/bin/env node
// pnpm run configure [--route HOST] [--host-service NAME | --no-host-service] [--force]
//
// Writes the gitignored `wrangler.jsonc` from wrangler.example.jsonc, and `.dev.vars` from
// .dev.vars.example when it is missing.
//
// --route HOST          serve the universe on a custom domain: adds
//                         "routes": [{ "pattern": HOST, "custom_domain": true }]
//                       and sets UNIVERSE to HOST (the zone must be on your Cloudflare account)
// --host-service NAME   put tau-host behind the universe (ADR 0013 §6): adds the service
//                       binding "services": [{ "binding": "HOST", "service": NAME }], so the
//                       universe forwards /app, /auth/*, /api/host/* and hosted taus' cards
//                       and inboxes to the Worker NAME and can bind handles
// --no-host-service     drop a HOST binding carried over by --force
// --force               replace an existing wrangler.jsonc; its routes, UNIVERSE and HOST
//                       binding are carried over unless given again, and the old file is
//                       kept as wrangler.jsonc.bak

import { copyFileSync, existsSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const target = join(root, "wrangler.jsonc");
const devVars = join(root, ".dev.vars");
const HOST = /^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+$/;
const WORKER_NAME = /^[a-z0-9]([a-z0-9_-]{0,61}[a-z0-9])?$/;

const usage =
  "Usage: pnpm run configure [--route HOST] [--host-service NAME | --no-host-service] [--force]";
let route = null;
/** The tau-host Worker's name; null keeps what --force carries over, "" drops it. */
let hostService = null;
let force = false;
const argv = process.argv.slice(2);
for (let i = 0; i < argv.length; i++) {
  const arg = argv[i];
  if (arg === "--help" || arg === "-h") {
    console.log(usage);
    process.exit(0);
  } else if (arg === "--force") {
    force = true;
  } else if (arg === "--no-host-service") {
    hostService = "";
  } else if (arg === "--host-service" || arg.startsWith("--host-service=")) {
    hostService = arg === "--host-service" ? argv[++i] : arg.slice("--host-service=".length);
    if (!hostService || !WORKER_NAME.test(hostService)) {
      console.error(`--host-service needs a Worker name (e.g. tau-host).\n${usage}`);
      process.exit(2);
    }
  } else if (arg === "--route" || arg.startsWith("--route=")) {
    route = arg === "--route" ? argv[++i] : arg.slice("--route=".length);
    if (!route) {
      console.error(`--route needs a host.\n${usage}`);
      process.exit(2);
    }
  } else {
    console.error(`Unknown option: ${arg}\n${usage}`);
    process.exit(2);
  }
}

if (route !== null) {
  route = route
    .trim()
    .toLowerCase()
    .replace(/^https?:\/\//, "")
    .replace(/\/+$/, "");
  if (!HOST.test(route)) {
    console.error(`Not a host name: ${route}`);
    process.exit(2);
  }
  if (route.endsWith(".workers.dev")) {
    console.error(
      "A workers.dev host needs no route: leave --route out and the universe is its request host.",
    );
    process.exit(2);
  }
}

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

/** Puts routes, UNIVERSE and the service bindings into the example text. */
function apply(text, routes, universe, services) {
  if (universe) text = text.replace('"UNIVERSE": ""', `"UNIVERSE": ${JSON.stringify(universe)}`);
  if (routes.length > 0) {
    text = text.replace(
      '  "triggers": {',
      `  "routes": ${JSON.stringify(routes)},\n  "triggers": {`,
    );
  }
  if (services.length > 0) {
    text = text.replace(
      '  "triggers": {',
      `  "services": ${JSON.stringify(services)},\n  "triggers": {`,
    );
  }
  parseJsonc(text); // Still valid.
  return text;
}

let failed = false;

// 1. wrangler.jsonc
if (existsSync(target) && !force) {
  console.error(
    "wrangler.jsonc already exists; left unchanged. Pass --force to replace it " +
      "(its routes and UNIVERSE are carried over unless you give --route).",
  );
  failed = true;
} else {
  let routes = [];
  let universe = "";
  let services = [];
  let old = null;
  if (existsSync(target)) {
    try {
      old = parseJsonc(readFileSync(target, "utf8"));
    } catch (err) {
      console.error(
        `Could not read the old wrangler.jsonc (${err.message}); nothing carried over.`,
      );
    }
  }
  if (route !== null) {
    routes = [{ pattern: route, custom_domain: true }];
    universe = route;
  } else if (old !== null) {
    if (Array.isArray(old.routes)) routes = old.routes;
    universe = old.vars?.UNIVERSE ?? "";
  }
  if (hostService) {
    services = [{ binding: "HOST", service: hostService }];
  } else if (hostService === null && old !== null && Array.isArray(old.services)) {
    services = old.services.filter((service) => service?.binding === "HOST");
  }
  if (existsSync(target)) {
    copyFileSync(target, `${target}.bak`);
    console.log("Replaced wrangler.jsonc; the old one is wrangler.jsonc.bak.");
  }
  writeFileSync(
    target,
    apply(readFileSync(join(root, "wrangler.example.jsonc"), "utf8"), routes, universe, services),
  );
  const where = universe ? ` for ${universe}` : " (the universe is the request host)";
  console.log(`Wrote wrangler.jsonc from wrangler.example.jsonc${where}.`);
  if (services.length > 0) {
    console.log(
      `tau-host is the Worker "${services[0].service}" (HOST binding); deploy it before the universe.`,
    );
  }
}

// 2. .dev.vars
if (existsSync(devVars)) {
  console.log(".dev.vars exists; left unchanged.");
} else {
  copyFileSync(join(root, ".dev.vars.example"), devVars);
  console.log("Wrote .dev.vars (ALLOW_INSECURE_PEERS=1 for `wrangler dev`).");
}

// 3. Next steps
const steps = [
  "pnpm dev                        # the site and the API at http://127.0.0.1:8790",
  "npx wrangler login              # once, to deploy",
  "pnpm run deploy                 # builds the page script, deploys the Worker and its Durable Object",
];
console.log(`\nNext steps:\n${steps.map((step) => `  - ${step}`).join("\n")}`);
process.exit(failed ? 1 : 0);
