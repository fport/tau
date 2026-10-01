/**
 * ADR 0013 §6 routing: the person, sub-tau and claim pages, and the paths forwarded to
 * tau-host. The pages are React (app/, ADR 0016); the server under test renders a stand-in
 * that names the app route it was asked for (test/worker.ts), so these tests check the
 * routing and not the pages' content (test/site.test.ts does).
 */

import { reset } from "cloudflare:test";
import { env } from "cloudflare:workers";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import {
  isForwarded,
  isReservedName,
  pageRoute,
  RESERVED_NAMES,
} from "../src/routes";
import {
  ALICE,
  BOB,
  FakeHost,
  GITHUB_ALICE,
  mockTaus,
  prepareTaus,
  resetClocks,
  send,
  sendClaim,
  universe,
  universeWith,
} from "./helpers";
import worker from "./worker";

const EXPECTED_CSP =
  "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; " +
  "connect-src 'self'; frame-ancestors 'none'";

/** The app route the stand-in renderer was asked for (test/worker.ts). */
function routeOf(page: string): string | null {
  return /data-route="([^"]*)"/.exec(page)?.[1] ?? null;
}

beforeAll(prepareTaus);
beforeEach(async () => {
  await reset();
  resetClocks();
});
afterEach(() => {
  vi.restoreAllMocks();
});

function expectSecurityHeaders(res: Response): void {
  expect(res.headers.get("content-security-policy")).toBe(EXPECTED_CSP);
  expect(res.headers.get("x-content-type-options")).toBe("nosniff");
  expect(res.headers.get("referrer-policy")).toBe("strict-origin-when-cross-origin");
}

describe("page routes", () => {
  beforeEach(async () => {
    mockTaus(ALICE, BOB);
    const host = new FakeHost(GITHUB_ALICE);
    for (const tau of [ALICE, BOB]) await send("join", tau);
    await send("report", ALICE, { subs: [{ name: "coach" }, { name: "landing" }] });
    await send("report", BOB, { subs: [{ name: "coach" }] });
    await sendClaim(host, ALICE, { account: GITHUB_ALICE });
  });

  it("render the person, sub-tau and claim pages in both languages", async () => {
    const cases: [string, string, "en" | "tr"][] = [
      ["/@alice", "/page/person", "en"],
      ["/tr/@alice", "/tr/page/person", "tr"],
      ["/coach", "/page/sub", "en"],
      ["/landing", "/page/sub", "en"],
      ["/tr/coach", "/tr/page/sub", "tr"],
      ["/@alice/coach", "/page/sub", "en"],
      ["/tr/@alice/landing", "/tr/page/sub", "tr"],
      ["/claim", "/claim", "en"],
      ["/tr/claim", "/tr/claim", "tr"],
    ];
    for (const [path, route, lang] of cases) {
      const res = await universe(path);
      expect(res.status, path).toBe(200);
      expect(routeOf(await res.text()), path).toBe(route);
      expect(res.headers.get("content-language"), path).toBe(lang);
      expectSecurityHeaders(res);
    }
  });

  it("answer the 404 page for a handle, slug or sub-tau the directory does not have", async () => {
    for (const path of [
      "/@nobody",
      "/@alice/nope",
      "/@nobody/coach",
      "/nope",
      "/@bob",
      "/@bob/coach",
      "/tr/@nobody",
      "/tr/nope",
    ]) {
      const res = await universe(path);
      const turkish = path.startsWith("/tr/");
      expect(res.status, path).toBe(404);
      expect(res.headers.get("content-type"), path).toMatch(/^text\/html/);
      expect(res.headers.get("content-language"), path).toBe(turkish ? "tr" : "en");
      expect(res.headers.get("cache-control"), path).toBe("no-store");
      expectSecurityHeaders(res);
      expect(routeOf(await res.text()), path).toBe(turkish ? "/tr/page/missing" : "/page/missing");
    }
  });

  it("never render an internal page from outside, nor a site name as a slug", async () => {
    for (const path of [
      "/person",
      "/sub",
      "/tr/person",
      "/tr/sub",
      "/page",
      "/page/person",
      "/page/sub",
      "/page/missing",
      "/tr/page/person",
      "/api",
      "/app/x",
    ]) {
      const res = await universe(path);
      expect(res.status, path).toBe(404);
      const route = routeOf(await res.text());
      if (route !== null) expect(route, path).toMatch(/\/page\/missing$/);
    }
  });

  it("show a page without the lookup only for ?fixture=1 on a local host", async () => {
    const local = await worker.fetch(new Request("http://localhost:8790/@nobody?fixture=1"), env);
    expect(local.status).toBe(200);
    expect(routeOf(await local.text())).toBe("/page/person");
    const sub = await worker.fetch(new Request("http://127.0.0.1:8790/tr/nope?fixture=1"), env);
    expect(routeOf(await sub.text())).toBe("/tr/page/sub");
    for (const url of [
      "https://universe.example/@nobody?fixture=1",
      "http://localhost:8790/@nobody",
      "http://localhost:8790/@nobody?fixture=0",
    ]) {
      const res = await worker.fetch(new Request(url), env);
      expect(res.status, url).toBe(404);
    }
  });

  it("send a handle in capitals to its lower-case page", async () => {
    for (const [path, location] of [
      ["/@Alice", "/@alice"],
      ["/tr/@ALICE", "/tr/@alice"],
      ["/@Alice/coach?ref=x", "/@alice/coach?ref=x"],
    ] as const) {
      const res = await universe(path, { redirect: "manual" });
      expect(res.status, path).toBe(301);
      expect(res.headers.get("location"), path).toBe(location);
    }
  });

  it("store the switcher's language choice like every other page", async () => {
    const res = await universe("/tr/@alice?lang=tr", { redirect: "manual" });
    expect(res.status).toBe(302);
    expect(res.headers.get("location")).toBe("/tr/@alice");
    expect(res.headers.get("set-cookie")).toMatch(/^lang=tr; /);
  });

  it("answer HEAD without a body, and refuse other methods", async () => {
    const head = await universe("/@alice", { method: "HEAD" });
    expect(head.status).toBe(200);
    expect(await head.text()).toBe("");
    expectSecurityHeaders(head);
    const res = await universe("/@alice", { method: "POST" });
    expect(res.status).toBe(405);
  });
});

describe("forwarding to tau-host", () => {
  const forwarded: [string, string, string | null][] = [
    ["GET", "/app", null],
    ["GET", "/app/", null],
    ["GET", "/app/settings?tab=keys", null],
    ["GET", "/auth/login", null],
    ["GET", "/auth/callback?code=c&state=s", null],
    ["POST", "/auth/logout", ""],
    ["GET", "/api/host/account", null],
    ["POST", "/api/host/subs", '{"name":"coach"}'],
    ["GET", "/@alice/.well-known/tau.json", null],
    ["POST", "/@alice/net/inbox", '{"payload":"x","sig":"y"}'],
    ["GET", "/@bob-2/net/hub/poll", null],
  ];

  it("passes tau-host's paths through unchanged, both ways", async () => {
    for (const [method, path, body] of forwarded) {
      const host = new FakeHost();
      const init: RequestInit = {
        method,
        headers: { cookie: "tau_session=s-1", origin: "https://universe.example", "x-extra": "1" },
        ...(body === null ? {} : { body }),
      };
      const res = await universeWith({ HOST: host.binding }, path, init);
      const where = `${method} ${path}`;
      expect(res.status, where).toBe(299);
      expect(res.headers.get("x-served-by"), where).toBe("tau-host");
      // tau-host sets its own headers; the universe adds none.
      expect(res.headers.get("content-security-policy"), where).toBeNull();
      expect(await res.text(), where).toBe(`tau-host ${method} ${path}`);
      expect(host.requests, where).toHaveLength(1);
      const [request] = host.requests;
      expect(request!.method).toBe(method);
      expect(request!.url).toBe(`https://universe.example${path}`);
      expect(request!.headers.get("cookie")).toBe("tau_session=s-1");
      expect(request!.headers.get("x-extra")).toBe("1");
      expect(await request!.text()).toBe(body ?? "");
    }
  });

  it("sends sign-in to the opening-soon page on a universe without tau-host", async () => {
    const en = await universe("/auth/login", { redirect: "manual" });
    expect(en.status).toBe(302);
    expect(en.headers.get("location")).toBe("/soon");
    const tr = await universe("/auth/login?next=/app", {
      redirect: "manual",
      headers: { cookie: "lang=tr" },
    });
    expect(tr.headers.get("location")).toBe("/tr/soon");
    const accept = await universe("/auth/login", {
      redirect: "manual",
      headers: { "accept-language": "tr-TR,tr" },
    });
    expect(accept.headers.get("location")).toBe("/tr/soon");
  });

  it("is 404 for tau-host's paths on a universe without tau-host", async () => {
    for (const [method, path, body] of forwarded) {
      if (method === "GET" && path === "/auth/login") continue;
      const res = await universe(path, { method, ...(body === null ? {} : { body }) });
      const where = `${method} ${path}`;
      expect(res.status, where).toBe(404);
      expectSecurityHeaders(res);
      const page = method === "GET" && !path.startsWith("/api/");
      expect(res.headers.get("content-type"), where).toMatch(
        page ? /^text\/html/ : /^application\/json/,
      );
    }
  });

  it("keeps everything else", async () => {
    const host = new FakeHost();
    for (const path of [
      "/",
      "/universe",
      "/api/universe",
      "/api/hostx",
      "/authx",
      "/application",
      "/@alice",
      "/@alice/coach",
      "/@alice/net",
      "/@Alice/net/inbox",
      "/@alice/.well-known/other.json",
      "/tr/app",
      "/.well-known/tau.json",
    ]) {
      await (await universeWith({ HOST: host.binding }, path)).body?.cancel();
    }
    expect(host.requests.map((request) => request.url)).toEqual([]);
  });

  it("is 502 host_unavailable when the binding throws", async () => {
    const broken = {
      fetch: async () => {
        throw new Error("down");
      },
    } as unknown as Fetcher;
    const res = await universeWith({ HOST: broken }, "/app");
    expect(res.status).toBe(502);
    expect(await res.json()).toEqual({ error: "host_unavailable" });
  });
});

describe("the route table", () => {
  it("names tau-host's paths", () => {
    for (const path of [
      "/app",
      "/app/",
      "/app/x/y",
      "/auth/login",
      "/api/host/whoami",
      "/@a/.well-known/tau.json",
      "/@alice/net/inbox",
    ]) {
      expect(isForwarded(path), path).toBe(true);
    }
    for (const path of [
      "/apps",
      "/auth",
      "/api/hosts",
      "/api/host",
      "/@alice",
      "/@alice/net",
      "/@alice/coach",
      "/@-alice/net/inbox",
      "/@alice/.well-known/tau.json/x",
    ]) {
      expect(isForwarded(path), path).toBe(false);
    }
  });

  it("names the template pages", () => {
    expect(pageRoute("/@alice")).toEqual({ kind: "person", lang: "en", handle: "alice" });
    expect(pageRoute("/tr/@alice/coach")).toEqual({
      kind: "sub",
      lang: "tr",
      handle: "alice",
      name: "coach",
    });
    expect(pageRoute("/coach")).toEqual({ kind: "slug", lang: "en", slug: "coach" });
    expect(pageRoute("/claim")).toEqual({ kind: "claim", lang: "en" });
    expect(pageRoute("/@Alice")).toEqual({ kind: "redirect", location: "/@alice" });
    expect(pageRoute("/sub")).toEqual({ kind: "template" });
    for (const path of [
      "/",
      "/tr/",
      "/universe",
      "/tr/how-it-works",
      "/c",
      "/Coach",
      "/1coach",
      "/coach/",
      "/@alice/",
      "/@alice/net",
      "/@alice/Coach",
      "/@-x",
      "/tr/tr",
      "/tr",
    ]) {
      expect(pageRoute(path), path).toBeNull();
    }
  });

  it("reserves every top-level name under public/ from slugs", () => {
    const files = Object.keys(import.meta.glob("../public/**"));
    expect(files.length).toBeGreaterThan(5);
    const names = new Set<string>();
    for (const file of files) {
      const parts = file.slice("../public/".length).split("/");
      const top = parts[0] === "tr" && parts.length > 1 ? [parts[0], parts[1]!] : [parts[0]!];
      for (const part of top) names.add(part.replace(/\.html$/, ""));
    }
    for (const name of names) expect(isReservedName(name), name).toBe(true);
    for (const name of ["api", "app", "auth", "claim", "person", "sub", "universe", "tr"]) {
      expect(RESERVED_NAMES.has(name), name).toBe(true);
    }
  });

  it("reserves every page of app/ from slugs, the internal routes included", () => {
    // Parentheses are glob syntax: list every page and keep the English ones.
    const prefix = "../app/(en)/";
    const pages = Object.keys(import.meta.glob("../app/**/page.tsx")).filter(
      (file) => file.startsWith(prefix) && file !== `${prefix}page.tsx`,
    );
    expect(pages.length).toBeGreaterThan(6);
    for (const file of pages) {
      const name = file.slice(prefix.length).split("/")[0]!;
      expect(isReservedName(name), name).toBe(true);
    }
  });
});
