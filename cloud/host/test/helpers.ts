/** Shared fixtures: requests to the host, signing in, the owner's API, NDJSON streams. */

import { env, exports } from "cloudflare:workers";
import { vi } from "vitest";
import { accountsOf, tauOf } from "../src/env";

/** The host under test, as a deployed host sees it (PUBLIC_HOST is empty in the tests). */
export const HOST = "https://host.example";
/** The host as `wrangler dev` sees it: DEV_LOGIN works only here. */
export const LOCAL = "http://127.0.0.1:8791";

export function request(base: string, path: string, init: RequestInit = {}): Promise<Response> {
  return exports.default.fetch(new Request(`${base}${path}`, { redirect: "manual", ...init }));
}

/** The value of a Set-Cookie header's cookie, or null. */
export function setCookie(response: Response, name: string): string | null {
  for (const header of response.headers.getSetCookie()) {
    const [pair = ""] = header.split(";");
    const eq = pair.indexOf("=");
    if (pair.slice(0, eq).trim() === name) return pair.slice(eq + 1).trim();
  }
  return null;
}

export function setCookieHeader(response: Response, name: string): string | null {
  return response.headers.getSetCookie().find((header) => header.startsWith(`${name}=`)) ?? null;
}

export interface Owner {
  base: string;
  cookie: string;
  handle: string;
}

/** Signs in with the development login (localhost, DEV_LOGIN=1). */
export async function devSignIn(login = "alice"): Promise<Owner> {
  const response = await request(LOCAL, "/auth/dev", {
    method: "POST",
    headers: { origin: LOCAL, "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ login, next: "/app" }).toString(),
  });
  if (response.status !== 302) throw new Error(`dev sign-in: ${response.status} ${await response.text()}`);
  const token = setCookie(response, "tau_session");
  if (!token) throw new Error("dev sign-in: no session cookie");
  return { base: LOCAL, cookie: `tau_session=${token}`, handle: login.toLowerCase() };
}

/** A call to the owner's API with the session cookie and the host's Origin. */
export function api(owner: Owner, method: string, path: string, body?: unknown, headers: Record<string, string> = {}) {
  return request(owner.base, path, {
    method,
    headers: {
      cookie: owner.cookie,
      origin: owner.base,
      ...(body === undefined ? {} : { "content-type": "application/json" }),
      ...headers,
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

export async function apiJson<T = Record<string, unknown>>(
  owner: Owner,
  method: string,
  path: string,
  body?: unknown,
): Promise<{ status: number; body: T }> {
  const response = await api(owner, method, path, body);
  return { status: response.status, body: (await response.json()) as T };
}

export type Event = Record<string, unknown> & { t: string };

/** Every line of an NDJSON answer. */
export async function events(response: Response): Promise<Event[]> {
  const text = await response.text();
  return text
    .split("\n")
    .filter((line) => line.trim())
    .map((line) => JSON.parse(line) as Event);
}

/** The streamed text of a turn. */
export function streamedText(list: Event[]): string {
  return list
    .filter((event) => event.t === "text")
    .map((event) => String(event.d))
    .join("");
}

/** Signs in and finishes onboarding on the fake provider. */
export async function onboardedOwner(login = "alice", universe = false): Promise<Owner> {
  const owner = await devSignIn(login);
  const response = await api(owner, "POST", "/api/host/onboard", {
    provider: "fake",
    language: "en",
    universe,
  });
  if (response.status !== 200) throw new Error(`onboard: ${response.status} ${await response.text()}`);
  return owner;
}

export function tau(handle: string) {
  return tauOf(env, handle);
}

export function accounts() {
  return accountsOf(env);
}

/** An outbound request as the mock saw it (the body read at once, as text). */
export interface Seen {
  url: string;
  method: string;
  headers: Headers;
  body: string;
}

/**
 * Makes the answer for one request. A function, not a Response: a Response made by the test
 * cannot be read inside a Durable Object (Workers keep I/O objects to their own context).
 */
type Answer = (request: Seen) => Response | Promise<Response>;

/**
 * Replaces outbound fetch: each URL prefix answers with its function; any other URL fails
 * the test. Returns the spy and the requests it saw. Bodies are read inside the mock: a
 * Durable Object's request body cannot be read from the test later.
 */
export function mockFetch(routes: Record<string, Answer>) {
  const seen: Seen[] = [];
  const spy = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const req = new Request(input as RequestInfo, init);
    const record: Seen = {
      url: req.url,
      method: req.method,
      headers: new Headers(req.headers),
      body: new TextDecoder().decode(await req.arrayBuffer()),
    };
    seen.push(record);
    for (const [prefix, answer] of Object.entries(routes)) {
      if (req.url.startsWith(prefix)) return answer(record);
    }
    throw new TypeError(`unexpected fetch in test: ${req.method} ${req.url}`);
  });
  return { spy, seen };
}

export function sse(text: string): Response {
  return new Response(text, { status: 200, headers: { "content-type": "text/event-stream" } });
}
