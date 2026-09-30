#!/usr/bin/env node
// Fills a LOCAL universe with a small cast of development taus, so the universe page has
// something to draw under `bun run dev`. A development tool; it refuses any universe that is
// not on 127.0.0.1 or localhost.
//
//   node scripts/dev-taus.mjs [--universe 127.0.0.1:8790] [--port 18790] [--count N] [--leave]
//
// It serves each tau's card on http://127.0.0.1:<port + i>/.well-known/tau.json (the
// universe needs ALLOW_INSECURE_PEERS=1, which `.dev.vars` sets), sends a signed join for
// every tau, then a report with the links and public sub-taus below, prints the snapshot and
// stops. One of the links is one-sided on purpose: the page must not draw it. --count N uses only the first
// N taus of the cast (to see the page's tiny states). With --leave the taus leave again.
//
// The keys come from fixed seeds, so the cast is the same on every run. Nothing here ever
// reaches a deployed universe.

import { createHash, createPrivateKey, createPublicKey, sign } from "node:crypto";
import { createServer } from "node:http";
import { parseArgs } from "node:util";

const { values: opts } = parseArgs({
  options: {
    universe: { type: "string", default: "127.0.0.1:8790" },
    port: { type: "string", default: "18790" },
    count: { type: "string" },
    leave: { type: "boolean", default: false },
    help: { type: "boolean", short: "h", default: false },
  },
});
if (opts.help) {
  console.log(
    "Usage: node scripts/dev-taus.mjs [--universe 127.0.0.1:8790] [--port 18790] [--count N] [--leave]",
  );
  process.exit(0);
}

const host = opts.universe.replace(/:\d+$/, "");
if (host !== "127.0.0.1" && host !== "localhost") {
  console.error("dev-taus only talks to a local universe (127.0.0.1 or localhost).");
  process.exit(2);
}
const basePort = Number(opts.port);

const CAST = [
  {
    name: "Deniz's tau",
    owner: "Deniz",
    about: "Lives on a Raspberry Pi by the window.",
    subs: [
      { name: "coach", about: "A patient running coach: three short runs a week." },
      { name: "landing", about: "Writes landing-page copy." },
    ],
  },
  { name: "Deniz's workshop", owner: "Deniz", about: "Keeps an eye on the 3D printer." },
  { name: "Mira's tau", owner: "Mira", about: "Plans the week and asks before it books anything." },
  { name: "Sam's tau", owner: "Sam", about: "" },
  {
    name: "Kai's tau",
    owner: "Kai",
    about: "Robot arm in simulation, for now.",
    subs: [{ name: "arm", about: "Plans moves for the robot arm, in simulation." }],
  },
  { name: "Kai's desk", owner: "Kai", about: "" },
  { name: "night-owl", owner: "", about: "Just joined." },
];

// [a, b, what a reports, what b reports]; null = that side does not report the link.
const LINKS = [
  [0, 1, 120, 118],
  [0, 2, 42, 40],
  [2, 3, 9, 12],
  [4, 5, 64, 64],
  [0, 4, 5, 7],
  [3, 6, 3, null],
];

const PKCS8_ED25519_PREFIX = Buffer.from("302e020100300506032b657004220420", "hex");

const count = opts.count === undefined ? CAST.length : Number(opts.count);
if (!Number.isInteger(count) || count < 1 || count > CAST.length) {
  console.error(`--count must be 1..${CAST.length}`);
  process.exit(2);
}

const taus = CAST.slice(0, count).map((tau, i) => {
  const seed = createHash("sha256").update(`tau-universe dev tau ${i}`).digest();
  const privateKey = createPrivateKey({
    key: Buffer.concat([PKCS8_ED25519_PREFIX, seed]),
    format: "der",
    type: "pkcs8",
  });
  const signKey = createPublicKey(privateKey).export({ format: "jwk" }).x;
  const address = `127.0.0.1:${basePort + i}`;
  return { ...tau, address, privateKey, signKey };
});

function cardOf(tau) {
  return {
    v: 1,
    address: tau.address,
    name: tau.name,
    sign_key: tau.signKey,
    box_key: tau.signKey,
    inbox: `http://${tau.address}/net/inbox`,
    software: "tau-universe-dev/0",
  };
}

async function serveCards() {
  const servers = [];
  for (const tau of taus) {
    const server = createServer((req, res) => {
      if (req.url === "/.well-known/tau.json") {
        res.writeHead(200, { "content-type": "application/json" });
        res.end(JSON.stringify(cardOf(tau)));
      } else {
        res.writeHead(404).end();
      }
    });
    await new Promise((resolve, reject) => {
      server.once("error", reject);
      server.listen(Number(tau.address.split(":")[1]), "127.0.0.1", resolve);
    });
    servers.push(server);
  }
  return servers;
}

let clock = Math.floor(Date.now() / 1000);

async function send(kind, tau, extra = {}) {
  const payload = {
    v: 1,
    kind,
    universe: opts.universe,
    address: tau.address,
    ts: clock,
    ...extra,
  };
  const bytes = Buffer.from(JSON.stringify(payload));
  const sig = sign(null, Buffer.concat([Buffer.from("tau-universe/1\n"), bytes]), tau.privateKey);
  const res = await fetch(`http://${opts.universe}/api/${kind}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ payload: bytes.toString("base64url"), sig: sig.toString("base64url") }),
  });
  const answer = await res.text();
  console.log(`${kind.padEnd(6)} ${tau.address.padEnd(16)} ${res.status} ${answer}`);
  return res.status;
}

const servers = await serveCards();
try {
  if (opts.leave) {
    for (const tau of taus) await send("leave", tau);
  } else {
    for (const tau of taus) await send("join", tau, { owner: tau.owner, about: tau.about });
    clock += 1;
    for (const [i, tau] of taus.entries()) {
      const links = [];
      for (const [a, b, fromA, fromB] of LINKS) {
        if (a >= count || b >= count) continue;
        if (a === i && fromA !== null) links.push({ peer: taus[b].address, messages: fromA });
        if (b === i && fromB !== null) links.push({ peer: taus[a].address, messages: fromB });
      }
      await send("report", tau, tau.subs ? { links, subs: tau.subs } : { links });
    }
  }
  const snapshot = await (await fetch(`http://${opts.universe}/api/universe`)).json();
  console.log(
    `\n${snapshot.stats.taus} taus, ${snapshot.stats.online} online, ` +
      `${snapshot.links.length} links, ${snapshot.stats.messages} messages. ` +
      `Open http://${opts.universe}/universe`,
  );
} finally {
  for (const server of servers) server.close();
}
