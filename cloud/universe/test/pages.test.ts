import { describe, expect, it } from "vitest";
import headersFile from "../public/_headers?raw";
import { CONTENT_SECURITY_POLICY } from "../src/pages";
import { universe } from "./helpers";

const EXPECTED_CSP =
  "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; " +
  "connect-src 'self'; frame-ancestors 'none'";

function expectSecurityHeaders(res: Response): void {
  expect(res.headers.get("content-security-policy")).toBe(EXPECTED_CSP);
  expect(res.headers.get("x-content-type-options")).toBe("nosniff");
  expect(res.headers.get("referrer-policy")).toBe("strict-origin-when-cross-origin");
}

describe("pages", () => {
  it("serves the landing page at / with the security headers", async () => {
    const res = await universe("/");
    expect(res.status).toBe(200);
    expect(res.headers.get("content-type")).toMatch(/^text\/html/);
    expectSecurityHeaders(res);
    const html = await res.text();
    expect(html).toContain("A personal agent that lives on your own machine.");
    expect(html).toContain('href="https://docs.tau.getporti.com/"');
    expect(html).toContain('href="/universe"');
    expect(html).not.toMatch(/github\.com/i);
  });

  it("serves the universe page at /universe with the security headers", async () => {
    const res = await universe("/universe");
    expect(res.status).toBe(200);
    expect(res.headers.get("content-type")).toMatch(/^text\/html/);
    expectSecurityHeaders(res);
    const html = await res.text();
    expect(html).toContain("The tau universe");
    expect(html).toContain('<script type="module" src="/app/universe.js"></script>');
  });

  it("answers HEAD for the pages", async () => {
    const res = await universe("/", { method: "HEAD" });
    expect(res.status).toBe(200);
    expectSecurityHeaders(res);
  });

  it("keeps the pages free of inline scripts and styles (the CSP would block them)", async () => {
    for (const path of ["/", "/universe"]) {
      const html = await (await universe(path)).text();
      expect(html).not.toMatch(/<script(?![^>]*\bsrc=)[^>]*>/);
      expect(html).not.toMatch(/<style[\s>]/);
      expect(html).not.toMatch(/\sstyle="/);
      expect(html).not.toMatch(/\son[a-z]+="/);
    }
  });

  it("answers unknown paths with the 404 page and the security headers", async () => {
    const res = await universe("/nowhere");
    expect(res.status).toBe(404);
    expect(res.headers.get("content-type")).toMatch(/^text\/html/);
    expectSecurityHeaders(res);
    expect(await res.text()).toContain("Nothing at this address.");
  });

  it("refuses other methods on pages", async () => {
    const res = await universe("/", { method: "POST" });
    expect(res.status).toBe(405);
    expect(res.headers.get("allow")).toBe("GET");
    expectSecurityHeaders(res);
  });

  it("puts the same policy into public/_headers for /404", () => {
    expect(CONTENT_SECURITY_POLICY).toBe(EXPECTED_CSP);
    const rule = headersFile.split(/\n\s*\n/).find((block) => /^\/404$/m.test(block));
    expect(rule).toBeDefined();
    expect(rule).toContain(`Content-Security-Policy: ${EXPECTED_CSP}`);
    expect(headersFile).toContain("X-Content-Type-Options: nosniff");
    expect(headersFile).toContain("Referrer-Policy: strict-origin-when-cross-origin");
  });
});
