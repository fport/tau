/**
 * What the server decides about the pages (src/pages.ts): which app route each path renders,
 * in which language, with which status and headers, and the language choice. The server under
 * test renders a stand-in that names the route (test/worker.ts); the rendered pages
 * themselves are checked in the built Worker (test/site.test.ts).
 */

import { describe, expect, it } from "vitest";
import headersFile from "../public/_headers?raw";
import installScript from "../public/install.sh?raw";
import {
  CONTENT_SECURITY_POLICY,
  PAGES,
  cookieLanguage,
  pageSecurityPolicy,
  preferredLanguage,
  newNonce,
} from "../src/pages";
import { createUniverse } from "../src/server";
import { env } from "cloudflare:workers";
import { universe } from "./helpers";
import { renderStandIn } from "./worker";

const EXPECTED_CSP =
  "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; " +
  "connect-src 'self'; frame-ancestors 'none'";

/** Each English page, its Turkish twin, and the app routes they render. */
const TWINS: readonly (readonly [string, string, string, string])[] = [
  ["/", "/tr/", "/", "/tr"],
  ["/how-it-works", "/tr/how-it-works", "/how-it-works", "/tr/how-it-works"],
  ["/universe", "/tr/universe", "/universe", "/tr/universe"],
  ["/download", "/tr/download", "/download", "/tr/download"],
  ["/soon", "/tr/soon", "/soon", "/tr/soon"],
];

const TURKISH = "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7";

function expectSecurityHeaders(res: Response): void {
  expect(res.headers.get("content-security-policy")).toBe(EXPECTED_CSP);
  expect(res.headers.get("x-content-type-options")).toBe("nosniff");
  expect(res.headers.get("referrer-policy")).toBe("strict-origin-when-cross-origin");
}

/** The app route the stand-in renderer was asked for. */
function routeOf(page: string): string | null {
  return /data-route="([^"]*)"/.exec(page)?.[1] ?? null;
}

describe("pages", () => {
  it("renders every page in English and in Turkish, from its app route", async () => {
    for (const [en, tr, enRoute, trRoute] of TWINS) {
      for (const [path, route, lang] of [
        [en, enRoute, "en"],
        [tr, trRoute, "tr"],
      ] as const) {
        const res = await universe(path);
        expect(res.status, path).toBe(200);
        expect(res.headers.get("content-type"), path).toMatch(/^text\/html/);
        expect(res.headers.get("content-language"), path).toBe(lang);
        expectSecurityHeaders(res);
        expect(routeOf(await res.text()), path).toBe(route);
      }
    }
    expect(Object.keys(PAGES).sort()).toEqual(TWINS.flatMap(([en, tr]) => [en, tr]).sort());
  });

  it("answers HEAD for the pages, without a body", async () => {
    for (const path of ["/", "/tr/how-it-works"]) {
      const res = await universe(path, { method: "HEAD" });
      expect(res.status, path).toBe(200);
      expect(await res.text(), path).toBe("");
      expectSecurityHeaders(res);
    }
  });

  it("answers unknown paths with the 404 page of their language", async () => {
    for (const [path, route, lang] of [
      ["/nowhere", "/page/missing", "en"],
      ["/tr/nowhere", "/tr/page/missing", "tr"],
      ["/a/b/c", "/page/missing", "en"],
    ] as const) {
      const res = await universe(path);
      expect(res.status, path).toBe(404);
      expect(res.headers.get("content-type"), path).toMatch(/^text\/html/);
      expect(res.headers.get("content-language"), path).toBe(lang);
      expect(res.headers.get("cache-control"), path).toBe("no-store");
      expectSecurityHeaders(res);
      expect(routeOf(await res.text()), path).toBe(route);
    }
  });

  it("answers plain text when the 404 page itself cannot be rendered", async () => {
    const broken = createUniverse(async () => {
      throw new Error("no renderer");
    });
    const res = await broken.fetch(new Request("https://universe.example/nowhere"), env);
    expect(res.status).toBe(404);
    expect(res.headers.get("content-type")).toMatch(/^text\/plain/);
    expectSecurityHeaders(res);
  });

  it("refuses other methods on pages", async () => {
    for (const path of ["/", "/tr/how-it-works"]) {
      const res = await universe(path, { method: "POST" });
      expect(res.status, path).toBe(405);
      expect(res.headers.get("allow")).toBe("GET");
      expectSecurityHeaders(res);
    }
  });

  it("keeps a page's own policy, the one with its nonce", async () => {
    const nonce = newNonce();
    const withNonce = createUniverse(async (request, target, e, ctx) => {
      const page = await renderStandIn(request, target, e, ctx);
      const response = new Response(page.body, page);
      response.headers.set("content-security-policy", pageSecurityPolicy(nonce));
      return response;
    });
    const res = await withNonce.fetch(new Request("https://universe.example/universe"), env);
    expect(res.headers.get("content-security-policy")).toBe(pageSecurityPolicy(nonce));
    expect(res.headers.get("x-content-type-options")).toBe("nosniff");
  });

  it("makes each page's nonce fresh, and allows it for scripts and styles only", () => {
    const a = newNonce();
    expect(a).toMatch(/^[A-Za-z0-9+/]{22}==$/);
    expect(newNonce()).not.toBe(a);
    const policy = pageSecurityPolicy(a);
    expect(policy).toContain(`script-src 'self' 'nonce-${a}'`);
    expect(policy).toContain(`style-src 'self' 'nonce-${a}'`);
    expect(policy.replace(` 'nonce-${a}'`, "").replace(` 'nonce-${a}'`, "")).toBe(
      CONTENT_SECURITY_POLICY,
    );
    expect(CONTENT_SECURITY_POLICY).toBe(EXPECTED_CSP);
  });

  it("keeps the asset store's headers for the files it serves", () => {
    expect(headersFile).toContain("X-Content-Type-Options: nosniff");
    expect(headersFile).toContain("Referrer-Policy: strict-origin-when-cross-origin");
    const rule = headersFile.split(/\n\s*\n/).find((block) => /^\/install\.sh$/m.test(block));
    expect(rule).toBeDefined();
    expect(rule).toContain("Content-Type: text/plain; charset=utf-8");
  });

  it("keeps install.sh safe to pipe into sh", () => {
    expect(installScript.startsWith("#!/bin/sh\n")).toBe(true);
    // Everything runs from main, called on the last line: a cut-off download runs nothing.
    expect(installScript.trimEnd().endsWith('main "$@"')).toBe(true);
    const code = installScript
      .split("\n")
      .filter((line) => line.trim() !== "" && !line.trimStart().startsWith("#"));
    // `sudo` appears only in what the script says, never as a command it runs
    expect(code.some((line) => /\bsudo\b/.test(line) && !line.includes('say "'))).toBe(false);
  });

  it("redirects /tr to /tr/", async () => {
    // A call through `exports` follows redirects unless told not to.
    const res = await universe("/tr", { redirect: "manual" });
    expect(res.status).toBe(302);
    expect(res.headers.get("location")).toBe("/tr/");
    expectSecurityHeaders(res);
  });
});

describe("the language choice", () => {
  const at = (path: string, headers: Record<string, string> = {}) =>
    universe(path, { headers, redirect: "manual" });

  it("sends a browser that prefers Turkish from / to /tr/ when no choice is stored", async () => {
    const res = await at("/", { "accept-language": TURKISH });
    expect(res.status).toBe(302);
    expect(res.headers.get("location")).toBe("/tr/");
    expect(res.headers.get("vary")).toBe("Accept-Language, Cookie");
    expect(res.headers.get("set-cookie")).toBeNull();
    expectSecurityHeaders(res);
    await res.body?.cancel();
  });

  it("keeps the query string on that redirect", async () => {
    const res = await at("/?ref=news", { "accept-language": TURKISH });
    expect(res.headers.get("location")).toBe("/tr/?ref=news");
  });

  it("serves English at / for English, other or missing preferences", async () => {
    for (const acceptLanguage of ["en-US,en;q=0.9,tr;q=0.8", "de-DE,de;q=0.9", "tr;q=0", null]) {
      const headers: Record<string, string> =
        acceptLanguage === null ? {} : { "accept-language": acceptLanguage };
      const res = await at("/", headers);
      expect(res.status, String(acceptLanguage)).toBe(200);
      expect(res.headers.get("vary")).toContain("Accept-Language");
      expect(await res.text()).toContain('<html lang="en">');
    }
  });

  it("lets the stored choice win over Accept-Language, both ways", async () => {
    const english = await at("/", { "accept-language": TURKISH, cookie: "theme=dark; lang=en" });
    expect(english.status).toBe(200);
    expect(await english.text()).toContain('<html lang="en">');

    const turkish = await at("/", { "accept-language": "en-US,en", cookie: "lang=tr" });
    expect(turkish.status).toBe(302);
    expect(turkish.headers.get("location")).toBe("/tr/");
  });

  it("never redirects the other pages", async () => {
    for (const path of ["/how-it-works", "/universe", "/download"]) {
      const res = await at(path, { "accept-language": TURKISH, cookie: "lang=tr" });
      expect(res.status, path).toBe(200);
      await res.body?.cancel();
    }
    const res = await at("/tr/", { "accept-language": "en", cookie: "lang=en" });
    expect(res.status).toBe(200);
    await res.body?.cancel();
  });

  it("stores the switcher's choice in a cookie and drops the parameter", async () => {
    const res = await at("/tr/how-it-works?lang=tr");
    expect(res.status).toBe(302);
    expect(res.headers.get("location")).toBe("/tr/how-it-works");
    const cookie = res.headers.get("set-cookie") ?? "";
    expect(cookie).toMatch(/^lang=tr; /);
    for (const part of ["Path=/", "Max-Age=31536000", "SameSite=Lax", "HttpOnly", "Secure"]) {
      expect(cookie).toContain(part);
    }
    expect(res.headers.get("cache-control")).toBe("no-store");
    expectSecurityHeaders(res);

    const back = await at("/?lang=en&ref=switch");
    expect(back.status).toBe(302);
    expect(back.headers.get("location")).toBe("/?ref=switch");
    expect(back.headers.get("set-cookie")).toMatch(/^lang=en; /);
  });

  it("ignores a language it does not have", async () => {
    const res = await at("/how-it-works?lang=de");
    expect(res.status).toBe(200);
    expect(res.headers.get("set-cookie")).toBeNull();
    await res.body?.cancel();
  });

  it("reads Accept-Language by q-value and the cookie by name", () => {
    expect(preferredLanguage("tr")).toBe("tr");
    expect(preferredLanguage("tr-TR")).toBe("tr");
    expect(preferredLanguage("en-GB,tr;q=0.9")).toBe("en");
    expect(preferredLanguage("en;q=0.5, tr;q=0.8")).toBe("tr");
    expect(preferredLanguage("de-DE, tr;q=0.5")).toBe("tr");
    expect(preferredLanguage("TR-tr;q=1.0, EN;q=1.0")).toBe("tr");
    expect(preferredLanguage("fr, de")).toBeNull();
    expect(preferredLanguage("tr;q=0, en;q=0.1")).toBe("en");
    expect(preferredLanguage("*")).toBeNull();
    expect(preferredLanguage("")).toBeNull();
    expect(preferredLanguage(null)).toBeNull();

    expect(cookieLanguage("lang=tr")).toBe("tr");
    expect(cookieLanguage("a=1; lang=en; b=2")).toBe("en");
    expect(cookieLanguage("xlang=tr; lang2=tr")).toBeNull();
    expect(cookieLanguage("lang=de")).toBeNull();
    expect(cookieLanguage(null)).toBeNull();
  });
});
