/**
 * The pages as they ship: the built Worker (dist/server/, `bun run build` first;
 * vitest.config.ts), rendered by vinext. Their words in both languages, their links, the
 * structure the Turkish twins share with the English pages, and the policy with its nonce.
 */

import { exports } from "cloudflare:workers";
import { describe, expect, it } from "vitest";

/** Each English page and its Turkish twin. */
const TWINS: readonly (readonly [string, string])[] = [
  ["/", "/tr/"],
  ["/how-it-works", "/tr/how-it-works"],
  ["/universe", "/tr/universe"],
  ["/download", "/tr/download"],
];

const ALL_PAGES = TWINS.flat();
const SITE = "https://tau.getporti.com";
const DOCS = "https://docs.tau.getporti.com/";
const TURKISH_DOCS = `${DOCS}tr/`;
/** The Mac app's disk image, from the public downloads (roadmap 190). */
const DMG = "/download/tau.dmg";
const INSTALL = "curl -fsSL https://tau.getporti.com/install.sh | sh";

function get(path: string, init?: RequestInit): Promise<Response> {
  return exports.default.fetch(new Request(`https://universe.example${path}`, init));
}

async function html(path: string): Promise<string> {
  const res = await get(path);
  expect(res.status, path).toBe(200);
  return res.text();
}

function hrefs(page: string): string[] {
  return [...page.matchAll(/\shref="([^"]*)"/g)].map((match) => match[1]!);
}

function ids(page: string): string[] {
  return [...page.matchAll(/\sid="([^"]*)"/g)].map((match) => match[1]!);
}

/** The root URL may come without its slash: `https://tau.getporti.com`. */
function siteUrl(path: string): string {
  return path === "/" ? `${SITE}/?` : `${SITE}${path}`;
}

describe("the pages", () => {
  it("serves the landing page: tau in a line, the docs, and the universe as its hero", async () => {
    const page = await html("/");
    expect(page).toContain("A personal agent that lives on your own machine.");
    expect(page).toContain(`href="${DOCS}"`);
    expect(page).toContain('href="/universe"');
    expect(page).not.toMatch(/github\.com/i);
    expect(page).toContain('<canvas class="hero-cosmos" id="cosmos" aria-hidden="true"></canvas>');
  });

  it("offers the Mac app and the one-line installer as the local way, in both languages", async () => {
    for (const [path, download, copy] of [
      ["/", "/download", "Copy"],
      ["/tr/", "/tr/download", "Kopyala"],
    ] as const) {
      const page = await html(path);
      const local = /<li class="way way-local">[\s\S]*?<\/li>/.exec(page)?.[0] ?? "";
      expect(local, path).toContain(`<a class="button" href="${download}">`);
      expect(page, path).toContain(`<code id="install-command">${INSTALL}</code>`);
      expect(page, path).toContain(
        `<button class="copy" type="button" data-copy="install-command" aria-describedby="install-command">${copy}</button>`,
      );
    }
  });

  it("serves the download page with the app, its first open, the wizard and the terminal way", async () => {
    const english = await html("/download");
    const turkish = await html("/tr/download");
    for (const page of [english, turkish]) {
      expect(page).toContain(`href="${DMG}"`);
      expect(page).toContain("macOS 13");
      for (const id of ["first-open", "first-launch", "terminal", "manual", "features"]) {
        expect(page, id).toMatch(new RegExp(`<section class="chapter" id="${id}"`));
      }
      expect(page).toContain(INSTALL);
      expect(page).toContain("curl -fsSL https://tau.getporti.com/install.sh | less");
      expect(page).toContain("TAU_INSTALL_NO_SETUP=1");
      expect(page).toContain("uv tool install tau-core --with tau-tui --with tau-net --with tau-sub");
      // The wizard's eight steps.
      expect([...page.matchAll(/<li class="chamfer">/g)]).toHaveLength(8);
    }
    expect(english).toContain("Open Anyway");
    expect(english).toContain(`${DOCS}guides/setup-features/`);
    expect(turkish).toContain("Yine de Aç");
    expect(turkish).toContain(`${TURKISH_DOCS}guides/setup-features/`);
  });

  it("serves the universe page: one canvas, the list and the join steps in its panel", async () => {
    const page = await html("/universe");
    expect(page).toContain("The tau universe");
    expect(page).toMatch(/<link rel="stylesheet" href="\/styles\/universe\.css"/);
    expect(page).toContain('id="cosmos"');
    expect(page).toContain('id="tau-list"');
    expect(page).toContain("tau net universe join");
  });

  it("answers unknown paths with the 404 page of their language", async () => {
    const res = await get("/nowhere");
    expect(res.status).toBe(404);
    const page = await res.text();
    expect(page).toContain('<html lang="en">');
    expect(page).toContain("Nothing at this address.");
    const tr = await get("/tr/nowhere");
    expect(tr.status).toBe(404);
    const sayfa = await tr.text();
    expect(sayfa).toContain('<html lang="tr">');
    expect(sayfa).toContain("Bu adreste bir şey yok.");
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
});

describe("the policy", () => {
  it("gives every page a nonce, and every script and style on it the same nonce", async () => {
    for (const path of [...ALL_PAGES, "/soon", "/claim", "/nowhere", "/tr/nowhere"]) {
      const res = await get(path);
      const policy = res.headers.get("content-security-policy") ?? "";
      const nonce = /script-src 'self' 'nonce-([A-Za-z0-9+/=]+)'/.exec(policy)?.[1];
      expect(nonce, path).toBeDefined();
      expect(policy, path).toContain(`style-src 'self' 'nonce-${nonce}'`);
      expect(policy, path).toContain("default-src 'self'");
      expect(policy, path).toContain("frame-ancestors 'none'");
      expect(res.headers.get("x-content-type-options")).toBe("nosniff");
      const page = await res.text();
      const scripts = [...page.matchAll(/<script\b[^>]*>/g)].map((match) => match[0]);
      expect(scripts.length, path).toBeGreaterThan(0);
      for (const tag of scripts) {
        expect(tag, path).toContain(`nonce="${nonce}"`);
        const src = /\bsrc="([^"]*)"/.exec(tag)?.[1];
        // Scripts come from the site itself, never from anywhere else.
        if (src !== undefined) expect(src.startsWith("/") && !src.startsWith("//"), src).toBe(true);
      }
      for (const tag of page.matchAll(/<style\b[^>]*>/g)) {
        expect(tag[0], path).toContain(`nonce="${nonce}"`);
      }
      expect(page, path).not.toMatch(/\sstyle="/);
      expect(page, path).not.toMatch(/\son[a-z]+="/);
    }
  });

  it("makes a new nonce for every page", async () => {
    const nonceOf = async () =>
      /'nonce-([^']+)'/.exec((await get("/")).headers.get("content-security-policy") ?? "")?.[1];
    expect(await nonceOf()).not.toBe(await nonceOf());
  });
});

describe("pages in two languages", () => {
  it("names both versions of each page with hreflang, English as the default", async () => {
    for (const [en, tr] of TWINS) {
      for (const path of [en, tr]) {
        const page = await html(path);
        for (const [lang, target] of [
          ["en", en],
          ["tr", tr],
          ["x-default", en],
        ] as const) {
          expect(page, `${path} ${lang}`).toMatch(
            new RegExp(`<link rel="alternate" hreflang="${lang}" href="${siteUrl(target)}"`, "i"),
          );
        }
      }
    }
  });

  it("puts a switcher on every page that links the same page in the other language", async () => {
    for (const [en, tr] of TWINS) {
      const english = await html(en);
      expect(english).toContain('<nav class="lang-switch" aria-label="Language">');
      expect(english).toMatch(new RegExp(`<a href="${tr}\\?lang=tr" hreflang="tr" lang="tr">`, "i"));
      const turkish = await html(tr);
      expect(turkish).toContain('<nav class="lang-switch" aria-label="Dil">');
      expect(turkish).toMatch(new RegExp(`<a href="${en}\\?lang=en" hreflang="en" lang="en">`, "i"));
    }
    const missing = await (await get("/nowhere")).text();
    expect(missing).toMatch(/<a href="\/tr\/\?lang=tr" hreflang="tr" lang="tr">/i);
    const eksik = await (await get("/tr/nowhere")).text();
    expect(eksik).toMatch(/<a href="\/\?lang=en" hreflang="en" lang="en">/i);
  });

  it("keeps each language's links in that language, the docs included", async () => {
    // Assets, the pages' bundles, the downloads, and the sign-in (tau-host's, one path for
    // both languages).
    const asset = /^\/(brand|styles|static|_next|auth|download)\//;
    for (const [en, tr] of TWINS) {
      for (const href of hrefs(await html(tr))) {
        const where = `${tr}: ${href}`;
        if (href.startsWith("https://")) {
          const site = href === SITE || href.startsWith(`${SITE}/`);
          expect(href.startsWith(TURKISH_DOCS) || site, where).toBe(true);
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
});
