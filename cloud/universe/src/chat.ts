/**
 * The visitor chat API (ADR 0013 §5; §5 of docs/reference/tau-universe.md): anonymous
 * visitors talk to public web sub-taus on their pages.
 *
 *   POST /api/chat/<target>                   {text, thread?} → {thread, id, n}
 *   GET  /api/chat/<target>/<thread>?after=<n>&wait=<s>
 *                                             → {messages, pending, state}
 *
 * `<target>` is a slug (`coach`) or a handle and a name (`@alice/coach`), resolved through
 * the directory like the sub-tau page. A visitor is the random cookie `tau_visitor`; a thread
 * belongs to the cookie that started it. The universe relays each message and keeps the
 * thread in a Relay object (src/relay.ts) for 24 hours:
 *
 * - **hosted** sub-taus (a tau at `<universe>/@<handle>`) are answered by tau-host through the
 *   `HOST` binding: `POST /api/visit/<handle>/<name>` with `{visitor, thread?, text}`;
 * - **hub-run** sub-taus get a sealed `visit` envelope from the universe's own identity
 *   (src/identity.ts), posted to their tau's inbox; the hub's answer comes back to
 *   `POST /net/inbox` (src/inbox.ts).
 *
 * The send returns as soon as the message is stored; the delivery runs after it
 * (`ctx.waitUntil`) and its outcome shows in the thread. Visitor text is never logged and
 * never rendered here: it is stored and returned as JSON strings.
 */

import {
  b64uEncode,
  buildEnvelope,
  encodeEnvelope,
  fetchCard,
  inboxUrl,
  isId,
  isPlainAddress,
  MAX_MESSAGE_CHARS,
  newId,
  randomBytes,
  utf8Encode,
} from "../../shared/net/index.ts";
import { hostedHandle, insecurePeersAllowed, isHandle, universeHost } from "./address";
import { directoryOf, relayOf, type UniverseEnv } from "./env";
import {
  badRequest,
  error,
  intParam,
  isObject,
  json,
  methodNotAllowed,
  notFound,
  nowSeconds,
  parseJson,
  readLimited,
  utf8,
} from "./http";
import { universeIdentity } from "./identity";
import { clientKey, withinLimit } from "./limits";
import { SUB_NAME } from "./protocol";
import type { TargetRef, ThreadState, ThreadTarget } from "./relay";
import { SOFTWARE } from "./version";

/** The longest visitor message, as JavaScript counts characters (tau-host's limit). */
export const MAX_TEXT_CHARS = 2_000;
export const MAX_CHAT_BODY_BYTES = 16_384;
/** The longest a poll waits for news. */
export const MAX_WAIT_SECONDS = 25;
/** How often a waiting poll reads the thread again. */
export const POLL_STEP_MS = 2_000;
export const VISITOR_COOKIE = "tau_visitor";
const VISITOR_COOKIE_MAX_AGE = 31_536_000;
const VISITOR_TOKEN = /^[A-Za-z0-9_-]{22,64}$/;
/** tau-host runs a model turn; `waitUntil` allows about 30 s after the response. */
const HOST_TIMEOUT_MS = 28_000;
const INBOX_TIMEOUT_MS = 10_000;

/** A chat path: the target and, for a poll, the thread. */
interface ChatPath {
  ref: TargetRef;
  thread: string | null;
}

/**
 * `/api/chat/<slug>[/<thread>]` or `/api/chat/@<handle>/<name>[/<thread>]`; null for any
 * other shape (the handle is case-insensitive, like the pages).
 */
export function parseChatPath(path: string): ChatPath | null {
  if (!path.startsWith("/api/chat/")) return null;
  const parts = path.slice("/api/chat/".length).split("/");
  let ref: TargetRef;
  let rest: string[];
  const first = parts[0] ?? "";
  if (first.startsWith("@")) {
    const handle = first.slice(1).toLowerCase();
    const name = parts[1] ?? "";
    if (!isHandle(handle) || !SUB_NAME.test(name)) return null;
    ref = { handle, name };
    rest = parts.slice(2);
  } else {
    if (!SUB_NAME.test(first)) return null;
    ref = { slug: first };
    rest = parts.slice(1);
  }
  if (rest.length === 0) return { ref, thread: null };
  if (rest.length === 1 && isId(rest[0])) return { ref, thread: rest[0]! };
  return null;
}

/** The visitor token of the request's `tau_visitor` cookie, or null. */
export function visitorToken(request: Request): string | null {
  const header = request.headers.get("cookie");
  if (header === null) return null;
  for (const part of header.split(";")) {
    const eq = part.indexOf("=");
    if (eq === -1 || part.slice(0, eq).trim() !== VISITOR_COOKIE) continue;
    const value = part.slice(eq + 1).trim();
    return VISITOR_TOKEN.test(value) ? value : null;
  }
  return null;
}

/**
 * The visitor id stored with a thread and sent to tau-host: the SHA-256 of the cookie, so
 * neither the Relay nor tau-host ever holds the cookie itself (43 base64url characters).
 */
export async function visitorId(token: string): Promise<string> {
  const digest = await crypto.subtle.digest(
    "SHA-256",
    utf8Encode(`tau-universe/1 visitor|${token}`),
  );
  return b64uEncode(new Uint8Array(digest));
}

function visitorCookie(token: string, url: URL): string {
  const secure = url.protocol === "https:" ? "; Secure" : "";
  return (
    `${VISITOR_COOKIE}=${token}; Path=/api/chat; Max-Age=${VISITOR_COOKIE_MAX_AGE}; ` +
    `HttpOnly; SameSite=Lax${secure}`
  );
}

function isJsonRequest(request: Request): boolean {
  const type = request.headers.get("content-type") ?? "";
  return type.split(";", 1)[0]!.trim().toLowerCase() === "application/json";
}

/** Every /api/chat/* request. */
export async function handleChat(
  request: Request,
  env: UniverseEnv,
  url: URL,
  ctx: ExecutionContext | undefined,
): Promise<Response> {
  const path = parseChatPath(url.pathname);
  if (path === null) return notFound();
  if (path.thread === null) {
    if (request.method !== "POST") return methodNotAllowed(["POST"]);
    return send(request, env, url, ctx, path.ref);
  }
  if (request.method !== "GET") return methodNotAllowed(["GET"]);
  return poll(request, env, url, path.ref, path.thread);
}

// -- sending -----------------------------------------------------------------------------------

type SendBody =
  | { ok: true; text: string; thread: string | null }
  | { ok: false; response: Response };

async function readSendBody(request: Request): Promise<SendBody> {
  const bytes = await readLimited(
    request.body,
    MAX_CHAT_BODY_BYTES,
    request.headers.get("content-length"),
  );
  if (bytes === null) return { ok: false, response: error(413, "too_large") };
  const decoded = utf8(bytes);
  const value = decoded === null ? undefined : parseJson(decoded);
  if (!isObject(value)) return { ok: false, response: badRequest("body must be a JSON object") };
  if (typeof value.text !== "string") {
    return { ok: false, response: badRequest("text must be a string") };
  }
  const text = value.text.trim();
  if (text === "" || text.length > MAX_TEXT_CHARS) {
    return {
      ok: false,
      response: badRequest(`text must have 1-${MAX_TEXT_CHARS} characters`),
    };
  }
  const thread = value.thread;
  if (thread !== undefined && thread !== null && !isId(thread)) {
    return { ok: false, response: badRequest("thread is not a thread id") };
  }
  return { ok: true, text, thread: typeof thread === "string" ? thread : null };
}

async function send(
  request: Request,
  env: UniverseEnv,
  url: URL,
  ctx: ExecutionContext | undefined,
  ref: TargetRef,
): Promise<Response> {
  // 1. A same-origin JSON request: no other site posts in a visitor's name.
  if (!isJsonRequest(request)) {
    await request.body?.cancel();
    return error(415, "unsupported_media_type");
  }
  if (request.headers.get("origin") !== url.origin) {
    await request.body?.cancel();
    return error(403, "bad_origin");
  }

  // 2. 10 messages a minute per client IP, before anything that costs more than CPU.
  const ip = clientKey(request.headers.get("cf-connecting-ip"));
  if (ip !== null && !(await withinLimit(env, "CHAT_IP_LIMIT", ip))) {
    await request.body?.cancel();
    return error(429, "rate_limited");
  }

  // 3. The body.
  const body = await readSendBody(request);
  if (!body.ok) return body.response;

  // 4. The sub-tau: listed, with a web page, and reachable from here.
  const now = nowSeconds();
  const self = universeHost(env, url);
  const sub = await directoryOf(env).sub(ref, self, now);
  if (sub === null) return notFound();
  if (!sub.web) return error(403, "not_web");
  const address = sub.owner.address;
  const handle = hostedHandle(address, self);
  if (handle !== null ? env.HOST === undefined : !(await relayReady(env, self))) {
    return error(503, "unavailable");
  }
  const target: ThreadTarget = {
    address,
    name: sub.name,
    slug: sub.slug,
    handle: sub.owner.handle,
    hosted: handle !== null,
  };

  // 5. The visitor, and the thread.
  const known = visitorToken(request);
  const token = known ?? b64uEncode(randomBytes(24));
  const visitor = await visitorId(token);
  const thread = body.thread ?? newId();
  const visit = newId();
  const relay = relayOf(env, thread);
  const outcome = await relay.send({
    create: body.thread === null,
    visitor,
    target,
    text: body.text,
    visit,
    now,
  });
  if (!outcome.ok) {
    return outcome.error === "not_found" ? notFound() : error(409, outcome.error);
  }

  // 6. The delivery, after the answer.
  const job = { env, self, thread, visit, visitor, text: body.text, target };
  const delivery =
    handle !== null
      ? deliverHosted({ ...job, handle, hostThread: outcome.hostThread })
      : deliverVisit(job);
  if (ctx !== undefined) ctx.waitUntil(delivery);
  else await delivery;

  const headers: Record<string, string> = { "cache-control": "no-store" };
  if (known === null) headers["set-cookie"] = visitorCookie(token, url);
  return json({ thread, id: visit, n: outcome.n }, 200, headers);
}

/** Whether visits to hub-run sub-taus can go out: an identity and a plain own host. */
async function relayReady(env: UniverseEnv, self: string): Promise<boolean> {
  return isPlainAddress(self) && (await universeIdentity(env)) !== null;
}

interface Delivery {
  env: UniverseEnv;
  self: string;
  thread: string;
  visit: string;
  visitor: string;
  text: string;
  target: ThreadTarget;
}

async function fail(job: Delivery, state: Exclude<ThreadState, "open">): Promise<void> {
  await relayOf(job.env, job.thread).fail({ visit: job.visit, state, now: nowSeconds() });
}

/** tau-host's error codes that mean "not now, and not before tomorrow or a new budget". */
const RESTING = new Set(["daily_cap", "budget"]);

/**
 * A hosted sub-tau: `POST https://<universe>/api/visit/<handle>/<name>` through `HOST` with
 * `{visitor, thread?, text}`, where `thread` is tau-host's own thread id (absent on the
 * first message). `200 {thread, reply: {id, text, ts}}` puts the answer in the thread. No
 * `Origin` and no client IP go along: the universe checked both.
 */
async function deliverHosted(
  job: Delivery & { handle: string; hostThread: string | null },
): Promise<void> {
  const host = job.env.HOST;
  if (host === undefined) return fail(job, "unavailable");
  const call = async (hostThread: string | null): Promise<{ status: number; body: unknown }> => {
    const payload: Record<string, string> = { visitor: job.visitor, text: job.text };
    if (hostThread !== null) payload.thread = hostThread;
    const response = await host.fetch(
      `https://${job.self}/api/visit/${job.handle}/${job.target.name}`,
      {
        method: "POST",
        headers: {
          "content-type": "application/json",
          accept: "application/json",
          "user-agent": SOFTWARE,
        },
        body: JSON.stringify(payload),
        signal: AbortSignal.timeout(HOST_TIMEOUT_MS),
      },
    );
    const text = await response.text();
    return { status: response.status, body: parseJson(text) };
  };
  let answer: { status: number; body: unknown };
  try {
    answer = await call(job.hostThread);
    // tau-host forgot its thread (it keeps them 24 hours too): continue in a new one.
    if (answer.status === 404 && codeOf(answer.body) === "unknown_thread" && job.hostThread) {
      answer = await call(null);
    }
  } catch (err) {
    console.warn(JSON.stringify({ event: "visit_host_failed", error: String(err) }));
    return fail(job, "unavailable");
  }
  const relay = relayOf(job.env, job.thread);
  const now = nowSeconds();
  if (answer.status === 200 && isObject(answer.body)) {
    const reply = answer.body.reply;
    const hostThread = typeof answer.body.thread === "string" ? answer.body.thread : null;
    if (isObject(reply) && typeof reply.text === "string") {
      await relay.answer({
        visit: job.visit,
        text: reply.text.slice(0, MAX_MESSAGE_CHARS),
        replyId: typeof reply.id === "string" ? reply.id : String(reply.id ?? ""),
        hostThread,
        now,
      });
      return;
    }
  }
  const code = codeOf(answer.body);
  if (code === "no_reply") {
    // The sub-tau chose not to answer: the visit is done, the thread stays open.
    await relay.answer({ visit: job.visit, text: null, replyId: "", hostThread: null, now });
    return;
  }
  console.warn(
    JSON.stringify({ event: "visit_host_refused", status: answer.status, error: code ?? "" }),
  );
  if (code !== null && RESTING.has(code)) return fail(job, "resting");
  if (code === "thread_full") return fail(job, "full");
  return fail(job, "unavailable");
}

function codeOf(body: unknown): string | null {
  return isObject(body) && typeof body.error === "string" ? body.error.slice(0, 64) : null;
}

/**
 * A hub-run sub-tau: a `visit` envelope from the universe to the tau's address, sealed to
 * the box key of its card, with `thread` the visitor's thread and `id` the visit's id,
 * posted to `<scheme>://<address>/net/inbox`. `202`, or `200 duplicate`, is delivered; the
 * hub's answer arrives at /net/inbox. The owner's hub may be offline: its spine keeps the
 * visit until it is back.
 */
async function deliverVisit(job: Delivery): Promise<void> {
  const identity = await universeIdentity(job.env);
  if (identity === null) return fail(job, "unavailable");
  const address = job.target.address;
  const allowInsecure = insecurePeersAllowed(job.env);
  try {
    const card = await fetchCard(address, { allowInsecure, userAgent: SOFTWARE });
    if (card === null) {
      console.warn(JSON.stringify({ event: "visit_card_unavailable", address }));
      return fail(job, "unavailable");
    }
    const built = await buildEnvelope(identity, {
      from: job.self,
      to: address,
      recipientBoxKey: card.box_key,
      kind: "visit",
      content: { text: job.text, sub: job.target.name },
      id: job.visit,
      thread: job.thread,
      replyTo: null,
      hops: 0,
    });
    const response = await fetch(inboxUrl(address, allowInsecure), {
      method: "POST",
      headers: {
        "content-type": "application/json",
        accept: "application/json",
        "user-agent": SOFTWARE,
      },
      body: encodeEnvelope(built.envelope),
      redirect: "manual",
      signal: AbortSignal.timeout(INBOX_TIMEOUT_MS),
    });
    const body = parseJson(await response.text());
    const duplicate =
      response.status === 200 && isObject(body) && body.status === "duplicate";
    if (response.status === 202 || duplicate) return;
    console.warn(
      JSON.stringify({
        event: "visit_refused",
        address,
        status: response.status,
        error: codeOf(body) ?? "",
      }),
    );
  } catch (err) {
    console.warn(JSON.stringify({ event: "visit_failed", address, error: String(err) }));
  }
  return fail(job, "unavailable");
}

// -- polling -----------------------------------------------------------------------------------

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * GET /api/chat/<target>/<thread>?after=<n>&wait=<s>: the messages after `n`. While a
 * message awaits its answer and nothing newer is there, the request waits up to `wait`
 * seconds (25 by default and at most), reading the thread every POLL_STEP_MS. It returns at
 * once when there is news, when nothing is pending, or with `wait=0`.
 */
async function poll(
  request: Request,
  env: UniverseEnv,
  url: URL,
  ref: TargetRef,
  thread: string,
): Promise<Response> {
  const after = intParam(url, "after", 0);
  const wait = intParam(url, "wait", MAX_WAIT_SECONDS);
  if (after === null) return badRequest("after must be a non-negative integer");
  if (wait === null || wait > MAX_WAIT_SECONDS) {
    return badRequest(`wait must be an integer from 0 to ${MAX_WAIT_SECONDS}`);
  }
  const token = visitorToken(request);
  if (token === null) return notFound();
  const visitor = await visitorId(token);
  const relay = relayOf(env, thread);
  const deadline = Date.now() + wait * 1000;
  for (;;) {
    const view = await relay.read({ visitor, ref, after, now: nowSeconds() });
    if (view === null) return notFound();
    const left = deadline - Date.now();
    if (view.messages.length > 0 || !view.pending || left <= 0) {
      return json(view, 200, { "cache-control": "no-store" });
    }
    await sleep(Math.min(POLL_STEP_MS, left));
  }
}
