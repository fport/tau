/**
 * ADR 0013 §6 routing: the person, sub-tau and claim pages, and the paths forwarded to
 * tau-host. The page templates (public/person.html, sub.html, claim.html) belong to the
 * site's pages; these tests serve stand-ins through a fake ASSETS binding, so they check the
 * routing and not the pages' content.
 */

import { reset } from "cloudflare:test";
import { env } from "cloudflare:workers";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import wranglerConfig from "../wrangler.example.jsonc?raw";
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

const EXPECTED_CSP =
  "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; " +
  "connect-src 'self'; frame-ancestors 'none'";

const TEMPLATE_FILES = ["/person", "/sub", "/claim", "/tr/person", "/tr/sub", "/tr/claim"];

/**
 * ASSETS with stand-in templates (`template <path>`); every other file comes from the real
 * asset store, so the 404 pages are the site's own. `missing` templates answer 404.
 */
function fakeAssets(missing: string[] = []) {
  const asked: string[] = [];
  const binding = {
    fetch: async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
      const request = new Request(input, init);
      const path = new URL(request.url).pathname;
      if (!TEMPLATE_FILES.includes(path)) return env.ASSETS.fetch(request);
      asked.push(path);
      if (missing.includes(path)) return new Response("Not Found", { status: 404 });
      return new Response(request.method === "HEAD" ? null : `<!doctype html>template ${path}`, {
        headers: { "content-type": "text/html; charset=utf-8", etag: '"t"' },
      });
    },
    connect: () => {
      throw new Error("no sockets in tests");
    },
  } as unknown as Fetcher;
  return { binding, asked };
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

  it("serve the person, sub-tau and claim templates in both languages", async () => {
    const cases: [string, string, "en" | "tr"][] = [
      ["/@alice", "/person", "en"],
      ["/tr/@alice", "/tr/person", "tr"],
      ["/coach", "/sub", "en"],
      ["/landing", "/sub", "en"],
      ["/tr/coach", "/tr/sub", "tr"],
      ["/@alice/coach", "/sub", "en"],
      ["/tr/@alice/landing", "/tr/sub", "tr"],
      ["/claim", "/claim", "en"],
      ["/tr/claim", "/tr/claim", "tr"],
    ];
    for (const [path, template, lang] of cases) {
      const assets = fakeAssets();
      const res = await universeWith({ ASSETS: assets.binding }, path);
      expect(res.status, path).toBe(200);
      expect(await res.text(), path).toBe(`<!doctype html>template ${template}`);
      expect(res.headers.get("content-language"), path).toBe(lang);
      expectSecurityHeaders(res);
      expect(assets.asked).toEqual([template]);
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
      const assets = fakeAssets();
      const res = await universeWith({ ASSETS: assets.binding }, path);
      expect(res.status, path).toBe(404);
      expect(res.headers.get("content-type"), path).toMatch(/^text\/html/);
      expect(res.headers.get("content-language"), path).toBe(path.startsWith("/tr/") ? "tr" : "en");
      expectSecurityHeaders(res);
      expect(await res.text(), path).toMatch(/Nothing at this address|Bu adreste bir şey yok/);
      expect(assets.asked, path).toEqual([]);
    }
  });

  it("never serve a template bare, nor a site name as a slug", async () => {
    for (const path of ["/person", "/sub", "/tr/person", "/tr/sub", "/api", "/app/x"]) {
      const assets = fakeAssets();
      const res = await universeWith({ ASSETS: assets.binding }, path);
      expect(res.status, path).toBe(404);
      expect(assets.asked, path).toEqual([]);
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

  it("answer HEAD, and refuse other methods", async () => {
    const assets = fakeAssets();
    const head = await universeWith({ ASSETS: assets.binding }, "/@alice", { method: "HEAD" });
    expect(head.status).toBe(200);
    expectSecurityHeaders(head);
    const res = await universe("/@alice", { method: "POST" });
    expect(res.status).toBe(405);
  });

  it("answer the 404 page when a deployment lacks the template", async () => {
    const assets = fakeAssets(["/person"]);
    const res = await universeWith({ ASSETS: assets.binding }, "/@alice");
    expect(res.status).toBe(404);
    expect(await res.text()).toContain("Nothing at this address.");
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

  it("runs the Worker first for the template pages", () => {
    const match = /"run_worker_first":\s*(\[[^\]]*\])/.exec(wranglerConfig);
    const routes = JSON.parse(match![1]!) as string[];
    for (const path of ["/@*", "/tr/@*", "/claim", "/tr/claim", ...TEMPLATE_FILES]) {
      expect(routes, path).toContain(path);
    }
  });
});
