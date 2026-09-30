import { reset } from "cloudflare:test";
import { env } from "cloudflare:workers";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { b64uEncode, sha256 } from "../src/crypto";
import worker from "../src/index";
import {
  accounts,
  api,
  devSignIn,
  HOST,
  LOCAL,
  mockFetch,
  request,
  setCookie,
  setCookieHeader,
} from "./helpers";

beforeEach(async () => {
  await reset();
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

/** Mocks GitHub: the token exchange and the user; returns the requests GitHub saw. */
function mockGitHub(user: { id: number; login: string }) {
  return mockFetch({
    "https://github.com/login/oauth/access_token": () => Response.json({ access_token: "gho_test", token_type: "bearer" }),
    "https://api.github.com/user": (req) =>
      req.headers.get("authorization") === "Bearer gho_test"
        ? Response.json(user)
        : new Response("unauthorized", { status: 401 }),
  });
}

/** Runs the whole OAuth web flow on https://host.example; returns the callback answer. */
async function githubSignIn(user: { id: number; login: string }, next = "/app") {
  const start = await request(HOST, `/auth/login?next=${encodeURIComponent(next)}`);
  const location = new URL(start.headers.get("location") ?? "");
  const state = location.searchParams.get("state") ?? "";
  const loginCookie = setCookie(start, "tau_login") ?? "";
  const github = mockGitHub(user);
  const done = await request(HOST, `/auth/callback?code=test-code&state=${state}`, {
    headers: { cookie: `tau_login=${loginCookie}` },
  });
  return { start, location, state, done, github };
}

describe("GitHub sign-in", () => {
  it("starts the web flow with state and a PKCE S256 challenge", async () => {
    const response = await request(HOST, "/auth/login?next=%2Fapp%2Fsettings");
    expect(response.status).toBe(302);
    const location = new URL(response.headers.get("location") ?? "");
    expect(location.origin + location.pathname).toBe("https://github.com/login/oauth/authorize");
    expect(location.searchParams.get("client_id")).toBe("test-client-id");
    expect(location.searchParams.get("redirect_uri")).toBe(`${HOST}/auth/callback`);
    expect(location.searchParams.get("code_challenge_method")).toBe("S256");
    expect(location.searchParams.get("code_challenge")).toMatch(/^[A-Za-z0-9_-]{43}$/);
    const state = location.searchParams.get("state");
    expect(state).toMatch(/^[A-Za-z0-9_-]{43}$/);
    const cookie = setCookieHeader(response, "tau_login") ?? "";
    expect(cookie).toContain(`tau_login=${state}`);
    expect(cookie).toContain("HttpOnly");
    expect(cookie).toContain("Secure");
    expect(cookie).toContain("Path=/auth");
  });

  it("signs in, sets a 30-day HttpOnly Secure Lax session and stores only its hash", async () => {
    const { location, done, github } = await githubSignIn({ id: 4242, login: "Alice" }, "/app/settings");
    expect(done.status).toBe(302);
    expect(done.headers.get("location")).toBe("/app/settings");
    const header = setCookieHeader(done, "tau_session") ?? "";
    expect(header).toMatch(/^tau_session=[A-Za-z0-9_-]{43}; /);
    for (const part of ["Path=/", "Max-Age=2592000", "HttpOnly", "SameSite=Lax", "Secure"]) {
      expect(header).toContain(part);
    }
    // The PKCE verifier sent to GitHub is the one behind the challenge.
    const tokenRequest = github.seen.find((req) => req.url.startsWith("https://github.com/login/oauth/access_token"));
    const form = new URLSearchParams(tokenRequest?.body);
    expect(form.get("client_secret")).toBe("test-client-secret");
    expect(form.get("code")).toBe("test-code");
    const verifier = form.get("code_verifier") ?? "";
    expect(b64uEncode(await sha256(verifier))).toBe(location.searchParams.get("code_challenge"));

    const token = setCookie(done, "tau_session") ?? "";
    const whoami = await request(HOST, "/api/host/whoami", { headers: { cookie: `tau_session=${token}` } });
    expect(await whoami.json()).toEqual({ handle: "alice", github_id: 4242 });

    const stored = await runInAccounts((sql) => sql.exec("SELECT hash FROM sessions").toArray());
    expect(stored).toHaveLength(1);
    expect(JSON.stringify(stored)).not.toContain(token);
  });

  it("refuses a callback whose state does not match the browser's cookie, or is reused", async () => {
    const start = await request(HOST, "/auth/login");
    const state = new URL(start.headers.get("location") ?? "").searchParams.get("state") ?? "";
    mockGitHub({ id: 1, login: "alice" });
    const wrong = await request(HOST, `/auth/callback?code=c&state=${state}`, { headers: { cookie: "tau_login=other" } });
    expect(wrong.status).toBe(400);
    const good = await request(HOST, `/auth/callback?code=c&state=${state}`, { headers: { cookie: `tau_login=${state}` } });
    expect(good.status).toBe(302);
    const again = await request(HOST, `/auth/callback?code=c&state=${state}`, { headers: { cookie: `tau_login=${state}` } });
    expect(again.status).toBe(400);
  });

  it("refuses a sign-in older than 10 minutes", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-09-30T12:00:00Z"));
    const start = await request(HOST, "/auth/login");
    const state = new URL(start.headers.get("location") ?? "").searchParams.get("state") ?? "";
    vi.setSystemTime(new Date("2026-09-30T12:10:30Z"));
    mockGitHub({ id: 1, login: "alice" });
    const late = await request(HOST, `/auth/callback?code=c&state=${state}`, { headers: { cookie: `tau_login=${state}` } });
    expect(late.status).toBe(400);
  });

  it("keeps a handle for its GitHub account and refuses another account with that login", async () => {
    const first = await githubSignIn({ id: 1, login: "alice" });
    expect(first.done.status).toBe(302);
    vi.restoreAllMocks();
    const renamed = await githubSignIn({ id: 1, login: "alice-new" });
    const token = setCookie(renamed.done, "tau_session") ?? "";
    const whoami = await request(HOST, "/api/host/whoami", { headers: { cookie: `tau_session=${token}` } });
    expect(await whoami.json()).toEqual({ handle: "alice", github_id: 1 });
    vi.restoreAllMocks();
    const squatter = await githubSignIn({ id: 2, login: "Alice" });
    expect(squatter.done.status).toBe(403);
    expect(await squatter.done.text()).toContain("already the handle of another account");
  });

  it("answers the sign-in page instead of GitHub when no OAuth App is configured", async () => {
    const handler = worker.fetch;
    const response = await handler(new Request(`${HOST}/auth/login`), { ...env, GITHUB_CLIENT_ID: "" });
    expect(response.status).toBe(503);
  });
});

async function runInAccounts<T>(fn: (sql: SqlStorage) => T): Promise<T> {
  const { runInDurableObject } = await import("cloudflare:test");
  return runInDurableObject(accounts(), (_instance, state) => fn(state.storage.sql));
}

describe("SIGNUP", () => {
  async function callbackWith(signup: string, user: { id: number; login: string }) {
    const handler = worker.fetch;
    const custom = { ...env, SIGNUP: signup };
    const start = await handler(new Request(`${HOST}/auth/login`), custom);
    const state = new URL(start.headers.get("location") ?? "").searchParams.get("state") ?? "";
    vi.restoreAllMocks();
    mockGitHub(user);
    return handler(
      new Request(`${HOST}/auth/callback?code=c&state=${state}`, { headers: { cookie: `tau_login=${state}` } }),
      custom,
    );
  }

  it("takes only the listed logins, in any case", async () => {
    expect((await callbackWith("alice, Bob", { id: 1, login: "Alice" })).status).toBe(302);
    const refused = await callbackWith("alice, Bob", { id: 3, login: "carol" });
    expect(refused.status).toBe(403);
    expect(await refused.text()).toContain("does not take new accounts");
  });

  it("closed (empty) refuses new accounts but lets existing ones in", async () => {
    expect((await callbackWith("open", { id: 1, login: "alice" })).status).toBe(302);
    expect((await callbackWith("", { id: 1, login: "alice" })).status).toBe(302);
    expect((await callbackWith("", { id: 2, login: "bob" })).status).toBe(403);
  });
});

describe("sessions", () => {
  it("whoami is 401 without a valid session", async () => {
    expect((await request(HOST, "/api/host/whoami")).status).toBe(401);
    const forged = await request(HOST, "/api/host/whoami", {
      headers: { cookie: `tau_session=${"A".repeat(43)}` },
    });
    expect(forged.status).toBe(401);
  });

  it("expires after 30 days", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-09-01T00:00:00Z"));
    const owner = await devSignIn("alice");
    expect((await api(owner, "GET", "/api/host/whoami")).status).toBe(200);
    vi.setSystemTime(new Date("2026-10-01T00:00:01Z"));
    expect((await api(owner, "GET", "/api/host/whoami")).status).toBe(401);
  });

  it("logout needs the host's Origin and ends the session", async () => {
    const owner = await devSignIn("alice");
    const foreign = await request(LOCAL, "/auth/logout", {
      method: "POST",
      headers: { cookie: owner.cookie, origin: "https://evil.example" },
    });
    expect(foreign.status).toBe(403);
    const out = await request(LOCAL, "/auth/logout", { method: "POST", headers: { cookie: owner.cookie, origin: LOCAL } });
    expect(out.status).toBe(302);
    expect(setCookieHeader(out, "tau_session")).toContain("Max-Age=0");
    expect((await api(owner, "GET", "/api/host/whoami")).status).toBe(401);
  });

  it("state-changing API calls need Origin equal to the host", async () => {
    const owner = await devSignIn("alice");
    const body = JSON.stringify({ provider: "fake", language: "en", universe: false });
    const none = await request(LOCAL, "/api/host/onboard", {
      method: "POST",
      headers: { cookie: owner.cookie, "content-type": "application/json" },
      body,
    });
    expect(none.status).toBe(403);
    const other = await request(LOCAL, "/api/host/onboard", {
      method: "POST",
      headers: { cookie: owner.cookie, origin: "http://localhost:8791", "content-type": "application/json" },
      body,
    });
    expect(other.status).toBe(403);
    expect((await api(owner, "POST", "/api/host/onboard", JSON.parse(body))).status).toBe(200);
  });

  it("uses PUBLIC_HOST as the origin when it is set", async () => {
    const handler = worker.fetch;
    const custom = { ...env, PUBLIC_HOST: "tau.example.com" };
    const start = await handler(new Request(`${HOST}/auth/login`), custom);
    expect(new URL(start.headers.get("location") ?? "").searchParams.get("redirect_uri")).toBe(
      "https://tau.example.com/auth/callback",
    );
  });
});

describe("DEV_LOGIN", () => {
  it("signs in without GitHub on 127.0.0.1", async () => {
    const owner = await devSignIn("Bob");
    const whoami = await api(owner, "GET", "/api/host/whoami");
    const body = (await whoami.json()) as { handle: string; github_id: number };
    expect(body.handle).toBe("bob");
    expect(body.github_id).toBeLessThan(0);
  });

  it("does not exist for any other host, even when it is on", async () => {
    const response = await request(HOST, "/auth/dev", {
      method: "POST",
      headers: { origin: HOST, "content-type": "application/x-www-form-urlencoded" },
      body: "login=alice",
    });
    expect(response.status).toBe(404);
    // The GitHub flow instead of the development form:
    expect((await request(HOST, "/auth/login")).headers.get("location")).toContain("github.com");
  });

  it("does not exist on localhost when it is off", async () => {
    const handler = worker.fetch;
    const response = await handler(
      new Request(`${LOCAL}/auth/dev`, {
        method: "POST",
        headers: { origin: LOCAL, "content-type": "application/x-www-form-urlencoded" },
        body: "login=alice",
      }),
      { ...env, DEV_LOGIN: "0" },
    );
    expect(response.status).toBe(404);
  });
});

describe("pages that need a session", () => {
  it("/app sends a signed-out browser to the sign-in and a signed-in one to the app", async () => {
    const out = await request(HOST, "/app/settings");
    expect(out.status).toBe(302);
    expect(out.headers.get("location")).toBe("/auth/login?next=%2Fapp%2Fsettings");
    const owner = await devSignIn("alice");
    const app = await request(LOCAL, "/app", { headers: { cookie: owner.cookie } });
    expect(app.status).toBe(200);
    expect(await app.text()).toContain('src="/app/assets/app.js"');
    const home = await request(LOCAL, "/", { headers: { cookie: owner.cookie } });
    expect(home.headers.get("location")).toBe("/app");
  });

  it("an open redirect is not possible through next", async () => {
    for (const next of ["//evil.example", "https://evil.example", "/\\evil.example"]) {
      const response = await request(LOCAL, "/auth/dev", {
        method: "POST",
        headers: { origin: LOCAL, "content-type": "application/x-www-form-urlencoded" },
        body: new URLSearchParams({ login: "alice", next }).toString(),
      });
      expect(response.headers.get("location")).toBe("/app");
    }
  });
});
