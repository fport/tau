/**
 * The site's calls to its own API, and the development fixtures.
 *
 * Fixtures: on `localhost` or `127.0.0.1` only, `?fixture=1` on any page switches the
 * pages to built-in example data (client/fixtures.ts, loaded on demand) for the rest of
 * the tab's session, so the person, sub-tau, claim and universe pages render without a
 * directory, a tau-host or a relay behind them. `?fixture=0` switches back. On any other
 * host the switch does nothing and the fixtures are never loaded.
 */

export interface ApiResult<T> {
  /** The HTTP status; 0 when the request did not complete. */
  status: number;
  /** The parsed JSON body, or null. */
  data: T | null;
  /** The body's `error` code, when it has one. */
  error: string | null;
}

const FIXTURE_KEY = "tau.fixture";
const LOCAL_HOSTS = new Set(["localhost", "127.0.0.1", "[::1]"]);

function storage(): Storage | null {
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

/** Whether this page uses the development fixtures (see the module comment). */
export function fixtureMode(): boolean {
  if (!LOCAL_HOSTS.has(window.location.hostname)) return false;
  const store = storage();
  const asked = new URLSearchParams(window.location.search).get("fixture");
  if (asked === "1") store?.setItem(FIXTURE_KEY, "1");
  if (asked === "0") store?.removeItem(FIXTURE_KEY);
  return asked === "1" || store?.getItem(FIXTURE_KEY) === "1";
}

const useFixtures = fixtureMode();

function errorOf(data: unknown): string | null {
  if (typeof data === "object" && data !== null && "error" in data) {
    const error = (data as { error: unknown }).error;
    return typeof error === "string" ? error : null;
  }
  return null;
}

async function call<T>(method: "GET" | "POST", path: string, body?: unknown): Promise<ApiResult<T>> {
  if (useFixtures) {
    const { fixtureFetch } = await import("./fixtures");
    const { status, data } = await fixtureFetch(method, path, body);
    return { status, data: data as T | null, error: errorOf(data) };
  }
  try {
    const response = await fetch(path, {
      method,
      credentials: "same-origin",
      headers:
        body === undefined
          ? { accept: "application/json" }
          : { accept: "application/json", "content-type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    let data: unknown = null;
    if ((response.headers.get("content-type") ?? "").includes("json")) {
      data = await response.json().catch(() => null);
    } else {
      await response.body?.cancel();
    }
    return { status: response.status, data: data as T | null, error: errorOf(data) };
  } catch {
    return { status: 0, data: null, error: null };
  }
}

export function getJson<T>(path: string): Promise<ApiResult<T>> {
  return call<T>("GET", path);
}

export function postJson<T>(path: string, body: unknown): Promise<ApiResult<T>> {
  return call<T>("POST", path, body);
}
