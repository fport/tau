/**
 * Signing in with GitHub, sessions and the request checks (ADR 0013 §2).
 *
 *   GET  /auth/login?next=/app   starts the OAuth web flow (state + PKCE S256), or shows the
 *                                development sign-in form when DEV_LOGIN is on for localhost
 *   GET  /auth/callback          checks state (cookie and store), exchanges the code with the
 *                                verifier, reads the GitHub user, signs in, sets the session
 *   POST /auth/logout            ends the session
 *   POST /auth/dev               development sign-in (DEV_LOGIN=1, localhost only)
 *
 * A session is 32 random bytes in the cookie `tau_session` (HttpOnly, Secure, SameSite=Lax,
 * Path=/, 30 days); the Accounts object keeps only its SHA-256. The GitHub access token is
 * used for one request (the user's id and login) and dropped. State-changing requests must
 * carry `Origin` equal to the host.
 */

import { type SignIn, type Who, SESSION_SECONDS } from "./accounts";
import { b64uEncode, randomToken, sha256, sha256b64u } from "./crypto";
import { accountsOf, devLoginEnabled, type HostEnv, hostOrigin, isLocal, signupPolicy, tauOf } from "./env";
import { cookie, error, nowSeconds, readForm, redirect, redirectWithCookies } from "./http";
import { devLoginPage, signInErrorPage } from "./pages";

export const SESSION_COOKIE = "tau_session";
export const LOGIN_COOKIE = "tau_login";
export const GITHUB_AUTHORIZE = "https://github.com/login/oauth/authorize";
export const GITHUB_TOKEN = "https://github.com/login/oauth/access_token";
export const GITHUB_USER = "https://api.github.com/user";

/** Where to go after signing in: a path on this host, `/app` otherwise. */
export function safeNext(next: string | null): string {
  if (next === null || !next.startsWith("/") || next.startsWith("//") || next.startsWith("/\\")) return "/app";
  if (/[\u0000-\u001f\u007f]/.test(next) || next.length > 512) return "/app";
  return next;
}

/** Secure everywhere except plain http on this machine (`wrangler dev` in every browser). */
function secureFlag(url: URL): string {
  return url.protocol === "http:" && isLocal(url) ? "" : "; Secure";
}

export function sessionCookie(token: string, url: URL): string {
  return `${SESSION_COOKIE}=${token}; Path=/; Max-Age=${SESSION_SECONDS}; HttpOnly; SameSite=Lax${secureFlag(url)}`;
}

export function clearedCookie(name: string, url: URL, path = "/"): string {
  return `${name}=; Path=${path}; Max-Age=0; HttpOnly; SameSite=Lax${secureFlag(url)}`;
}

/** The signed-in account of a request, or null. */
export async function currentUser(request: Request, env: HostEnv): Promise<Who | null> {
  const token = cookie(request, SESSION_COOKIE);
  if (token === null || !/^[A-Za-z0-9_-]{43}$/.test(token)) return null;
  return accountsOf(env).session(await sha256b64u(token), nowSeconds());
}

/**
 * State-changing requests must come from the host's own pages: `Origin` equal to the host.
 * A request without `Origin` is refused too (every browser sends it on POST).
 */
export function originAllowed(request: Request, env: HostEnv, url: URL): boolean {
  return request.headers.get("origin") === hostOrigin(env, url);
}

async function pkceChallenge(verifier: string): Promise<string> {
  return b64uEncode(await sha256(verifier));
}

function callbackUrl(env: HostEnv, url: URL): string {
  return `${hostOrigin(env, url)}/auth/callback`;
}

/** Signs `who` in: a new session cookie, the tau created on first sign-in. */
async function startSession(env: HostEnv, who: Who, url: URL, next: string, extra: string[] = []): Promise<Response> {
  await tauOf(env, who.handle).ensure(who.handle, who.github_id);
  const token = randomToken(32);
  await accountsOf(env).createSession(await sha256b64u(token), who, nowSeconds());
  return redirectWithCookies(next, [sessionCookie(token, url), ...extra]);
}

async function signIn(env: HostEnv, githubId: number, login: string): Promise<SignIn> {
  const policy = signupPolicy(env);
  const allowed = policy.open || policy.logins.has(login.toLowerCase());
  return accountsOf(env).signIn(githubId, login, allowed, nowSeconds());
}

export async function login(request: Request, env: HostEnv, url: URL): Promise<Response> {
  const next = safeNext(url.searchParams.get("next"));
  if (devLoginEnabled(env, url)) return devLoginPage(request, next);
  if (!env.GITHUB_CLIENT_ID || !env.GITHUB_CLIENT_SECRET) {
    return signInErrorPage(request, "not_configured", 503);
  }
  const state = randomToken(32);
  const verifier = randomToken(32);
  await accountsOf(env).startLogin(state, verifier, next, nowSeconds());
  const target = new URL(GITHUB_AUTHORIZE);
  target.searchParams.set("client_id", env.GITHUB_CLIENT_ID);
  target.searchParams.set("redirect_uri", callbackUrl(env, url));
  target.searchParams.set("state", state);
  target.searchParams.set("code_challenge", await pkceChallenge(verifier));
  target.searchParams.set("code_challenge_method", "S256");
  target.searchParams.set("allow_signup", "true");
  return redirect(target.toString(), {
    "set-cookie": `${LOGIN_COOKIE}=${state}; Path=/auth; Max-Age=600; HttpOnly; SameSite=Lax${secureFlag(url)}`,
  });
}

interface GitHubUser {
  id: number;
  login: string;
}

async function githubUser(env: HostEnv, url: URL, code: string, verifier: string): Promise<GitHubUser | null> {
  const tokenResponse = await fetch(GITHUB_TOKEN, {
    method: "POST",
    headers: {
      accept: "application/json",
      "content-type": "application/x-www-form-urlencoded",
      "user-agent": "tau-host",
    },
    body: new URLSearchParams({
      client_id: env.GITHUB_CLIENT_ID,
      client_secret: env.GITHUB_CLIENT_SECRET,
      code,
      redirect_uri: callbackUrl(env, url),
      code_verifier: verifier,
    }).toString(),
  });
  if (!tokenResponse.ok) return null;
  const token = ((await tokenResponse.json()) as { access_token?: unknown }).access_token;
  if (typeof token !== "string" || !token) return null;
  const userResponse = await fetch(GITHUB_USER, {
    headers: {
      authorization: `Bearer ${token}`,
      accept: "application/vnd.github+json",
      "user-agent": "tau-host",
      "x-github-api-version": "2022-11-28",
    },
  });
  if (!userResponse.ok) return null;
  const user = (await userResponse.json()) as { id?: unknown; login?: unknown };
  if (typeof user.id !== "number" || !Number.isSafeInteger(user.id) || typeof user.login !== "string") return null;
  return { id: user.id, login: user.login };
}

export async function callback(request: Request, env: HostEnv, url: URL): Promise<Response> {
  const state = url.searchParams.get("state");
  const code = url.searchParams.get("code");
  const cleared = clearedCookie(LOGIN_COOKIE, url, "/auth");
  if (url.searchParams.get("error")) return signInErrorPage(request, "cancelled", 400, cleared);
  if (!state || !code || cookie(request, LOGIN_COOKIE) !== state) {
    return signInErrorPage(request, "bad_state", 400, cleared);
  }
  const pending = await accountsOf(env).takeLogin(state, nowSeconds());
  if (pending === null) return signInErrorPage(request, "bad_state", 400, cleared);
  let user: GitHubUser | null;
  try {
    user = await githubUser(env, url, code, pending.verifier);
  } catch {
    user = null;
  }
  if (user === null) return signInErrorPage(request, "github_failed", 502, cleared);
  const result = await signIn(env, user.id, user.login);
  if (!result.ok) return signInErrorPage(request, result.error, 403, cleared);
  return startSession(env, { handle: result.handle, github_id: user.id }, url, pending.next, [cleared]);
}

/** A stable, negative id for a development account (never a real GitHub id). */
async function devGithubId(login: string): Promise<number> {
  const digest = await sha256(`dev|${login.toLowerCase()}`);
  const value = ((digest[0] ?? 0) << 23) | ((digest[1] ?? 0) << 15) | ((digest[2] ?? 0) << 7) | ((digest[3] ?? 0) >> 1);
  return -(value + 1);
}

export async function devLogin(request: Request, env: HostEnv, url: URL): Promise<Response> {
  if (!devLoginEnabled(env, url)) return error(404, "not_found");
  if (!originAllowed(request, env, url)) return error(403, "bad_origin");
  const form = await readForm(request, 4096);
  const login = form?.get("login")?.trim() ?? "";
  if (!/^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$/.test(login)) {
    return signInErrorPage(request, "bad_login", 400);
  }
  const githubId = await devGithubId(login);
  const result = await signIn(env, githubId, login);
  if (!result.ok) return signInErrorPage(request, result.error, 403);
  return startSession(env, { handle: result.handle, github_id: githubId }, url, safeNext(form?.get("next") ?? null));
}

export async function logout(request: Request, env: HostEnv, url: URL): Promise<Response> {
  if (!originAllowed(request, env, url)) return error(403, "bad_origin");
  const token = cookie(request, SESSION_COOKIE);
  if (token !== null && /^[A-Za-z0-9_-]{43}$/.test(token)) {
    await accountsOf(env).endSession(await sha256b64u(token));
  }
  return redirectWithCookies("/", [clearedCookie(SESSION_COOKIE, url)]);
}
