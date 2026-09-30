import { describe, expect, it } from "vitest";
import headersFile from "../public/_headers?raw";
import installScript from "../public/install.sh?raw";
import wranglerConfig from "../wrangler.example.jsonc?raw";
import {
  CONTENT_SECURITY_POLICY,
  PAGES,
  cookieLanguage,
  preferredLanguage,
} from "../src/pages";
import { universe } from "./helpers";

const EXPECTED_CSP =
  "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; " +
  "connect-src 'self'; frame-ancestors 'none'";

/** Each English page and its Turkish twin. */
const TWINS: readonly (readonly [string, string])[] = [
  ["/", "/tr/"],
  ["/how-it-works", "/tr/how-it-works"],
  ["/universe", "/tr/universe"],
];

const ALL_PAGES = TWINS.flat();
const SITE = "https://tau.getporti.com";
const DOCS = "https://docs.tau.getporti.com/";
const TURKISH_DOCS = `${DOCS}tr/`;
const TURKISH = "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7";

function expectSecurityHeaders(res: Response): void {
  expect(res.headers.get("content-security-policy")).toBe(EXPECTED_CSP);
  expect(res.headers.get("x-content-type-options")).toBe("nosniff");
  expect(res.headers.get("referrer-policy")).toBe("strict-origin-when-cross-origin");
}

async function html(path: string, init?: RequestInit): Promise<string> {
  const res = await universe(path, init);
  expect(res.status, path).toBe(200);
  return res.text();
}

function hrefs(page: string): string[] {
  return [...page.matchAll(/\shref="([^"]*)"/g)].map((match) => match[1]!);
}

function ids(page: string): string[] {
  return [...page.matchAll(/\sid="([^"]*)"/g)].map((match) => match[1]!);
}

describe("pages", () => {
  it("serves the landing page at / with the security headers", async () => {
    const res = await universe("/");
    expect(res.status).toBe(200);
    expect(res.headers.get("content-type")).toMatch(/^text\/html/);
    expectSecurityHeaders(res);
    const page = await res.text();
    expect(page).toContain("A personal agent that lives on your own machine.");
    expect(page).toContain('href="https://docs.tau.getporti.com/"');
    expect(page).toContain('href="/universe"');
    expect(page).not.toMatch(/github\.com/i);
    // The hero is the universe on a canvas, drawn by its own script (client/landing.ts).
    expect(page).toContain('<canvas class="hero-cosmos" id="cosmos" aria-hidden="true"></canvas>');
    expect(page).toContain('<script type="module" src="/static/landing.js"></script>');
    expect(page).not.toContain("/static/universe.js");
  });

  it("serves the universe page at /universe with the security headers", async () => {
    const res = await universe("/universe");
    expect(res.status).toBe(200);
    expect(res.headers.get("content-type")).toMatch(/^text\/html/);
    expectSecurityHeaders(res);
    const page = await res.text();
    expect(page).toContain("The tau universe");
    expect(page).toContain('<script type="module" src="/static/universe.js"></script>');
    // The whole page is the universe: one canvas, the list and the join steps in its panel.
    expect(page).toContain('<link rel="stylesheet" href="/styles/universe.css">');
    expect(page).toContain('id="cosmos"');
    expect(page).toContain('id="tau-list"');
    expect(page).toContain("tau net universe join");
  });

  it("answers HEAD for the pages", async () => {
    for (const path of ["/", "/tr/how-it-works"]) {
      const res = await universe(path, { method: "HEAD" });
      expect(res.status, path).toBe(200);
      expectSecurityHeaders(res);
    }
  });

  it("keeps the pages free of inline scripts and styles (the CSP would block them)", async () => {
    for (const path of [...ALL_PAGES, "/nowhere", "/tr/nowhere"]) {
      const page = await (await universe(path)).text();
      expect(page).not.toMatch(/<script(?![^>]*\bsrc=)[^>]*>/);
      expect(page).not.toMatch(/<style[\s>]/);
      expect(page).not.toMatch(/\sstyle="/);
      expect(page).not.toMatch(/\son[a-z]+="/);
    }
  });

  it("answers unknown paths with the 404 page and the security headers", async () => {
    const res = await universe("/nowhere");
    expect(res.status).toBe(404);
    expect(res.headers.get("content-type")).toMatch(/^text\/html/);
    expect(res.headers.get("content-language")).toBe("en");
    expectSecurityHeaders(res);
    expect(await res.text()).toContain("Nothing at this address.");
  });

  it("answers unknown paths under /tr/ with the Turkish 404 page", async () => {
    const res = await universe("/tr/nowhere");
    expect(res.status).toBe(404);
    expect(res.headers.get("content-type")).toMatch(/^text\/html/);
    expect(res.headers.get("content-language")).toBe("tr");
    expectSecurityHeaders(res);
    const page = await res.text();
    expect(page).toContain('<html lang="tr">');
    expect(page).toContain("Bu adreste bir şey yok.");
  });

  it("refuses other methods on pages", async () => {
    for (const path of ["/", "/tr/how-it-works"]) {
      const res = await universe(path, { method: "POST" });
      expect(res.status, path).toBe(405);
      expect(res.headers.get("allow")).toBe("GET");
      expectSecurityHeaders(res);
    }
  });

  it("puts the same policy into public/_headers for /404 and /tr/404", () => {
    expect(CONTENT_SECURITY_POLICY).toBe(EXPECTED_CSP);
    for (const path of ["/404", "/tr/404"]) {
      const rule = headersFile
        .split(/\n\s*\n/)
        .find((block) => new RegExp(`^${path.replaceAll("/", "\\/")}$`, "m").test(block));
      expect(rule, path).toBeDefined();
      expect(rule).toContain(`Content-Security-Policy: ${EXPECTED_CSP}`);
    }
    expect(headersFile).toContain("X-Content-Type-Options: nosniff");
    expect(headersFile).toContain("Referrer-Policy: strict-origin-when-cross-origin");
  });

  it("serves install.sh as plain text straight from the asset store", () => {
    const rule = headersFile
      .split(/\n\s*\n/)
      .find((block) => /^\/install\.sh$/m.test(block));
    expect(rule).toBeDefined();
    expect(rule).toContain("Content-Type: text/plain; charset=utf-8");
    const match = /"run_worker_first":\s*(\[[^\]]*\])/.exec(wranglerConfig);
    const routes = JSON.parse(match![1]!) as string[];
    expect(routes).not.toContain("/install.sh");
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

  it("runs the Worker first for every page, so every page gets the headers", () => {
    const match = /"run_worker_first":\s*(\[[^\]]*\])/.exec(wranglerConfig);
    expect(match).not.toBeNull();
    const routes = JSON.parse(match![1]!) as string[];
    expect(routes).toContain("/api/*");
    expect(routes).toContain("/tr");
    for (const path of Object.keys(PAGES)) expect(routes, path).toContain(path);
    expect(Object.keys(PAGES).sort()).toEqual([...ALL_PAGES].sort());
  });
});

describe("pages in two languages", () => {
  it("serves every page in English and in Turkish with its language", async () => {
    for (const [en, tr] of TWINS) {
      for (const [path, lang] of [
        [en, "en"],
        [tr, "tr"],
      ] as const) {
        const res = await universe(path);
        expect(res.status, path).toBe(200);
        expect(res.headers.get("content-type")).toMatch(/^text\/html/);
        expect(res.headers.get("content-language"), path).toBe(lang);
        expectSecurityHeaders(res);
        expect(await res.text(), path).toContain(`<html lang="${lang}">`);
      }
    }
  });

  it("names both versions of each page with hreflang, English as the default", async () => {
    for (const [en, tr] of TWINS) {
      for (const path of [en, tr]) {
        const page = await html(path);
        expect(page, path).toContain(`<link rel="alternate" hreflang="en" href="${SITE}${en}">`);
        expect(page, path).toContain(`<link rel="alternate" hreflang="tr" href="${SITE}${tr}">`);
        expect(page, path).toContain(
          `<link rel="alternate" hreflang="x-default" href="${SITE}${en}">`,
        );
      }
    }
  });

  it("puts a switcher on every page that links the same page in the other language", async () => {
    for (const [en, tr] of TWINS) {
      const english = await html(en);
      expect(english).toContain('<nav class="lang-switch" aria-label="Language">');
      expect(english).toContain(`<a href="${tr}?lang=tr" hreflang="tr" lang="tr">`);
      const turkish = await html(tr);
      expect(turkish).toContain('<nav class="lang-switch" aria-label="Dil">');
      expect(turkish).toContain(`<a href="${en}?lang=en" hreflang="en" lang="en">`);
    }
    const missing = await (await universe("/nowhere")).text();
    expect(missing).toContain('<a href="/tr/?lang=tr" hreflang="tr" lang="tr">');
    const eksik = await (await universe("/tr/nowhere")).text();
    expect(eksik).toContain('<a href="/?lang=en" hreflang="en" lang="en">');
  });

  it("keeps each language's links in that language, the docs included", async () => {
    // Assets, and the sign-in (tau-host's, one path for both languages).
    const asset = /^\/(brand|styles|static|auth)\//;
    for (const [en, tr] of TWINS) {
      for (const href of hrefs(await html(tr))) {
        const where = `${tr}: ${href}`;
        if (href.startsWith("https://")) {
          expect(href.startsWith(TURKISH_DOCS) || href.startsWith(`${SITE}/`), where).toBe(true);
        } else if (href.startsWith("/") && !asset.test(href)) {
          expect(href.startsWith("/tr/") || href.endsWith("?lang=en"), where).toBe(true);
        }
      }
      for (const href of hrefs(await html(en))) {
        const where = `${en}: ${href}`;
        expect(href.startsWith("/tr/") && !href.endsWith("?lang=tr"), where).toBe(false);
        expect(href.startsWith(TURKISH_DOCS), where).toBe(false);
      }
    }
  });

  it("gives each Turkish page the same structure as its English source", async () => {
    for (const [en, tr] of TWINS) {
      expect(ids(await html(tr)), tr).toEqual(ids(await html(en)));
    }
  });

  it("links how it works from the landing page, in the nav and under the hero", async () => {
    const english = await html("/");
    expect(english).toMatch(/<nav class="site-nav" aria-label="Main">\s*<a href="\/how-it-works">/);
    expect(english).toMatch(/<p class="hero-more">[^<]*<a href="\/how-it-works">/);
    const turkish = await html("/tr/");
    expect(turkish).toMatch(
      /<nav class="site-nav" aria-label="Ana menü">\s*<a href="\/tr\/how-it-works">/,
    );
    expect(turkish).toMatch(/<p class="hero-more">[^<]*<a href="\/tr\/how-it-works">/);
  });

  it("explains how tau works in both languages, security and start included", async () => {
    const sections = [
      "machine",
      "address",
      "talking",
      "subs",
      "visitors",
      "universe",
      "ways",
      "hacked",
      "start",
    ];
    const english = await html("/how-it-works");
    const turkish = await html("/tr/how-it-works");
    for (const id of sections) {
      expect(english, id).toMatch(new RegExp(`<section class="chapter[^"]*" id="${id}"`));
      expect(turkish, id).toMatch(new RegExp(`<section class="chapter[^"]*" id="${id}"`));
    }
    expect(english).toContain("Can I be hacked?");
    expect(english).toContain("When is Bob free on Friday?");
    expect(english).toContain(`${DOCS}getting-started/build-your-own-tau/`);
    expect(english).toContain(`${DOCS}getting-started/try-locally/`);
    expect(turkish).toContain("Hacklenebilir miyim?");
    expect(turkish).toContain("Bob cuma ne zaman müsait?");
    expect(turkish).toContain(`${TURKISH_DOCS}getting-started/build-your-own-tau/`);
    expect(turkish).toContain(`${TURKISH_DOCS}getting-started/try-locally/`);
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
    for (const path of ["/how-it-works", "/universe"]) {
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
