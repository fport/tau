#!/usr/bin/env node
// node scripts/dev-site.mjs [--port 8795]
//
// Development only: serves public/ the way the Worker routes the pages, without the Worker,
// its Durable Objects or tau-host, so the site can be looked at and screenshot while the
// server side is elsewhere. Pair it with the pages' fixtures: open any page with
// `?fixture=1` (localhost only; see client/api.ts) and the person, sub-tau, claim and
// universe pages read built-in example data instead of the API.
//
//   bun run build && node scripts/dev-site.mjs
//   http://127.0.0.1:8795/?fixture=1              the landing page, the universe as its hero
//   http://127.0.0.1:8795/universe?fixture=1
//   http://127.0.0.1:8795/download                the download page (static)
//   http://127.0.0.1:8795/@alice?fixture=1        a person page
//   http://127.0.0.1:8795/coach?fixture=1         a sub-tau page with its visitor chat
//   http://127.0.0.1:8795/@alice/landing?fixture=1  a sub-tau without a chat
//   http://127.0.0.1:8795/@erin/scout?fixture=1   a hub-run sub-tau whose hub is offline
//   http://127.0.0.1:8795/@grace/poet?fixture=1   a sub-tau that answers "resting"
//   http://127.0.0.1:8795/claim?fixture=1         the claim page with an example claim
//   … and the same under /tr/.
//
// `bun run dev` (wrangler) serves the same pages through the real Worker, and `?fixture=1`
// works there too for /, /universe and /claim; the Worker answers /@handle and /<slug> only
// for handles and slugs its directory knows. This server listens on 127.0.0.1 only and
// answers no API: without the fixtures the pages show their "could not load" states.

import { existsSync, readFileSync, statSync } from "node:fs";
import { createServer } from "node:http";
import { dirname, extname, join, normalize } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const publicDir = join(root, "public");
const argv = process.argv.slice(2);
const portIndex = argv.indexOf("--port");
const port = portIndex === -1 ? 8795 : Number(argv[portIndex + 1]);

const CSP =
  "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; " +
  "connect-src 'self'; frame-ancestors 'none'";

const TYPES = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".svg": "image/svg+xml",
  ".woff2": "font/woff2",
  ".txt": "text/plain; charset=utf-8",
};

const HANDLE = /^[a-z0-9](?:[a-z0-9-]{0,37}[a-z0-9])?$/i;
const NAME = /^[a-z][a-z0-9-]{1,30}$/;
const PAGES = new Set(["/", "/how-it-works", "/universe", "/download", "/claim"]);

/** The file behind a page path, as the Worker picks it; null for none. */
function pageFile(path) {
  const tr = path === "/tr" || path.startsWith("/tr/");
  const rest = (tr ? path.slice(3) : path).replace(/\/+$/, "") || "/";
  const dir = tr ? "tr/" : "";
  if (PAGES.has(rest)) return `${dir}${rest === "/" ? "index" : rest.slice(1)}.html`;
  const person = /^\/@([^/]+)$/.exec(rest);
  if (person && HANDLE.test(person[1])) return `${dir}person.html`;
  const sub = /^\/@([^/]+)\/([^/]+)$/.exec(rest);
  if (sub && HANDLE.test(sub[1]) && NAME.test(sub[2])) return `${dir}sub.html`;
  const slug = /^\/([^/@.]+)$/.exec(rest);
  if (slug && NAME.test(slug[1])) return `${dir}sub.html`;
  return null;
}

function send(res, status, type, body, extra = {}) {
  res.writeHead(status, {
    "content-type": type,
    "x-content-type-options": "nosniff",
    "referrer-policy": "strict-origin-when-cross-origin",
    "cache-control": "no-store",
    ...(type.startsWith("text/html") ? { "content-security-policy": CSP } : {}),
    ...extra,
  });
  res.end(body);
}

const server = createServer((req, res) => {
  const url = new URL(req.url ?? "/", `http://${req.headers.host}`);
  const path = decodeURIComponent(url.pathname);

  // The switcher's `?lang=`: the Worker stores a cookie; here it only drops the parameter.
  if (url.searchParams.has("lang")) {
    url.searchParams.delete("lang");
    const query = url.searchParams.toString();
    send(res, 302, "text/plain", "", { location: `${url.pathname}${query ? `?${query}` : ""}` });
    return;
  }
  if (path === "/tr") {
    send(res, 302, "text/plain", "", { location: `/tr/${url.search}` });
    return;
  }

  // A static file (styles, scripts, brand, fonts).
  const file = normalize(join(publicDir, path));
  if (file.startsWith(publicDir) && existsSync(file) && statSync(file).isFile()) {
    send(res, 200, TYPES[extname(file)] ?? "application/octet-stream", readFileSync(file));
    return;
  }

  if (path.startsWith("/api/") || path.startsWith("/auth/")) {
    send(res, 404, "application/json", JSON.stringify({ error: "not_found" }));
    return;
  }

  const page = pageFile(path);
  if (page !== null && existsSync(join(publicDir, page))) {
    send(res, 200, TYPES[".html"], readFileSync(join(publicDir, page)));
    return;
  }
  const missing = path.startsWith("/tr/") ? "tr/404.html" : "404.html";
  send(res, 404, TYPES[".html"], readFileSync(join(publicDir, missing)));
});

server.listen(port, "127.0.0.1", () => {
  console.log(`The site at http://127.0.0.1:${port}/ (add ?fixture=1 for the example universe).`);
});
