#!/usr/bin/env node
// pnpm run configure [--route HOST] [--client-id ID] [--signup open|LOGINS] [--force]
//
// Writes the gitignored `wrangler.jsonc` from wrangler.example.jsonc, and `.dev.vars` from
// .dev.vars.example when it is missing (with a fresh random VAULT_KEY for `wrangler dev`).
//
// --route HOST        serve tau-host on a custom domain: adds
//                       "routes": [{ "pattern": HOST, "custom_domain": true }]
//                     and sets PUBLIC_HOST to HOST (the zone must be on your Cloudflare account)
// --client-id ID      the client id of your GitHub OAuth App (GITHUB_CLIENT_ID)
// --signup VALUE      who may create an account: "open", or a comma list of GitHub logins
// --force             replace an existing wrangler.jsonc; its routes and vars are carried
//                     over unless given again, and the old file is kept as wrangler.jsonc.bak
//
// Secrets are never written here. For a deployment:
//   npx wrangler secret put GITHUB_CLIENT_SECRET
//   npx wrangler secret put VAULT_KEY          (32 random bytes, base64url)

import { randomBytes } from "node:crypto";
import { copyFileSync, existsSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const target = join(root, "wrangler.jsonc");
const devVars = join(root, ".dev.vars");
const HOST = /^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+$/;
const LOGIN = /^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$/;

const usage = "Usage: pnpm run configure [--route HOST] [--client-id ID] [--signup open|LOGINS] [--force]";
const options = { route: null, clientId: null, signup: null, force: false };
const argv = process.argv.slice(2);
for (let i = 0; i < argv.length; i++) {
  const arg = argv[i];
  const value = (name) => {
    const inline = arg.startsWith(`${name}=`) ? arg.slice(name.length + 1) : null;
    const next = inline ?? argv[++i];
    if (!next) {
      console.error(`${name} needs a value.\n${usage}`);
      process.exit(2);
    }
    return next;
  };
  if (arg === "--help" || arg === "-h") {
    console.log(usage);
    process.exit(0);
  } else if (arg === "--force") options.force = true;
  else if (arg === "--route" || arg.startsWith("--route=")) options.route = value("--route");
  else if (arg === "--client-id" || arg.startsWith("--client-id=")) options.clientId = value("--client-id");
  else if (arg === "--signup" || arg.startsWith("--signup=")) options.signup = value("--signup");
  else {
    console.error(`Unknown option: ${arg}\n${usage}`);
    process.exit(2);
  }
}

if (options.route !== null) {
  options.route = options.route.trim().toLowerCase().replace(/^https?:\/\//, "").replace(/\/+$/, "");
  if (!HOST.test(options.route)) {
    console.error(`Not a host name: ${options.route}`);
    process.exit(2);
  }
  if (options.route.endsWith(".workers.dev")) {
    console.error("A workers.dev host needs no route: leave --route out and the host is the request host.");
    process.exit(2);
  }
}
if (options.clientId !== null && !/^[A-Za-z0-9._-]{4,64}$/.test(options.clientId)) {
  console.error("That does not look like an OAuth App client id.");
  process.exit(2);
}
if (options.signup !== null) {
  const raw = options.signup.trim();
  const logins = raw.split(",").map((s) => s.trim()).filter(Boolean);
  if (raw !== "open" && !logins.every((login) => LOGIN.test(login))) {
    console.error('--signup takes "open" or a comma list of GitHub logins.');
    process.exit(2);
  }
  options.signup = raw === "open" ? "open" : logins.join(",");
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

function setVar(text, name, value) {
  const pattern = new RegExp(`"${name}": "[^"]*"`);
  if (!pattern.test(text)) throw new Error(`wrangler.example.jsonc has no ${name}`);
  return text.replace(pattern, `"${name}": ${JSON.stringify(value)}`);
}

let failed = false;

// 1. wrangler.jsonc
if (existsSync(target) && !options.force) {
  console.error(
    "wrangler.jsonc already exists; left unchanged. Pass --force to replace it " +
      "(its routes and vars are carried over unless you give them again).",
  );
  failed = true;
} else {
  let routes = [];
  const vars = { PUBLIC_HOST: "", GITHUB_CLIENT_ID: "", SIGNUP: "" };
  if (existsSync(target)) {
    try {
      const old = parseJsonc(readFileSync(target, "utf8"));
      if (Array.isArray(old.routes)) routes = old.routes;
      for (const name of Object.keys(vars)) vars[name] = old.vars?.[name] ?? "";
    } catch (err) {
      console.error(`Could not read the old wrangler.jsonc (${err.message}); nothing carried over.`);
    }
    copyFileSync(target, `${target}.bak`);
    console.log("Replacing wrangler.jsonc; the old one is wrangler.jsonc.bak.");
  }
  if (options.route !== null) {
    routes = [{ pattern: options.route, custom_domain: true }];
    vars.PUBLIC_HOST = options.route;
  }
  if (options.clientId !== null) vars.GITHUB_CLIENT_ID = options.clientId;
  if (options.signup !== null) vars.SIGNUP = options.signup;

  let text = readFileSync(join(root, "wrangler.example.jsonc"), "utf8");
  for (const [name, value] of Object.entries(vars)) text = setVar(text, name, value);
  if (routes.length > 0) {
    text = text.replace('  "dev": {', `  "routes": ${JSON.stringify(routes)},\n  "dev": {`);
  }
  parseJsonc(text); // Still valid.
  writeFileSync(target, text);
  const where = vars.PUBLIC_HOST ? ` for ${vars.PUBLIC_HOST}` : " (the host is the request host)";
  console.log(`Wrote wrangler.jsonc from wrangler.example.jsonc${where}.`);
  if (!vars.GITHUB_CLIENT_ID) console.log("GITHUB_CLIENT_ID is empty: GitHub sign-in stays off until you set it (--client-id).");
  if (!vars.SIGNUP) console.log('SIGNUP is empty: nobody can create an account until you set it (--signup open or --signup LOGIN).');
}

// 2. .dev.vars
if (existsSync(devVars)) {
  console.log(".dev.vars exists; left unchanged.");
} else {
  const example = readFileSync(join(root, ".dev.vars.example"), "utf8");
  const vaultKey = randomBytes(32).toString("base64url");
  writeFileSync(devVars, example.replace(/^VAULT_KEY=.*$/m, `VAULT_KEY=${vaultKey}`), { mode: 0o600 });
  console.log("Wrote .dev.vars (DEV_LOGIN=1, FAKE_PROVIDER=1, SIGNUP=open and a fresh VAULT_KEY for `wrangler dev`).");
}

// 3. Next steps
const steps = [
  "pnpm dev                                    # the host at http://127.0.0.1:8791 (development sign-in, fake provider)",
  "npx wrangler login                          # once, to deploy",
  "npx wrangler secret put GITHUB_CLIENT_SECRET",
  "npx wrangler secret put VAULT_KEY           # 32 random bytes, base64url; keep a copy offline",
  "pnpm run deploy                             # builds the app, deploys the Worker and its Durable Objects",
];
console.log(`\nNext steps:\n${steps.map((step) => `  - ${step}`).join("\n")}`);
process.exit(failed ? 1 : 0);
