#!/usr/bin/env node
// bun run identity [--out FILE | --dev] [--force]
//
// Makes the universe's own network identity (ADR 0013 §5): a fresh Ed25519 signing key and
// X25519 box key in tau-net's TAU_NET_IDENTITY form (the identity JSON, base64url-encoded),
// the value of the Worker secret UNIVERSE_IDENTITY. The universe relays visitors to web
// sub-taus that run on hubs under this identity, and hubs pin its keys at the first visit.
//
// The secret is never printed. It goes into a file of mode 0600 that you pipe into Wrangler:
//
//   --out FILE   write it to FILE (default: .universe-identity, gitignored), then run
//                  bunx wrangler secret put UNIVERSE_IDENTITY < .universe-identity
// --dev          write it to .dev.vars (gitignored, mode 0600) as UNIVERSE_IDENTITY=..., for
//                `bun run dev`
// --force        replace an identity that is already there. Hubs that pinned the old keys
//                drop the new identity's visits until their owner runs `tau net universe
//                leave` and `join` again, so keep the file (offline) rather than make a new one.
//
// Only the public keys are printed. Node runs cloud/shared's TypeScript directly (type
// stripping, Node 22.18 or newer); `bun install` has installed its dependency.

import { chmodSync, copyFileSync, existsSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { Identity } from "../../shared/net/identity.ts";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const NAME = "UNIVERSE_IDENTITY";
const usage = "Usage: bun run identity [--out FILE | --dev] [--force]";

let out = null;
let dev = false;
let force = false;
const argv = process.argv.slice(2);
for (let i = 0; i < argv.length; i++) {
  const arg = argv[i];
  if (arg === "--help" || arg === "-h") {
    console.log(usage);
    process.exit(0);
  } else if (arg === "--force") {
    force = true;
  } else if (arg === "--dev") {
    dev = true;
  } else if (arg === "--out" || arg.startsWith("--out=")) {
    out = arg === "--out" ? argv[++i] : arg.slice("--out=".length);
    if (!out) {
      console.error(`--out needs a file.\n${usage}`);
      process.exit(2);
    }
  } else {
    console.error(`Unknown option: ${arg}\n${usage}`);
    process.exit(2);
  }
}
if (dev && out !== null) {
  console.error(`--dev and --out do not go together.\n${usage}`);
  process.exit(2);
}

const SETS_NAME = new RegExp(`^\\s*${NAME}\\s*=`);

const identity = await Identity.generate();
const value = identity.toEnvValue();

if (dev) {
  const target = join(root, ".dev.vars");
  if (!existsSync(target)) copyFileSync(join(root, ".dev.vars.example"), target);
  const all = readFileSync(target, "utf8").split("\n");
  const lines = all.filter((line) => !SETS_NAME.test(line));
  if (lines.length !== all.length && !force) {
    console.error(`.dev.vars already sets ${NAME}; left unchanged. Pass --force to replace it.`);
    process.exit(1);
  }
  while (lines.length > 0 && lines.at(-1) === "") lines.pop();
  lines.push(`${NAME}=${value}`, "");
  writeFileSync(target, lines.join("\n"), { mode: 0o600 });
  chmodSync(target, 0o600);
  console.log(`Wrote ${NAME} to .dev.vars (mode 0600) for \`bun run dev\`.`);
} else {
  const target = resolve(root, out ?? ".universe-identity");
  if (existsSync(target) && !force) {
    console.error(`${target} already exists; left unchanged. Pass --force to replace it.`);
    process.exit(1);
  }
  writeFileSync(target, `${value}\n`, { mode: 0o600 });
  chmodSync(target, 0o600);
  const shown = out ?? ".universe-identity";
  console.log(`Wrote a new universe identity to ${shown} (mode 0600).`);
  console.log("It is the secret: never commit it, and keep a copy offline.");
  console.log("To give it to the deployed universe:\n");
  console.log(`  bunx wrangler secret put ${NAME} < ${shown}\n`);
}
console.log("Public keys (the universe's card shows them at /.well-known/tau.json):");
console.log(`  sign_key  ${identity.signKey}`);
console.log(`  box_key   ${identity.boxKey}`);
