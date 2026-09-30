/**
 * ADR 0013 §5 on the universe: its network identity (card and inbox), the Relay of visitor
 * threads and the chat API. Hosted sub-taus answer through a fake tau-host behind `HOST`;
 * hub-run sub-taus get their `visit` envelopes from a fake spine (a mocked fetch), and the
 * tests answer them as the hub would, with envelopes built by cloud/shared/net.
 */

import {
  createExecutionContext,
  reset,
  runDurableObjectAlarm,
  runInDurableObject,
  waitOnExecutionContext,
} from "cloudflare:test";
import { env } from "cloudflare:workers";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import {
  b64uDecode,
  type BuildOptions,
  buildEnvelope,
  Identity,
  openEnvelope,
  type OpenedEnvelope,
  type WireEnvelope,
} from "../../shared/net/index.ts";
import { parseChatPath, visitorId, visitorToken } from "../src/chat";
import type { UniverseEnv } from "../src/env";
import worker from "../src/index";
import { clientKey } from "../src/limits";
import { HUB_PENDING_SECONDS, MAX_THREAD_MESSAGES, THREAD_TTL_SECONDS } from "../src/relay";
import { SOFTWARE } from "../src/version";
import {
  ALICE,
  BOB,
  CAROL,
  card,
  FakeHost,
  mockCards,
  mockTaus,
  nowSeconds,
  prepareTaus,
  resetClocks,
  send,
  sendVia,
  type Tau,
  UNIVERSE,
} from "./helpers";

/** A tau hosted by the fake tau-host on the universe's own host. */
const DANA: Tau = { address: `${UNIVERSE}/@dana`, name: "Dana's tau", seed: "", signKey: "" };

const ORIGIN = `https://${UNIVERSE}`;
const COACH = { name: "coach", about: "Runs with you", web: true, starters: ["Hi"] };
const NOTES = { name: "notes", about: "Private-ish notes", web: false };
const HELPER = { name: "helper", about: "Helps", web: true };

let universeIdentity: Identity;
let identityValue: string;
/** Alice's hub: Alice's signing seed and the box seed of card(ALICE) (bytes 0x20..0x3f). */
let hubIdentity: Identity;

beforeAll(async () => {
  await prepareTaus();
  Object.assign(DANA, { seed: CAROL.seed, signKey: CAROL.signKey });
  universeIdentity = await Identity.generate();
  identityValue = universeIdentity.toEnvValue();
  hubIdentity = await Identity.fromSeeds(b64uDecode(ALICE.seed)!, b64uDecode(BOB.seed)!);
});
beforeEach(async () => {
  await reset();
  resetClocks();
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

// -- requests ----------------------------------------------------------------------------------

interface CallOptions extends RequestInit {
  bindings?: Partial<UniverseEnv>;
}

/** A request to the universe with its identity, waiting for everything it left running. */
async function call(path: string, options: CallOptions = {}): Promise<Response> {
  const { bindings, ...init } = options;
  const ctx = createExecutionContext();
  const res = await worker.fetch(
    new Request(`https://${UNIVERSE}${path}`, init),
    { ...env, UNIVERSE_IDENTITY: identityValue, ...bindings },
    ctx,
  );
  await waitOnExecutionContext(ctx);
  return res;
}

interface ChatOptions {
  cookie?: string | null;
  ip?: string;
  origin?: string | null;
  contentType?: string;
  bindings?: Partial<UniverseEnv>;
}

function chatPost(target: string, body: unknown, options: ChatOptions = {}): Promise<Response> {
  const headers: Record<string, string> = {
    "content-type": options.contentType ?? "application/json",
  };
  const origin = options.origin === undefined ? ORIGIN : options.origin;
  if (origin !== null) headers.origin = origin;
  if (options.cookie) headers.cookie = `lang=en; tau_visitor=${options.cookie}`;
  if (options.ip) headers["cf-connecting-ip"] = options.ip;
  return call(`/api/chat/${target}`, {
    method: "POST",
    headers,
    body: typeof body === "string" ? body : JSON.stringify(body),
    bindings: options.bindings,
  });
}

function chatGet(
  target: string,
  thread: string,
  cookie: string | null,
  query = "after=0&wait=0",
  bindings?: Partial<UniverseEnv>,
): Promise<Response> {
  const headers: Record<string, string> = {};
  if (cookie !== null) headers.cookie = `tau_visitor=${cookie}`;
  return call(`/api/chat/${target}/${thread}?${query}`, { headers, bindings });
}

function cookieOf(res: Response): string {
  const header = res.headers.get("set-cookie") ?? "";
  const token = /tau_visitor=([^;]+)/.exec(header)?.[1];
  if (token === undefined) throw new Error(`no visitor cookie in ${JSON.stringify(header)}`);
  return token;
}

interface Sent {
  thread: string;
  id: string;
  n: number;
}

async function sent(res: Response): Promise<Sent> {
  expect(res.status).toBe(200);
  return (await res.json()) as Sent;
}

interface View {
  messages: { n: number; from: string; text: string; ts: number }[];
  pending: boolean;
  state: string;
}

async function view(res: Response): Promise<View> {
  expect(res.status).toBe(200);
  return (await res.json()) as View;
}

// -- the directory -----------------------------------------------------------------------------

/** Alice's hub lists /coach (web) and /notes (no web page); /coach takes the slug. */
async function listAlice(): Promise<void> {
  mockTaus(ALICE);
  expect((await send("join", ALICE)).status).toBe(200);
  expect((await send("report", ALICE, { subs: [COACH, NOTES] })).status).toBe(200);
  vi.restoreAllMocks();
}

/** Dana, hosted by `host`, lists /helper (web). */
async function listDana(host: FakeHost): Promise<void> {
  mockCards({});
  host.hosts(DANA);
  expect((await sendVia(host, "join", DANA)).status).toBe(200);
  expect((await sendVia(host, "report", DANA, { subs: [HELPER] })).status).toBe(200);
  vi.restoreAllMocks();
}

// -- a fake spine for Alice's hub --------------------------------------------------------------

/**
 * Replaces outbound fetch: serves the cards it knows and takes envelopes at Alice's inbox
 * (`https://alice.example/net/inbox`), answering with `inbox` (202 queued by default).
 */
class FakeSpine {
  readonly envelopes: WireEnvelope[] = [];
  readonly requests: Request[] = [];
  readonly cards = new Map<string, Record<string, unknown>>();
  inbox: (wire: WireEnvelope) => Response = (wire) =>
    Response.json({ status: "queued", id: idOf(wire) }, { status: 202 });

  constructor(...taus: Tau[]) {
    for (const tau of taus) {
      this.cards.set(`https://${tau.address}/.well-known/tau.json`, card(tau));
    }
  }

  install() {
    return vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const request = new Request(input as RequestInfo, init);
      this.requests.push(request.clone());
      const known = this.cards.get(request.url);
      if (known !== undefined && request.method === "GET") return Response.json(known);
      if (request.url === `https://${ALICE.address}/net/inbox` && request.method === "POST") {
        const wire = (await request.json()) as WireEnvelope;
        this.envelopes.push(wire);
        return this.inbox(wire);
      }
      throw new TypeError(`unexpected fetch in test: ${request.method} ${request.url}`);
    });
  }

  /** The n-th visit as Alice's hub opens it. */
  async visit(index = -1): Promise<OpenedEnvelope> {
    const wire = this.envelopes.at(index);
    if (wire === undefined) throw new Error("no visit reached the spine");
    return openEnvelope(wire, universeIdentity.signKey, hubIdentity);
  }
}

function idOf(wire: WireEnvelope): string {
  const bytes = b64uDecode(wire.payload)!;
  return (JSON.parse(new TextDecoder().decode(bytes)) as { id: string }).id;
}

/** The hub's answer to a visit: a `message` to the universe, as tau-net builds it. */
async function hubAnswer(
  visit: OpenedEnvelope,
  text: string,
  overrides: Partial<BuildOptions> = {},
  signer: Identity = hubIdentity,
): Promise<WireEnvelope> {
  const built = await buildEnvelope(signer, {
    from: ALICE.address,
    to: UNIVERSE,
    recipientBoxKey: universeIdentity.boxKey,
    kind: "message",
    content: { text, sub: "coach" },
    thread: visit.payload.thread,
    replyTo: visit.payload.id,
    hops: visit.payload.hops + 1,
    ...overrides,
  });
  return built.envelope;
}

function inbox(
  wire: unknown,
  options: { contentType?: string; bindings?: Partial<UniverseEnv>; ip?: string } = {},
): Promise<Response> {
  const headers: Record<string, string> = {
    "content-type": options.contentType ?? "application/json",
  };
  if (options.ip) headers["cf-connecting-ip"] = options.ip;
  return call("/net/inbox", {
    method: "POST",
    headers,
    body: typeof wire === "string" ? wire : JSON.stringify(wire),
    bindings: options.bindings,
  });
}

/** A fake tau-host visitor API that answers every visit with `text` in tau-host's `thread`. */
function replying(text = "Hi from helper", thread = "host-thread-1") {
  let id = 0;
  return (_request: Request, _body: unknown) =>
    Response.json({ thread, reply: { id: String(++id), text, ts: nowSeconds() } });
}

// -- the universe's identity -------------------------------------------------------------------

describe("the universe's card", () => {
  it("is 404 no_card without UNIVERSE_IDENTITY", async () => {
    const res = await call("/.well-known/tau.json", { bindings: { UNIVERSE_IDENTITY: "" } });
    expect(res.status).toBe(404);
    expect(await res.json()).toEqual({ error: "no_card" });
  });

  it("is 404 no_card with an identity that cannot be read", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const res = await call("/.well-known/tau.json", {
      bindings: { UNIVERSE_IDENTITY: "not-an-identity" },
    });
    expect(res.status).toBe(404);
    for (const args of warn.mock.calls) expect(JSON.stringify(args)).not.toContain("not-an");
  });

  it("names the universe's host, its keys and its inbox", async () => {
    const res = await call("/.well-known/tau.json");
    expect(res.status).toBe(200);
    expect(res.headers.get("access-control-allow-origin")).toBe("*");
    expect(res.headers.get("cache-control")).toBe("public, max-age=300");
    expect(await res.json()).toEqual({
      v: 1,
      address: UNIVERSE,
      name: "tau universe",
      sign_key: universeIdentity.signKey,
      box_key: universeIdentity.boxKey,
      inbox: `https://${UNIVERSE}/net/inbox`,
      software: SOFTWARE,
    });
    expect(JSON.stringify(await (await call("/.well-known/tau.json")).json())).not.toContain(
      identityValue,
    );
  });

  it("answers only GET and HEAD", async () => {
    expect((await call("/.well-known/tau.json", { method: "POST" })).status).toBe(405);
    expect((await call("/.well-known/tau.json", { method: "HEAD" })).status).toBe(200);
  });
});

// -- hub-run sub-taus --------------------------------------------------------------------------

describe("a hub-run web sub-tau", () => {
  it("gets a sealed visit and its answer lands in the visitor's thread", async () => {
    await listAlice();
    const spine = new FakeSpine(ALICE);
    spine.install();

    const res = await chatPost("coach", { text: "  Hello coach  " });
    const cookie = res.headers.get("set-cookie") ?? "";
    expect(cookie).toMatch(/^tau_visitor=[A-Za-z0-9_-]{32}; /);
    expect(cookie).toContain("Path=/api/chat");
    expect(cookie).toContain("Max-Age=31536000");
    expect(cookie).toContain("HttpOnly");
    expect(cookie).toContain("SameSite=Lax");
    expect(cookie).toContain("Secure");
    expect(res.headers.get("cache-control")).toBe("no-store");
    const visitor = cookieOf(res);
    const first = await sent(res);
    expect(first.n).toBe(1);
    expect(first.thread).toMatch(/^[A-Za-z0-9_-]{16,64}$/);

    // What Alice's hub gets: a visit from the universe, sealed to her box key.
    expect(spine.envelopes).toHaveLength(1);
    const visit = await spine.visit();
    expect(visit.payload).toMatchObject({
      v: 1,
      id: first.id,
      kind: "visit",
      from: UNIVERSE,
      to: ALICE.address,
      thread: first.thread,
      reply_to: null,
      hops: 0,
    });
    expect(visit.content).toEqual({ text: "Hello coach", sub: "coach" });
    const inboxRequest = spine.requests.find((request) => request.url.endsWith("/net/inbox"))!;
    expect(inboxRequest.headers.get("content-type")).toBe("application/json");
    expect(inboxRequest.headers.get("user-agent")).toBe(SOFTWARE);

    let thread = await view(await chatGet("coach", first.thread, visitor));
    expect(thread.pending).toBe(true);
    expect(thread.state).toBe("open");
    expect(thread.messages).toEqual([
      { n: 1, from: "visitor", text: "Hello coach", ts: expect.any(Number) },
    ]);

    // The hub answers.
    const answer = await hubAnswer(visit, "Hi! Ready for a run?");
    const delivered = await inbox(answer);
    expect(delivered.status).toBe(202);
    expect(await delivered.json()).toEqual({ status: "delivered", id: idOf(answer) });

    thread = await view(await chatGet("coach", first.thread, visitor, "after=1"));
    expect(thread).toEqual({
      messages: [{ n: 2, from: "sub", text: "Hi! Ready for a run?", ts: expect.any(Number) }],
      pending: false,
      state: "open",
    });

    // The same answer again (a hub re-handling after a crash) is a duplicate.
    const again = await inbox(answer);
    expect(again.status).toBe(200);
    expect(await again.json()).toEqual({ status: "duplicate", id: idOf(answer) });

    // The thread continues: the next visit carries the same thread.
    const second = await sent(
      await chatPost("coach", { text: "Yes", thread: first.thread }, { cookie: visitor }),
    );
    expect(second).toMatchObject({ thread: first.thread, n: 3 });
    const next = await spine.visit();
    expect(next.payload.thread).toBe(first.thread);
    expect(next.payload.id).toBe(second.id);
    expect(next.content).toEqual({ text: "Yes", sub: "coach" });
  });

  it("keeps the visitor's cookie: no new one when the request has it", async () => {
    await listAlice();
    new FakeSpine(ALICE).install();
    const first = await chatPost("coach", { text: "One" });
    const token = cookieOf(first);
    const second = await chatPost("coach", { text: "Two" }, { cookie: token });
    expect(second.status).toBe(200);
    expect(second.headers.get("set-cookie")).toBeNull();
  });

  it("returns a waiting poll as soon as the answer lands", async () => {
    await listAlice();
    const spine = new FakeSpine(ALICE);
    spine.install();
    const res = await chatPost("coach", { text: "Are you there?" });
    const visitor = cookieOf(res);
    const { thread } = await sent(res);
    const visit = await spine.visit();

    const started = Date.now();
    const [polled] = await Promise.all([
      chatGet("coach", thread, visitor, "after=1&wait=10"),
      (async () => {
        await new Promise((resolve) => setTimeout(resolve, 300));
        expect((await inbox(await hubAnswer(visit, "I am."))).status).toBe(202);
      })(),
    ]);
    const body = await view(polled);
    expect(body.messages.map((message) => message.text)).toEqual(["I am."]);
    expect(Date.now() - started).toBeLessThan(8_000);
  });

  it("returns a poll at once when nothing is pending", async () => {
    await listAlice();
    const spine = new FakeSpine(ALICE);
    spine.install();
    const res = await chatPost("coach", { text: "Hi" });
    const visitor = cookieOf(res);
    const { thread } = await sent(res);
    await inbox(await hubAnswer(await spine.visit(), "Hello"));
    const started = Date.now();
    const body = await view(await chatGet("coach", thread, visitor, "after=2&wait=25"));
    expect(body).toEqual({ messages: [], pending: false, state: "open" });
    expect(Date.now() - started).toBeLessThan(1_500);
  });

  it("takes one message at a time: a second one while the first waits is busy", async () => {
    await listAlice();
    new FakeSpine(ALICE).install();
    const res = await chatPost("coach", { text: "First" });
    const visitor = cookieOf(res);
    const { thread } = await sent(res);
    const busy = await chatPost("coach", { text: "Second", thread }, { cookie: visitor });
    expect(busy.status).toBe(409);
    expect(await busy.json()).toEqual({ error: "busy" });
  });

  it("stops counting a visit as pending after the window; a late answer still lands", async () => {
    await listAlice();
    const spine = new FakeSpine(ALICE);
    spine.install();
    const res = await chatPost("coach", { text: "Anyone?" });
    const visitor = cookieOf(res);
    const { thread } = await sent(res);
    const visit = await spine.visit();

    const relay = env.RELAY.getByName(thread);
    const later = nowSeconds() + HUB_PENDING_SECONDS + 1;
    const hashed = await visitorId(visitor);
    const ref = { slug: "coach" };
    const stale = await relay.read({ visitor: hashed, ref, after: 0, now: later });
    expect(stale?.pending).toBe(false);

    expect((await inbox(await hubAnswer(visit, "Sorry, I was out."))).status).toBe(202);
    const body = await view(await chatGet("coach", thread, visitor, "after=1"));
    expect(body.messages.map((message) => message.from)).toEqual(["sub"]);
  });

  it("shows a spine that refuses the visit as unavailable, and takes a late answer", async () => {
    await listAlice();
    const spine = new FakeSpine(ALICE);
    spine.inbox = () => Response.json({ error: "mailbox_full" }, { status: 503 });
    spine.install();
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const res = await chatPost("coach", { text: "Hello?" });
    const visitor = cookieOf(res);
    const { thread } = await sent(res);
    let body = await view(await chatGet("coach", thread, visitor));
    expect(body.pending).toBe(false);
    expect(body.state).toBe("unavailable");
    expect(JSON.stringify(warn.mock.calls)).toContain("mailbox_full");

    // The hub got it after all and answers: the answer is taken and the thread is open.
    expect((await inbox(await hubAnswer(await spine.visit(), "Here now."))).status).toBe(202);
    body = await view(await chatGet("coach", thread, visitor));
    expect(body.state).toBe("open");
    expect(body.messages.map((message) => message.text)).toEqual(["Hello?", "Here now."]);
  });

  it("shows an owner whose card cannot be fetched as unavailable", async () => {
    await listAlice();
    const spine = new FakeSpine();
    spine.install();
    vi.spyOn(console, "warn").mockImplementation(() => {});
    const res = await chatPost("coach", { text: "Hello?" });
    const visitor = cookieOf(res);
    const { thread } = await sent(res);
    expect(spine.envelopes).toHaveLength(0);
    const body = await view(await chatGet("coach", thread, visitor));
    expect(body).toMatchObject({ pending: false, state: "unavailable" });
  });

  it("is unavailable without UNIVERSE_IDENTITY, before anything is stored", async () => {
    await listAlice();
    const spine = new FakeSpine(ALICE);
    spine.install();
    const res = await chatPost(
      "coach",
      { text: "Hello" },
      { bindings: { UNIVERSE_IDENTITY: "" } },
    );
    expect(res.status).toBe(503);
    expect(await res.json()).toEqual({ error: "unavailable" });
    expect(res.headers.get("set-cookie")).toBeNull();
    expect(spine.requests).toHaveLength(0);
  });
});

// -- the inbox ---------------------------------------------------------------------------------

describe("the universe's inbox", () => {
  /** A visit Alice's hub received, with the visitor's cookie. */
  async function pendingVisit(): Promise<{
    spine: FakeSpine;
    visit: OpenedEnvelope;
    visitor: string;
    thread: string;
  }> {
    await listAlice();
    const spine = new FakeSpine(ALICE, BOB);
    spine.install();
    const res = await chatPost("coach", { text: "Hello" });
    const visitor = cookieOf(res);
    const { thread } = await sent(res);
    return { spine, visit: await spine.visit(), visitor, thread };
  }

  it("is 503 not_configured without UNIVERSE_IDENTITY", async () => {
    const res = await inbox({ payload: "e30", sig: "AA" }, { bindings: { UNIVERSE_IDENTITY: "" } });
    expect(res.status).toBe(503);
    expect(await res.json()).toEqual({ error: "not_configured" });
  });

  it("takes only POST", async () => {
    expect((await call("/net/inbox")).status).toBe(405);
  });

  it("refuses what is not JSON, too large or not an envelope", async () => {
    const text = await inbox("{}", { contentType: "text/plain" });
    expect(text.status).toBe(415);
    expect(await text.json()).toEqual({ error: "unsupported_media_type" });

    const large = await inbox(JSON.stringify({ payload: "A".repeat(70_000), sig: "" }));
    expect(large.status).toBe(413);

    const shape = await inbox({ payload: 1, sig: "AA" });
    expect(shape.status).toBe(400);
    expect(await shape.json()).toMatchObject({ error: "bad_request" });

    const payload = await inbox({ payload: "e30", sig: "AA" });
    expect(payload.status).toBe(400);
    expect(await payload.json()).toMatchObject({ error: "bad_request" });
  });

  it("refuses an envelope for another recipient or outside the clock window", async () => {
    const { visit } = await pendingVisit();
    const other = await inbox(await hubAnswer(visit, "Hi", { to: "other.example" }));
    expect(other.status).toBe(400);
    expect(await other.json()).toEqual({ error: "wrong_recipient" });

    const stale = await inbox(await hubAnswer(visit, "Hi", { ts: nowSeconds() - 301 }));
    expect(stale.status).toBe(400);
    expect(await stale.json()).toEqual({ error: "stale" });
  });

  it("takes only answers to its own visits", async () => {
    const { visit, spine } = await pendingVisit();
    const before = spine.requests.length;

    const unknown = await inbox(await hubAnswer(visit, "Hi", { replyTo: "x".repeat(24) }));
    expect(unknown.status).toBe(400);
    expect(await unknown.json()).toEqual({
      error: "bad_request",
      detail: "no visit of this universe has this reply_to",
    });

    const noReply = await inbox(await hubAnswer(visit, "Hi", { replyTo: null }));
    expect(noReply.status).toBe(400);

    const request = await inbox(
      await hubAnswer(visit, "Hi", { kind: "contact_request", content: { name: "A", text: "" } }),
    );
    expect(request.status).toBe(400);
    expect(await request.json()).toMatchObject({
      detail: "the universe takes only answers to its visits",
    });

    const otherThread = await inbox(await hubAnswer(visit, "Hi", { thread: "y".repeat(24) }));
    expect(otherThread.status).toBe(400);

    // None of these cost a card fetch.
    expect(spine.requests.length).toBe(before);
  });

  it("refuses an answer from another address than the visit went to", async () => {
    const { visit } = await pendingVisit();
    const bob = await Identity.fromSeeds(b64uDecode(BOB.seed)!, b64uDecode(ALICE.seed)!);
    const res = await inbox(await hubAnswer(visit, "Hi, I am Bob", { from: BOB.address }, bob));
    expect(res.status).toBe(400);
    expect(await res.json()).toEqual({
      error: "bad_request",
      detail: "the visit went to another address",
    });
  });

  it("refuses an answer the sender's key did not sign", async () => {
    const { visit } = await pendingVisit();
    const forger = await Identity.generate();
    const res = await inbox(await hubAnswer(visit, "Forged", {}, forger));
    expect(res.status).toBe(403);
    expect(await res.json()).toEqual({ error: "bad_signature" });
  });

  it("refuses an answer that names another sub-tau, or none", async () => {
    const { visit } = await pendingVisit();
    const other = await inbox(
      await hubAnswer(visit, "Hi", { content: { text: "Hi", sub: "notes" } }),
    );
    expect(other.status).toBe(400);
    expect(await other.json()).toMatchObject({ detail: "sub does not name the visited sub-tau" });
    const none = await inbox(await hubAnswer(visit, "Hi", { content: { text: "Hi" } }));
    expect(none.status).toBe(400);
  });

  it("refuses a second, different answer to an answered visit", async () => {
    const { visit } = await pendingVisit();
    expect((await inbox(await hubAnswer(visit, "One"))).status).toBe(202);
    const second = await inbox(await hubAnswer(visit, "Two"));
    expect(second.status).toBe(400);
    expect(await second.json()).toMatchObject({ detail: "the visit was already answered" });
  });

  it("is 502 when the sender's card cannot be fetched", async () => {
    const { visit, spine } = await pendingVisit();
    spine.cards.clear();
    const res = await inbox(await hubAnswer(visit, "Hi"));
    expect(res.status).toBe(502);
    expect(await res.json()).toEqual({ error: "sender_card_unavailable" });
  });

  it("applies the per-IP and per-sender limits before anything else is done", async () => {
    const { visit, spine } = await pendingVisit();
    const before = spine.requests.length;
    const refuse = { limit: async () => ({ success: false }) } as unknown as RateLimit;
    const byIp = await inbox(await hubAnswer(visit, "Hi"), {
      ip: "198.51.100.7",
      bindings: { INBOX_IP_LIMIT: refuse },
    });
    expect(byIp.status).toBe(429);
    const bySender = await inbox(await hubAnswer(visit, "Hi"), {
      bindings: { INBOX_SENDER_LIMIT: refuse },
    });
    expect(bySender.status).toBe(429);
    expect(await bySender.json()).toEqual({ error: "rate_limited" });
    expect(spine.requests.length).toBe(before);
  });
});

// -- hosted sub-taus ---------------------------------------------------------------------------

describe("a hosted web sub-tau", () => {
  it("is answered by tau-host's visitor API through HOST", async () => {
    const host = new FakeHost();
    await listDana(host);
    const bodies: unknown[] = [];
    const answer = replying();
    host.visit = (request, body) => {
      bodies.push(body);
      return answer(request, body);
    };
    const bindings = { HOST: host.binding };

    const res = await chatPost("@dana/helper", { text: "Hello helper" }, { bindings });
    const visitor = cookieOf(res);
    const { thread, n } = await sent(res);
    expect(n).toBe(1);

    const call = host.requests.find((request) => request.url.includes("/api/visit/"))!;
    expect(call.method).toBe("POST");
    expect(call.url).toBe(`https://${UNIVERSE}/api/visit/dana/helper`);
    expect(call.headers.get("origin")).toBeNull();
    expect(call.headers.get("cf-connecting-ip")).toBeNull();
    expect(call.headers.get("cookie")).toBeNull();
    expect(bodies[0]).toEqual({ visitor: await visitorId(visitor), text: "Hello helper" });
    expect((bodies[0] as { visitor: string }).visitor).toMatch(/^[A-Za-z0-9_-]{8,64}$/);

    const body = await view(await chatGet("@dana/helper", thread, visitor, "after=0", bindings));
    expect(body).toEqual({
      messages: [
        { n: 1, from: "visitor", text: "Hello helper", ts: expect.any(Number) },
        { n: 2, from: "sub", text: "Hi from helper", ts: expect.any(Number) },
      ],
      pending: false,
      state: "open",
    });

    // The next message carries tau-host's own thread id; the slug names the same sub-tau.
    await sent(await chatPost("helper", { text: "More", thread }, { cookie: visitor, bindings }));
    expect(bodies[1]).toEqual({
      visitor: await visitorId(visitor),
      thread: "host-thread-1",
      text: "More",
    });
    const bySlug = await view(await chatGet("helper", thread, visitor, "after=2", bindings));
    expect(bySlug.messages.map((message) => message.n)).toEqual([3, 4]);
  });

  it("rests until tomorrow when tau-host says daily_cap, and after a budget refusal", async () => {
    const host = new FakeHost();
    await listDana(host);
    vi.spyOn(console, "warn").mockImplementation(() => {});
    const bindings = { HOST: host.binding };
    for (const [status, code] of [
      [429, "daily_cap"],
      [402, "budget"],
    ] as const) {
      host.visit = () => Response.json({ error: code }, { status });
      const res = await chatPost("helper", { text: "Hi" }, { bindings });
      const visitor = cookieOf(res);
      const { thread } = await sent(res);
      const body = await view(await chatGet("helper", thread, visitor, "after=0", bindings));
      expect(body).toEqual({
        messages: [{ n: 1, from: "visitor", text: "Hi", ts: expect.any(Number) }],
        pending: false,
        state: "resting",
      });
    }
  });

  it("starts a new tau-host thread when tau-host forgot its own", async () => {
    const host = new FakeHost();
    await listDana(host);
    const bindings = { HOST: host.binding };
    host.visit = replying("First", "host-old");
    const res = await chatPost("helper", { text: "Hi" }, { bindings });
    const visitor = cookieOf(res);
    const { thread } = await sent(res);

    const bodies: Record<string, unknown>[] = [];
    host.visit = (_request, body) => {
      const b = body as Record<string, unknown>;
      bodies.push(b);
      if (b.thread === "host-old") {
        return Response.json({ error: "unknown_thread" }, { status: 404 });
      }
      return Response.json({ thread: "host-new", reply: { id: "9", text: "Again", ts: 1 } });
    };
    const options = { cookie: visitor, bindings };
    await sent(await chatPost("helper", { text: "Still there?", thread }, options));
    expect(bodies.map((b) => b.thread)).toEqual(["host-old", undefined]);
    const body = await view(await chatGet("helper", thread, visitor, "after=2", bindings));
    expect(body.messages.map((message) => message.text)).toEqual(["Still there?", "Again"]);

    host.visit = (_request, b) => {
      bodies.push(b as Record<string, unknown>);
      return Response.json({ thread: "host-new", reply: { id: "10", text: "Yes", ts: 1 } });
    };
    await sent(await chatPost("helper", { text: "Good", thread }, { cookie: visitor, bindings }));
    expect(bodies.at(-1)?.thread).toBe("host-new");
  });

  it("takes no_reply as an answer without a message", async () => {
    const host = new FakeHost();
    await listDana(host);
    const bindings = { HOST: host.binding };
    host.visit = () => Response.json({ error: "no_reply" }, { status: 502 });
    const res = await chatPost("helper", { text: "Bye" }, { bindings });
    const visitor = cookieOf(res);
    const { thread } = await sent(res);
    const body = await view(await chatGet("helper", thread, visitor, "after=0", bindings));
    expect(body).toMatchObject({ pending: false, state: "open" });
    expect(body.messages).toHaveLength(1);
  });

  it("shows tau-host errors and failures as unavailable", async () => {
    const host = new FakeHost();
    await listDana(host);
    vi.spyOn(console, "warn").mockImplementation(() => {});
    const bindings = { HOST: host.binding };
    const answers: (() => Response)[] = [
      () => Response.json({ error: "provider_error" }, { status: 502 }),
      () => Response.json({ error: "unavailable" }, { status: 503 }),
      () => new Response("not json", { status: 200 }),
      () => {
        throw new Error("host is down");
      },
    ];
    for (const answer of answers) {
      host.visit = answer;
      const res = await chatPost("helper", { text: "Hi" }, { bindings });
      const visitor = cookieOf(res);
      const { thread } = await sent(res);
      const body = await view(await chatGet("helper", thread, visitor, "after=0", bindings));
      expect(body).toMatchObject({ pending: false, state: "unavailable" });
    }
  });

  it("is unavailable without the HOST binding", async () => {
    const host = new FakeHost();
    await listDana(host);
    const res = await chatPost("helper", { text: "Hi" });
    expect(res.status).toBe(503);
    expect(await res.json()).toEqual({ error: "unavailable" });
  });

  it("fills a thread with 50 messages, then refuses more (thread_full)", async () => {
    const host = new FakeHost();
    await listDana(host);
    host.visit = replying("ok");
    const bindings = { HOST: host.binding };
    const first = await chatPost("helper", { text: "1" }, { bindings });
    const visitor = cookieOf(first);
    const { thread } = await sent(first);
    for (let i = 2; i <= MAX_THREAD_MESSAGES / 2; i++) {
      await sent(
        await chatPost("helper", { text: String(i), thread }, { cookie: visitor, bindings }),
      );
    }
    const full = await chatPost("helper", { text: "more", thread }, { cookie: visitor, bindings });
    expect(full.status).toBe(409);
    expect(await full.json()).toEqual({ error: "thread_full" });
    const body = await view(await chatGet("helper", thread, visitor, "after=0", bindings));
    expect(body.messages).toHaveLength(MAX_THREAD_MESSAGES);
    expect(body.state).toBe("full");
  });
});

// -- the chat API's checks ---------------------------------------------------------------------

describe("POST /api/chat/<target>", () => {
  it("refuses unknown targets and paths", async () => {
    await listAlice();
    for (const target of ["nobody", "@alice/coach", "@nobody/coach", "Coach", "@al!ce/coach"]) {
      const res = await chatPost(target, { text: "Hi" });
      expect(res.status, target).toBe(404);
      expect(await res.json()).toEqual({ error: "not_found" });
    }
    expect((await call("/api/chat", { method: "POST" })).status).toBe(404);
    expect((await call("/api/chat/coach/x/y", { method: "POST" })).status).toBe(404);
  });

  it("refuses a sub-tau without a web page (not_web)", async () => {
    await listAlice();
    const res = await chatPost("notes", { text: "Hi" });
    expect(res.status).toBe(403);
    expect(await res.json()).toEqual({ error: "not_web" });
  });

  it("wants JSON from the site's own origin", async () => {
    await listAlice();
    const type = await chatPost("coach", "text=Hi", {
      contentType: "application/x-www-form-urlencoded",
    });
    expect(type.status).toBe(415);
    const other = await chatPost("coach", { text: "Hi" }, { origin: "https://evil.example" });
    expect(other.status).toBe(403);
    expect(await other.json()).toEqual({ error: "bad_origin" });
    const none = await chatPost("coach", { text: "Hi" }, { origin: null });
    expect(none.status).toBe(403);
  });

  it("checks the text and the thread id", async () => {
    await listAlice();
    new FakeSpine(ALICE).install();
    const cases: [unknown, string][] = [
      [{}, "text must be a string"],
      [{ text: 5 }, "text must be a string"],
      [{ text: "   " }, "text must have 1-2000 characters"],
      [{ text: "x".repeat(2001) }, "text must have 1-2000 characters"],
      [{ text: "Hi", thread: "short" }, "thread is not a thread id"],
      [{ text: "Hi", thread: 7 }, "thread is not a thread id"],
      ["[1]", "body must be a JSON object"],
      ["{", "body must be a JSON object"],
    ];
    for (const [body, detail] of cases) {
      const res = await chatPost("coach", body);
      expect(res.status, JSON.stringify(body)).toBe(400);
      expect(await res.json()).toEqual({ error: "bad_request", detail });
    }
    expect((await chatPost("coach", { text: "x".repeat(2000) })).status).toBe(200);
    const large = await chatPost("coach", JSON.stringify({ text: "x".repeat(20_000) }));
    expect(large.status).toBe(413);
  });

  it("limits each client IP to what CHAT_IP_LIMIT allows", async () => {
    await listAlice();
    new FakeSpine(ALICE).install();
    const counts = new Map<string, number>();
    const limiter = {
      limit: async ({ key }: { key: string }) => {
        counts.set(key, (counts.get(key) ?? 0) + 1);
        return { success: counts.get(key)! <= 10 };
      },
    } as unknown as RateLimit;
    const bindings = { CHAT_IP_LIMIT: limiter };
    for (let i = 0; i < 10; i++) {
      const res = await chatPost("coach", { text: "Hi" }, { ip: "203.0.113.9", bindings });
      expect(res.status).toBe(200);
    }
    const limited = await chatPost("coach", { text: "Hi" }, { ip: "203.0.113.9", bindings });
    expect(limited.status).toBe(429);
    expect(await limited.json()).toEqual({ error: "rate_limited" });
    const other = await chatPost("coach", { text: "Hi" }, { ip: "203.0.113.10", bindings });
    expect(other.status).toBe(200);
    expect([...counts.keys()]).toEqual(["203.0.113.9", "203.0.113.10"]);
  });

  it("keeps a thread to the visitor who started it and to its sub-tau", async () => {
    await listAlice();
    const host = new FakeHost();
    await listDana(host);
    host.visit = replying();
    const spine = new FakeSpine(ALICE);
    spine.install();
    const res = await chatPost("coach", { text: "Mine" });
    const visitor = cookieOf(res);
    const { thread } = await sent(res);
    await inbox(await hubAnswer(await spine.visit(), "Yours"));

    // Another visitor, or none, cannot continue or read it.
    const stranger = cookieOf(await chatPost("coach", { text: "Other thread" }));
    const post = await chatPost("coach", { text: "Hijack", thread }, { cookie: stranger });
    expect(post.status).toBe(404);
    expect((await chatGet("coach", thread, stranger)).status).toBe(404);
    expect((await chatGet("coach", thread, null)).status).toBe(404);
    // The thread belongs to /coach, not to another sub-tau.
    const elsewhere = await chatPost(
      "helper",
      { text: "Hi", thread },
      { cookie: visitor, bindings: { HOST: host.binding } },
    );
    expect(elsewhere.status).toBe(404);
    expect((await chatGet("helper", thread, visitor)).status).toBe(404);
    // An unknown thread id is not found either.
    const unknown = await chatPost(
      "coach",
      { text: "Hi", thread: "z".repeat(24) },
      { cookie: visitor },
    );
    expect(unknown.status).toBe(404);
  });

  it("never logs a visitor's text", async () => {
    const secret = "SECRET-VISITOR-TEXT-42";
    const logs = ["log", "info", "warn", "error", "debug"].map((level) =>
      vi.spyOn(console, level as "log").mockImplementation(() => {}),
    );
    await listAlice();
    const spine = new FakeSpine(ALICE);
    spine.install();
    const res = await chatPost("coach", { text: secret });
    const visitor = cookieOf(res);
    const { thread } = await sent(res);
    await inbox(await hubAnswer(await spine.visit(), `${secret} back`));
    await chatGet("coach", thread, visitor);

    const host = new FakeHost();
    await listDana(host);
    host.visit = () => Response.json({ error: "provider_error" }, { status: 502 });
    await chatPost("helper", { text: secret }, { bindings: { HOST: host.binding } });

    for (const spy of logs) expect(JSON.stringify(spy.mock.calls)).not.toContain(secret);
  });
});

describe("GET /api/chat/<target>/<thread>", () => {
  it("checks after and wait, and takes only GET", async () => {
    await listAlice();
    new FakeSpine(ALICE).install();
    const res = await chatPost("coach", { text: "Hi" });
    const visitor = cookieOf(res);
    const { thread } = await sent(res);
    expect((await chatGet("coach", thread, visitor, "after=-1")).status).toBe(400);
    expect((await chatGet("coach", thread, visitor, "wait=26")).status).toBe(400);
    expect((await chatGet("coach", thread, visitor, "wait=x")).status).toBe(400);
    const post = await call(`/api/chat/coach/${thread}`, { method: "POST" });
    expect(post.status).toBe(405);
    const get = await call("/api/chat/coach", { method: "GET" });
    expect(get.status).toBe(405);
  });

  it("names the same thread by its slug and by its tau's handle", async () => {
    const host = new FakeHost();
    await listDana(host);
    host.visit = replying();
    const bindings = { HOST: host.binding };
    const res = await chatPost("helper", { text: "Hi" }, { bindings });
    const visitor = cookieOf(res);
    const { thread } = await sent(res);
    const bySlug = await view(await chatGet("helper", thread, visitor));
    const byHandle = await view(await chatGet("@DANA/helper", thread, visitor));
    expect(byHandle).toEqual(bySlug);
  });
});

// -- the Relay ---------------------------------------------------------------------------------

describe("the Relay", () => {
  async function started(): Promise<{ thread: string; visitor: string }> {
    await listAlice();
    new FakeSpine(ALICE).install();
    const res = await chatPost("coach", { text: "Hi" });
    const visitor = cookieOf(res);
    const { thread } = await sent(res);
    return { thread, visitor };
  }

  it("deletes a thread 24 hours after it began", async () => {
    const before = nowSeconds();
    const { thread, visitor } = await started();
    const stub = env.RELAY.getByName(thread);
    const alarm = await runInDurableObject(stub, (_instance, state) =>
      state.storage.getAlarm(),
    );
    expect(alarm).toBeGreaterThanOrEqual((before + THREAD_TTL_SECONDS) * 1000);
    expect(alarm).toBeLessThanOrEqual((nowSeconds() + THREAD_TTL_SECONDS) * 1000);

    expect(await runDurableObjectAlarm(stub)).toBe(true);
    expect((await chatGet("coach", thread, visitor)).status).toBe(404);
    const tables = await runInDurableObject(stub, (_instance, state) =>
      state.storage.sql
        .exec<{ name: string }>("SELECT name FROM sqlite_master WHERE type = 'table'")
        .toArray(),
    );
    expect(tables.map((row) => row.name)).not.toContain("messages");
  });

  it("treats an expired thread as gone before the alarm runs", async () => {
    const { thread, visitor } = await started();
    const relay = env.RELAY.getByName(thread);
    const input = {
      visitor: await visitorId(visitor),
      ref: { slug: "coach" },
      after: 0,
    };
    expect(await relay.read({ ...input, now: nowSeconds() })).not.toBeNull();
    expect(await relay.read({ ...input, now: nowSeconds() + THREAD_TTL_SECONDS + 1 })).toBeNull();
  });

  it("stores nothing for a thread id that never began", async () => {
    await listAlice();
    const token = "t".repeat(32);
    const thread = "q".repeat(24);
    expect((await chatGet("coach", thread, token)).status).toBe(404);
    const stub = env.RELAY.getByName(thread);
    const tables = await runInDurableObject(stub, (_instance, state) =>
      state.storage.sql
        .exec(
          "SELECT name FROM sqlite_master WHERE type = 'table' " +
            "AND name IN ('thread', 'messages', 'visits')",
        )
        .toArray(),
    );
    expect(tables).toEqual([]);
  });
});

// -- small pieces ------------------------------------------------------------------------------

describe("chat helpers", () => {
  it("parses chat paths", () => {
    const thread = "a".repeat(24);
    expect(parseChatPath("/api/chat/coach")).toEqual({ ref: { slug: "coach" }, thread: null });
    expect(parseChatPath(`/api/chat/coach/${thread}`)).toEqual({ ref: { slug: "coach" }, thread });
    expect(parseChatPath("/api/chat/@Alice/coach")).toEqual({
      ref: { handle: "alice", name: "coach" },
      thread: null,
    });
    expect(parseChatPath(`/api/chat/@alice/coach/${thread}`)).toEqual({
      ref: { handle: "alice", name: "coach" },
      thread,
    });
    for (const path of [
      "/api/chat/",
      "/api/chat/c",
      "/api/chat/@alice",
      "/api/chat/@alice/",
      "/api/chat/coach/short",
      `/api/chat/coach/${thread}/x`,
      "/api/chat/@-x/coach",
      "/api/chats/coach",
    ]) {
      expect(parseChatPath(path), path).toBeNull();
    }
  });

  it("reads the visitor cookie", () => {
    const token = "v".repeat(32);
    const request = (cookie: string) => new Request("https://x.example/", { headers: { cookie } });
    expect(visitorToken(request(`lang=tr; tau_visitor=${token}`))).toBe(token);
    expect(visitorToken(request("tau_visitor=short"))).toBeNull();
    expect(visitorToken(request("tau_visitor=bad value!"))).toBeNull();
    expect(visitorToken(new Request("https://x.example/"))).toBeNull();
  });

  it("derives a visitor id that is not the cookie", async () => {
    const token = "v".repeat(32);
    const id = await visitorId(token);
    expect(id).toMatch(/^[A-Za-z0-9_-]{43}$/);
    expect(id).not.toContain(token);
    expect(await visitorId(token)).toBe(id);
    expect(await visitorId("w".repeat(32))).not.toBe(id);
  });

  it("keys IPv6 clients by their /64", () => {
    expect(clientKey("203.0.113.9")).toBe("203.0.113.9");
    expect(clientKey("2001:db8:1:2:3:4:5:6")).toBe("2001:db8:1:2::/64");
    expect(clientKey("::ffff:203.0.113.9")).toBe("203.0.113.9");
    expect(clientKey("")).toBeNull();
    expect(clientKey("nonsense")).toBeNull();
  });
});
