#!/usr/bin/env node
// Signs, seals and posts one envelope to a spine's inbox (docs/reference/tau-network.md §3).
// A development tool: it plays the sending hub, so two local spines (or a spine and a hub)
// can be tested without a second tau.
//
//   node scripts/send-dev-envelope.mjs --to 127.0.0.1:8788 --from 127.0.0.1:8787 \
//       [--kind message|contact_request|contact_accept] [--text "hello"] [--name "Dev tau"] \
//       [--identity path/to/identity.json] [--print]
//
// Keys: --identity (the {"v":1,"sign_seed","box_seed"} file of `tau net init`), else
// TAU_NET_IDENTITY (the same JSON, base64url), else the public §3 test-vector seeds.
// The sender's spine must serve a card with the matching sign_key, or the recipient
// answers 403 bad_signature (or 502 when it cannot fetch the card at all).
//
// The box is sealed to the recipient's box_key from its card, so a real hub can open it.
// With --print the envelope JSON is printed instead of posted.

import {
  createCipheriv,
  createPrivateKey,
  createPublicKey,
  diffieHellman,
  generateKeyPairSync,
  hkdfSync,
  randomBytes,
  sign,
} from "node:crypto";
import { readFileSync } from "node:fs";
import { parseArgs } from "node:util";

const VECTOR_IDENTITY = {
  v: 1,
  sign_seed: "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8",
  box_seed: "ICEiIyQlJicoKSorLC0uLzAxMjM0NTY3ODk6Ozw9Pj8",
};
const ADDRESS =
  /^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*(:[0-9]{1,5})?$/;
const PKCS8_ED25519_PREFIX = Buffer.from("302e020100300506032b657004220420", "hex");

const { values: opts } = parseArgs({
  options: {
    to: { type: "string" },
    from: { type: "string", default: "127.0.0.1:8787" },
    kind: { type: "string", default: "message" },
    text: { type: "string", default: "Hello from a development tau." },
    name: { type: "string", default: "Dev tau" },
    identity: { type: "string" },
    thread: { type: "string" },
    "reply-to": { type: "string" },
    hops: { type: "string", default: "0" },
    print: { type: "boolean", default: false },
    help: { type: "boolean", short: "h", default: false },
  },
});

if (opts.help || !opts.to) {
  console.log(
    readFileSync(new URL(import.meta.url), "utf8")
      .split("\n")
      .slice(1, 17)
      .join("\n"),
  );
  process.exit(opts.help ? 0 : 2);
}
for (const [flag, address] of [
  ["--to", opts.to],
  ["--from", opts.from],
]) {
  if (!ADDRESS.test(address)) fail(`${flag} ${address} is not a valid address`);
}
if (!["message", "contact_request", "contact_accept"].includes(opts.kind)) {
  fail(`unknown --kind ${opts.kind}`);
}

function fail(message) {
  console.error(message);
  process.exit(2);
}

const b64u = (bytes) => Buffer.from(bytes).toString("base64url");
const unb64u = (text) => Buffer.from(text, "base64url");

/** http only for localhost / 127.0.0.1, like a spine with ALLOW_INSECURE_PEERS=1. */
function baseUrl(address) {
  const host = address.replace(/:[0-9]+$/, "");
  return `${host === "localhost" || host === "127.0.0.1" ? "http" : "https"}://${address}`;
}

function loadIdentity() {
  if (opts.identity) return JSON.parse(readFileSync(opts.identity, "utf8"));
  if (process.env.TAU_NET_IDENTITY) {
    return JSON.parse(unb64u(process.env.TAU_NET_IDENTITY).toString("utf8"));
  }
  console.error("Using the public test-vector keys (development only).");
  return VECTOR_IDENTITY;
}

async function recipientBoxKey() {
  const url = `${baseUrl(opts.to)}/.well-known/tau.json`;
  const response = await fetch(url, { signal: AbortSignal.timeout(5_000) });
  if (!response.ok)
    fail(`GET ${url} answered ${response.status}; publish the recipient's card first`);
  const card = await response.json();
  const key = unb64u(card.box_key ?? "");
  if (key.length !== 32) fail(`the card at ${url} has no 32-byte box_key`);
  return key;
}

/** X25519 + HKDF-SHA256 + ChaCha20-Poly1305, as in §3 "Sealing". */
function seal(plaintext, recipientBox, aad) {
  const { privateKey: esk, publicKey: epkKey } = generateKeyPairSync("x25519");
  const epk = unb64u(epkKey.export({ format: "jwk" }).x);
  const recipient = createPublicKey({
    key: { kty: "OKP", crv: "X25519", x: b64u(recipientBox) },
    format: "jwk",
  });
  const shared = diffieHellman({ privateKey: esk, publicKey: recipient });
  const key = Buffer.from(
    hkdfSync("sha256", shared, Buffer.concat([epk, recipientBox]), "tau-net/1 box", 32),
  );
  const nonce = randomBytes(12);
  const cipher = createCipheriv("chacha20-poly1305", key, nonce, { authTagLength: 16 });
  cipher.setAAD(aad, { plaintextLength: plaintext.length });
  const ct = Buffer.concat([cipher.update(plaintext), cipher.final(), cipher.getAuthTag()]);
  return { epk: b64u(epk), nonce: b64u(nonce), ct: b64u(ct) };
}

const identity = loadIdentity();
const signingKey = createPrivateKey({
  key: Buffer.concat([PKCS8_ED25519_PREFIX, unb64u(identity.sign_seed)]),
  format: "der",
  type: "pkcs8",
});

const id = randomBytes(18).toString("base64url");
const content =
  opts.kind === "message"
    ? { text: opts.text }
    : opts.kind === "contact_request"
      ? { name: opts.name, text: opts.text }
      : { name: opts.name };
const aad = Buffer.from(`tau-net/1|${id}|${opts.kind}|${opts.from}|${opts.to}`, "utf8");
const box = seal(Buffer.from(JSON.stringify(content), "utf8"), await recipientBoxKey(), aad);

const payload = Buffer.from(
  JSON.stringify({
    v: 1,
    id,
    kind: opts.kind,
    from: opts.from,
    to: opts.to,
    ts: Math.floor(Date.now() / 1000),
    thread: opts.thread ?? id,
    reply_to: opts["reply-to"] ?? null,
    hops: Number(opts.hops),
    box,
  }),
  "utf8",
);
const sig = sign(null, Buffer.concat([Buffer.from("tau-net/1\n"), payload]), signingKey);
const envelope = { payload: b64u(payload), sig: b64u(sig) };

if (opts.print) {
  console.log(JSON.stringify(envelope));
  process.exit(0);
}

const inbox = `${baseUrl(opts.to)}/net/inbox`;
const response = await fetch(inbox, {
  method: "POST",
  headers: { "content-type": "application/json" },
  body: JSON.stringify(envelope),
});
console.log(`POST ${inbox} -> ${response.status} ${await response.text()}`);
process.exit(response.status === 202 || response.status === 200 ? 0 : 1);
