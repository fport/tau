/** The rendered pages, their headers, and the two message tables. */

import { reset } from "cloudflare:test";
import { beforeEach, describe, expect, it } from "vitest";
import { MESSAGES } from "../client/messages";
import { PAGE_MESSAGES } from "../src/i18n";
import { CONTENT_SECURITY_POLICY, escapeHtml, jsonForHtml } from "../src/pages";
import { HOST, LOCAL, request } from "./helpers";

beforeEach(async () => {
  await reset();
});

describe("pages", () => {
  it("the landing page has the security headers, the sign-in and the privacy note", async () => {
    const page = await request(HOST, "/");
    expect(page.status).toBe(200);
    expect(page.headers.get("content-security-policy")).toBe(CONTENT_SECURITY_POLICY);
    expect(page.headers.get("x-content-type-options")).toBe("nosniff");
    expect(page.headers.get("x-frame-options")).toBe("DENY");
    const html = await page.text();
    expect(html).toContain('href="/auth/login?next=%2Fapp"');
    expect(html).toContain("Its operator can read your chats");
    expect(html).not.toContain("/auth/dev"); // DEV_LOGIN works on localhost only
    expect(html).not.toMatch(/<script(?![^>]*\bsrc=)(?![^>]*application\/json)/);
    expect(html).not.toContain("style=");
  });

  it("offers the development sign-in on localhost", async () => {
    const html = await (await request(LOCAL, "/")).text();
    expect(html).toContain('action="/auth/dev"');
  });

  it("speaks Turkish when asked", async () => {
    const byQuery = await (await request(HOST, "/?lang=tr")).text();
    expect(byQuery).toContain('<html lang="tr">');
    const byHeader = await (await request(HOST, "/", { headers: { "accept-language": "tr-TR,tr;q=0.9,en;q=0.5" } })).text();
    expect(byHeader).toContain('<html lang="tr">');
    const byCookie = await (await request(HOST, "/", { headers: { cookie: "lang=tr" } })).text();
    expect(byCookie).toContain('<html lang="tr">');
  });

  it("answers unknown paths with the 404 page and unknown API paths with JSON", async () => {
    const page = await request(HOST, "/nothing/here");
    expect(page.status).toBe(404);
    expect(page.headers.get("content-type")).toContain("text/html");
    const apiMiss = await request(HOST, "/api/nothing");
    expect(apiMiss.status).toBe(404);
    expect(await apiMiss.json()).toEqual({ error: "not_found" });
    // The network routes belong to issue 162.
    expect((await request(HOST, "/@alice/.well-known/tau.json")).status).toBe(404);
    expect((await request(HOST, "/@alice/net/inbox", { method: "POST" })).status).toBe(405);
  });

  it("escapes HTML and keeps JSON inert inside a script block", () => {
    expect(escapeHtml(`<a href="x">'&'</a>`)).toBe("&lt;a href=&quot;x&quot;&gt;&#39;&amp;&#39;&lt;/a&gt;");
    expect(jsonForHtml({ about: "</script><script>alert(1)</script>" })).not.toContain("</script>");
  });
});

describe("message tables", () => {
  it("the app's English and Turkish tables have the same keys", () => {
    expect(Object.keys(MESSAGES.tr).sort()).toEqual(Object.keys(MESSAGES.en).sort());
    for (const key of Object.keys(MESSAGES.en) as (keyof typeof MESSAGES.en)[]) {
      expect(typeof MESSAGES.tr[key]).toBe(typeof MESSAGES.en[key]);
    }
  });

  it("the pages' English and Turkish tables have the same keys", () => {
    expect(Object.keys(PAGE_MESSAGES.tr).sort()).toEqual(Object.keys(PAGE_MESSAGES.en).sort());
  });
});
