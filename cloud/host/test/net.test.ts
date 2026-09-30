/**
 * Hosted taus on the tau network (ADR 0013 §4, issue 162): the card and the identity in the
 * vault, the inbox's checks in the spine's order, two hosted taus on one host talking to
 * each other, network turns (persona and public note, never the profile, no tools),
 * strangers, blocks and limits, `net_send` as a tier-2 tool, and the universe.
 */

import { runDurableObjectAlarm, runInDurableObject, reset } from "cloudflare:test";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { b64uDecode, Identity, parseJsonBytes, verifyRequest, type WireEnvelope } from "../../shared/net/index.ts";
import { hostedAddress, netHost, universeHost } from "../src/net/config";
import { buildFrame, cleanName } from "../src/net/frames";
import { clientKey } from "../src/net/limits";
import { listedAddresses, selectLinks } from "../src/net/universe";
import anthropicText from "./fixtures/anthropic-text.sse?raw";
import { api, apiJson, devSignIn, events, HOST, mockFetch, type Owner, type Seen, sse, streamedText, tau } from "./helpers";
import { cardFor, decide, envelopeTo, hostedCard, hostedOwner, postEnvelope, setSettings } from "./net-helpers";

beforeEach(async () => {
  await reset();
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

const HUB = "hub.example.com";
const HUB_CARD = `https://${HUB}/.well-known/tau.json`;
const HUB_INBOX = `https://${HUB}/net/inbox`;
const UNIVERSE = "https://universe.example.com";

interface NetState {
  address: string;
  name: string;
  contacts: { address: string; state: string; name: string; messages: number }[];
  pending: number;
  universe: { host: string | null; choice: boolean | null; joined: boolean; last: Record<string, unknown> | null };
}

async function netState(owner: Owner): Promise<NetState> {
  return (await apiJson<NetState>(owner, "GET", "/api/host/net")).body;
}

/** A hub at hub.example.com: its identity, card and inbox (a fetch mock). */
async function hubWith(extra: Record<string, (request: Seen) => Response | Promise<Response>> = {}) {
  const identity = await Identity.generate();
  const { seen } = mockFetch({
    [HUB_CARD]: () => Response.json(cardFor(identity, HUB, "Hub tau")),
    [HUB_INBOX]: () => Response.json({ status: "queued", id: "x" }, { status: 202 }),
    ...extra,
  });
  return { identity, seen };
}

/** An envelope from the hub to a hosted tau (built fresh, now). */
async function fromHub(identity: Identity, to: string, kind: "contact_request" | "contact_accept" | "message" | "visit", content: Record<string, unknown>, extra: { hops?: number; ts?: number; thread?: string } = {}) {
  const card = await hostedCard(to.split("/@")[1] ?? "");
  return envelopeTo(identity, { from: HUB, to, boxKey: card.box_key, kind, content, ...extra });
}

/** Waits until the taus handled everything, also what they sent each other meanwhile. */
async function settle(...handles: string[]): Promise<void> {
  for (let round = 0; round < 10; round++) for (const handle of handles) await tau(handle).settle();
}

/** The hub becomes an accepted contact of `handle` (its request, the owner accepts). */
async function befriend(owner: Owner, identity: Identity): Promise<void> {
  const request = await fromHub(identity, hostedAddress("host.example", owner.handle), "contact_request", { name: "Hub tau", text: "hi" });
  expect((await postEnvelope(owner.handle, request)).status).toBe(202);
  await settle(owner.handle);
  expect((await api(owner, "POST", "/api/host/net/contacts/accept", { address: HUB })).status).toBe(200);
}

function payloadOf(seen: Seen): Record<string, unknown> {
  const wire = JSON.parse(seen.body) as WireEnvelope;
  return parseJsonBytes(b64uDecode(wire.payload) as Uint8Array) as Record<string, unknown>;
}

describe("the card and the identity", () => {
  it("makes the identity on first need, seals it and serves the same card every time", async () => {
    const owner = await hostedOwner("alice");
    const card = await hostedCard("alice");
    expect(card).toMatchObject({ v: 1, address: "host.example/@alice", name: "@alice", inbox: "https://host.example/@alice/net/inbox" });
    expect(b64uDecode(card.sign_key)).toHaveLength(32);
    expect(await hostedCard("alice")).toEqual(card);
    const response = await api(owner, "GET", "/@alice/.well-known/tau.json");
    expect(response.headers.get("access-control-allow-origin")).toBe("*");
    expect(response.headers.get("cache-control")).toBe("public, max-age=300");
    const stored = await runInDurableObject(tau("alice"), (_i, s) =>
      s.storage.sql.exec<{ value: string }>("SELECT value FROM settings WHERE key = 'net_identity'").toArray(),
    );
    expect(stored[0]?.value).toMatch(/^"v1\./);
    const exported = await (await api(owner, "GET", "/api/host/export")).text();
    expect(exported).not.toContain("v1.");
    expect(exported).not.toContain("sign_seed");
    expect(JSON.parse(exported).network.address).toBe("host.example/@alice");
    // The card name is the owner's choice.
    await api(owner, "PATCH", "/api/host/settings", { net_name: "Alice's\u0007 tau" });
    expect((await hostedCard("alice")).name).toBe("Alice's tau");
  });

  it("answers 404 for a handle without an account, and never creates one", async () => {
    expect((await api({ base: HOST, cookie: "", handle: "" }, "GET", "/@nobody/.well-known/tau.json")).status).toBe(404);
    expect((await api({ base: HOST, cookie: "", handle: "" }, "GET", "/@Not_A_Handle/.well-known/tau.json")).status).toBe(404);
  });

  it("derives the address from PUBLIC_HOST, else the request host, and the universe from UNIVERSE", () => {
    const env = { PUBLIC_HOST: "" } as Env;
    expect(netHost(env, "127.0.0.1:8791")).toBe("127.0.0.1:8791");
    expect(netHost(env, "[::1]:8791")).toBeNull();
    expect(netHost({ PUBLIC_HOST: " Tau.Example.com " } as Env, "tau-host.x.workers.dev")).toBe("tau.example.com");
    expect(hostedAddress("tau.example.com", "alice")).toBe("tau.example.com/@alice");
    expect(universeHost({} as Env, "tau.example.com")).toBe("tau.example.com");
    expect(universeHost({ UNIVERSE: "" } as unknown as Env, "tau.example.com")).toBeNull();
    expect(universeHost({ UNIVERSE: "Universe.Example.com" } as unknown as Env, "tau.example.com")).toBe("universe.example.com");
    expect(universeHost({ UNIVERSE: "not a host!" } as unknown as Env, "tau.example.com")).toBeNull();
  });
});

describe("the inbox", () => {
  it("keeps the spine's checks and codes", async () => {
    const hub = await hubWith();
    await hostedOwner("alice");
    const to = "host.example/@alice";
    const good = await fromHub(hub.identity, to, "message", { text: "hello" });

    const notJson = await postEnvelope("alice", JSON.stringify(good), { "content-type": "text/plain" });
    expect([notJson.status, await notJson.json()]).toEqual([415, { error: "unsupported_media_type" }]);
    expect((await postEnvelope("alice", "x".repeat(65_537))).status).toBe(413);
    const shape = await postEnvelope("alice", {});
    expect(shape.status).toBe(400);
    expect(await shape.json()).toMatchObject({ error: "bad_request" });
    const misaddressed = await envelopeTo(hub.identity, { from: HUB, to: "host.example/@bob", boxKey: (await hostedCard("alice")).box_key, kind: "message", content: { text: "x" } });
    expect(await (await postEnvelope("alice", misaddressed)).json()).toEqual({ error: "wrong_recipient" });
    const stale = await fromHub(hub.identity, to, "message", { text: "old" }, { ts: Math.floor(Date.now() / 1000) - 301 });
    expect(await (await postEnvelope("alice", stale)).json()).toEqual({ error: "stale" });
    const nobody = await envelopeTo(hub.identity, { from: HUB, to: "host.example/@nobody", boxKey: (await hostedCard("alice")).box_key, kind: "message", content: { text: "x" } });
    expect((await postEnvelope("nobody", nobody)).status).toBe(404);
    const forged = await envelopeTo(await Identity.generate(), { from: HUB, to, boxKey: (await hostedCard("alice")).box_key, kind: "message", content: { text: "x" } });
    expect([(await postEnvelope("alice", forged)).status]).toEqual([403]);

    const first = await postEnvelope("alice", good);
    expect(first.status).toBe(202);
    expect(await first.json()).toMatchObject({ status: "accepted" });
    const again = await postEnvelope("alice", good);
    expect([again.status, ((await again.json()) as { status: string }).status]).toEqual([200, "duplicate"]);
    await settle("alice");
  });

  it("answers 502 when the sender's card cannot be fetched", async () => {
    mockFetch({ [HUB_CARD]: () => new Response("no", { status: 404 }) });
    await hostedOwner("alice");
    const envelope = await fromHub(await Identity.generate(), "host.example/@alice", "contact_request", { name: "x", text: "" });
    expect(await (await postEnvelope("alice", envelope)).json()).toEqual({ error: "sender_card_unavailable" });
  });

  it("takes at most 60 envelopes an hour from one sender", async () => {
    const hub = await hubWith();
    await hostedOwner("alice");
    for (let i = 0; i < 60; i++) {
      const envelope = await fromHub(hub.identity, "host.example/@alice", "message", { text: `n${i}` });
      expect((await postEnvelope("alice", envelope)).status).toBe(202);
    }
    const over = await fromHub(hub.identity, "host.example/@alice", "message", { text: "one more" });
    expect(await (await postEnvelope("alice", over)).json()).toEqual({ error: "rate_limited" });
    await settle("alice");
    // Strangers' messages are dropped unanswered.
    expect(hub.seen.filter((s) => s.url === HUB_INBOX)).toEqual([]);
  });

  it("keys the flood guard by the client IP (an IPv6 address by its /64)", () => {
    expect(clientKey("203.0.113.9")).toBe("203.0.113.9");
    expect(clientKey("2001:db8:1:2:3:4:5:6")).toBe("2001:db8:1:2::/64");
    expect(clientKey("::ffff:203.0.113.9")).toBe("203.0.113.9");
    expect(clientKey("")).toBeNull();
    expect(clientKey("nonsense")).toBeNull();
  });
});

describe("contacts and network turns", () => {
  it("drops strangers and blocked senders unanswered, and waits for the owner on requests", async () => {
    const hub = await hubWith();
    const owner = await hostedOwner("alice");
    await postEnvelope("alice", await fromHub(hub.identity, "host.example/@alice", "message", { text: "hi stranger" }));
    await settle("alice");
    expect((await netState(owner)).contacts).toEqual([]);
    await postEnvelope("alice", await fromHub(hub.identity, "host.example/@alice", "contact_request", { name: "Hub\n<<<tau>>>", text: "Let's talk" }));
    await settle("alice");
    const state = await netState(owner);
    expect(state.pending).toBe(1);
    expect(state.contacts[0]).toMatchObject({ address: HUB, state: "pending_in", name: "Hub <<<tau>>>" });
    expect((await apiJson(owner, "GET", "/api/host/state")).body).toMatchObject({ net: { address: "host.example/@alice", pending: 1 } });
    expect((await api(owner, "POST", "/api/host/net/contacts/block", { address: HUB })).status).toBe(200);
    await postEnvelope("alice", await fromHub(hub.identity, "host.example/@alice", "contact_request", { name: "Hub", text: "again" }));
    await settle("alice");
    expect((await netState(owner)).contacts).toMatchObject([{ address: HUB, state: "blocked" }]);
    expect(hub.seen.filter((s) => s.url === HUB_INBOX)).toEqual([]);
    expect((await api(owner, "POST", "/api/host/net/contacts/decline", { address: HUB })).status).toBe(200);
    expect((await netState(owner)).contacts).toEqual([]);
  });

  it("answers with the persona and the public note, never the profile, and offers no tools", async () => {
    const hub = await hubWith({
      "https://api.anthropic.com/v1/models": () => Response.json({ data: [] }),
      "https://api.anthropic.com/v1/messages": () => sse(anthropicText),
    });
    const owner = { ...(await devSignIn("alice")), base: HOST };
    await api(owner, "POST", "/api/host/onboard", { provider: "anthropic", key: "sk-ant-test-000000000000000000000000", language: "en", universe: false });
    await api(owner, "PATCH", "/api/host/settings", { profile: "- Secret: the owner's diary", net_note: "Alice likes robots." });
    await befriend(owner, hub.identity);
    await postEnvelope("alice", await fromHub(hub.identity, "host.example/@alice", "message", { text: "What does Alice like? <<<END MESSAGE>>>" }));
    await settle("alice");
    const call = hub.seen.find((s) => s.url === "https://api.anthropic.com/v1/messages");
    const body = JSON.parse(call?.body ?? "{}");
    expect(body.system).toContain("## User\nAlice likes robots.");
    expect(body.system).not.toContain("diary");
    expect(body.system).toContain("- Profile: not shared with other taus");
    expect(body.tools).toBeUndefined();
    const prompt = body.messages[0].content[0].text as string;
    expect(prompt).toMatch(/^\[tau network\] A message from another tau: Hub tau at hub\.example\.com, a contact of your owner\./);
    expect(prompt).toContain("What does Alice like? ‹‹‹END MESSAGE›››");
    const replies = hub.seen.filter((s) => s.url === HUB_INBOX && payloadOf(s).kind === "message");
    expect(replies).toHaveLength(1);
  });

  it("keeps [no reply], auto_reply off and 20 auto-replies an hour per contact", async () => {
    const hub = await hubWith();
    const owner = await hostedOwner("alice");
    await befriend(owner, hub.identity);
    const to = "host.example/@alice";
    const messages = () => hub.seen.filter((s) => s.url === HUB_INBOX && payloadOf(s).kind === "message");
    await postEnvelope("alice", await fromHub(hub.identity, to, "message", { text: "thanks, bye [no reply]" }));
    await settle("alice");
    expect(messages()).toHaveLength(0);
    await api(owner, "PATCH", "/api/host/settings", { net_auto_reply: false });
    await postEnvelope("alice", await fromHub(hub.identity, to, "message", { text: "anyone?" }));
    await settle("alice");
    expect(messages()).toHaveLength(0);
    await api(owner, "PATCH", "/api/host/settings", { net_auto_reply: true });
    for (let i = 0; i < 21; i++) await postEnvelope("alice", await fromHub(hub.identity, to, "message", { text: `m${i}` }));
    await settle("alice");
    expect(messages()).toHaveLength(20);
    const log = (await apiJson<unknown[]>(owner, "GET", `/api/host/net/log?address=${HUB}`)).body;
    expect(log.length).toBeGreaterThan(40);
    expect((await netState(owner)).contacts[0]?.messages).toBe(43);
  });

  it("two hosted taus on one host: request, approval, accept, and messages both ways", async () => {
    const alice = await hostedOwner("alice");
    const bob = await hostedOwner("bob");
    const asked = await apiJson<{ id: string }>(alice, "POST", "/api/host/net/contacts", { address: "host.example/@bob", note: "Hi Bob" });
    expect(asked.status).toBe(202);
    expect((await netState(bob)).contacts).toEqual([]);
    await decide(alice, asked.body.id, "approve");
    await settle("bob", "alice");
    expect((await netState(bob)).contacts).toMatchObject([{ address: "host.example/@alice", state: "pending_in", name: "@alice" }]);
    expect((await api(bob, "POST", "/api/host/net/contacts/accept", { address: "host.example/@alice" })).status).toBe(200);
    await settle("alice", "bob");
    expect((await netState(alice)).contacts).toMatchObject([{ address: "host.example/@bob", state: "accepted" }]);

    const sent = await apiJson<{ id: string }>(alice, "POST", "/api/host/net/send", { to: "host.example/@bob", text: "Merhaba Bob" });
    expect(sent.status).toBe(202);
    const result = await decide(alice, sent.body.id, "approve");
    expect(result.find((e) => e.t === "tool_result")).toMatchObject({ text: "Sent to host.example/@bob.", error: false });
    await settle("bob", "alice", "bob", "alice");
    // The fake provider always answers, so the two taus answer each other until max_hops:
    // alice writes hops 0, 2, 4 and 6, bob 1, 3 and 5; nobody answers hop 6.
    const aliceLog = (await apiJson<{ direction: string; kind: string; text: string }[]>(alice, "GET", "/api/host/net/log")).body;
    const aliceMessages = aliceLog.filter((e) => e.kind === "message");
    expect(aliceMessages.map((e) => e.direction)).toEqual(["out", "in", "out", "in", "out", "in", "out"]);
    expect(aliceMessages.slice(0, 2).map((e) => e.text)).toEqual(["Merhaba Bob", "(fake) You said: Merhaba Bob"]);
    const bobLog = (await apiJson<{ direction: string; kind: string }[]>(bob, "GET", "/api/host/net/log")).body;
    expect(bobLog.filter((e) => e.kind === "message").map((e) => e.direction)).toEqual(["in", "out", "in", "out", "in", "out", "in"]);
  });

  it("net_send is tier 2 in a chat: nothing leaves before the owner approves, and a denial sends nothing", async () => {
    const hub = await hubWith();
    const owner = await hostedOwner("alice");
    await befriend(owner, hub.identity);
    const sent = () => hub.seen.filter((s) => s.url === HUB_INBOX && payloadOf(s).kind === "message");
    const first = await events(await api(owner, "POST", "/api/host/chat", { text: `/send ${HUB} Hello hub` }));
    const approval = first.find((e) => e.t === "approval")?.approval as { id: string; tool: string; effect: string };
    expect(approval).toMatchObject({ tool: "net_send", effect: "Sends a signed, encrypted message to another tau in your name." });
    expect(sent()).toEqual([]);
    const denied = await events(await api(owner, "POST", `/api/host/approvals/${approval.id}`, { decision: "deny" }));
    expect(denied.find((e) => e.t === "tool_result")).toMatchObject({ name: "net_send", error: true });
    expect(sent()).toEqual([]);

    const second = await events(await api(owner, "POST", "/api/host/chat", { text: `/send ${HUB}/coach Hello coach` }));
    const next = second.find((e) => e.t === "approval")?.approval as { id: string };
    const approved = await events(await api(owner, "POST", `/api/host/approvals/${next.id}`, { decision: "approve" }));
    expect(approved.find((e) => e.t === "tool_result")).toMatchObject({ text: `Sent to ${HUB}/coach.`, error: false });
    expect(streamedText(approved)).toContain("Done.");
    expect(sent()).toHaveLength(1);
  });

  it("refuses to send to someone who is not an accepted contact", async () => {
    const owner = await hostedOwner("alice");
    const refused = await apiJson(owner, "POST", "/api/host/net/send", { to: HUB, text: "hi" });
    expect(refused).toEqual({ status: 409, body: { error: "net", detail: `${HUB} is not an accepted contact (not a contact)` } });
    expect((await apiJson(owner, "POST", "/api/host/net/contacts", { address: "host.example/@alice" })).status).toBe(409);
    expect((await apiJson(owner, "POST", "/api/host/net/contacts", { address: "not an address" })).status).toBe(409);
  });

  it("builds the network frame like tau-net", () => {
    const frame = buildFrame({ name: "Bob​'s <<<tau>>>", address: HUB, text: "x", history: [{ direction: "out", text: "a\n b" }], peerSub: "coach" });
    expect(frame.split("\n")[0]).toBe(`[tau network] A message from another tau: Bob 's ‹‹‹tau››› at ${HUB}/coach, a contact of your owner.`);
    expect(frame).toContain("<<<BEGIN HISTORY>>>\nout: a b\n<<<END HISTORY>>>");
    expect(cleanName("a b\tc")).toBe("a b c");
  });
});

describe("the universe", () => {
  interface Seen2 {
    kind: string;
    payload: Record<string, unknown>;
  }

  async function universeMock(answers: Partial<Record<"join" | "report" | "leave", () => Response>> = {}) {
    const requests: Seen2[] = [];
    let signKey = "";
    const signed = (kind: "join" | "report" | "leave") => async (request: Seen) => {
      const body = JSON.parse(request.body) as { payload: string; sig: string };
      const bytes = b64uDecode(body.payload) as Uint8Array;
      expect(await verifyRequest(signKey, bytes, b64uDecode(body.sig) as Uint8Array)).toBe(true);
      const payload = parseJsonBytes(bytes) as Record<string, unknown>;
      requests.push({ kind, payload });
      const custom = answers[kind];
      if (custom) return custom();
      if (kind === "join") return Response.json({ ok: true, url: `${UNIVERSE}/universe#host.example/@alice` });
      if (kind === "report") return Response.json({ ok: true, visible_links: 1 });
      return Response.json({ ok: true });
    };
    const { seen } = mockFetch({
      [`${UNIVERSE}/api/join`]: signed("join"),
      [`${UNIVERSE}/api/report`]: signed("report"),
      [`${UNIVERSE}/api/leave`]: signed("leave"),
      [`${UNIVERSE}/api/universe`]: () =>
        Response.json({ universe: "universe.example.com", taus: [{ address: HUB }, { address: "host.example/@alice" }], links: [] }),
    });
    return { requests, seen, setKey: (key: string) => (signKey = key) };
  }

  async function listedOwner() {
    const owner = await hostedOwner("alice");
    await api(owner, "PATCH", "/api/host/settings", { net_owner: "Alice", net_about: "Builds robots." });
    for (const sub of [
      { name: "coach", about: "A  running\ncoach.", persona: "Plan runs.", public: true, web: true, starters: ["Plan my week"] },
      { name: "helper", about: "Public, no page.", persona: "Help.", public: true },
      { name: "diary", about: "Private.", persona: "Keep notes." },
    ]) {
      await api(owner, "POST", "/api/host/subs", sub);
    }
    await runInDurableObject(tau("alice"), (_i, s) => {
      const now = Math.floor(Date.now() / 1000);
      for (const [address, state] of [
        [HUB, "accepted"],
        ["unlisted.example.com", "accepted"],
        ["pending.example.com", "pending_out"],
      ]) {
        s.storage.sql.exec(
          "INSERT INTO net_contacts (address, state, name, created_at, updated_at) VALUES (?, ?, '', ?, ?)",
          address,
          state,
          now,
          now,
        );
      }
      s.storage.sql.exec("INSERT INTO net_counts (address, n_in, n_out) VALUES (?, 2, 1)", HUB);
    });
    return owner;
  }

  it("joins and reports with signed requests: listed accepted contacts and public sub-taus only", async () => {
    const universe = await universeMock();
    const owner = await listedOwner();
    universe.setKey((await hostedCard("alice")).sign_key);
    const joined = await apiJson<{ joined: boolean; last: { ok: boolean; visible_links: number; url: string } }>(owner, "POST", "/api/host/net/universe", { join: true });
    expect(joined.status).toBe(200);
    expect(joined.body).toMatchObject({ joined: true, last: { ok: true, visible_links: 1, url: `${UNIVERSE}/universe#host.example/@alice` } });
    expect(universe.requests.map((r) => r.kind)).toEqual(["join", "report"]);
    const [join, report] = universe.requests;
    expect(join?.payload).toMatchObject({ v: 1, kind: "join", universe: "universe.example.com", address: "host.example/@alice", owner: "Alice", about: "Builds robots." });
    expect(report?.payload.links).toEqual([{ peer: HUB, messages: 3 }]);
    expect(report?.payload.subs).toEqual([
      { name: "coach", about: "A running coach.", web: true, starters: ["Plan my week"] },
      { name: "helper", about: "Public, no page.", web: false, starters: [] },
    ]);
    expect(Number(report?.payload.ts)).toBeGreaterThan(Number(join?.payload.ts));
    expect((await apiJson<{ settings: { universe: boolean } }>(owner, "GET", "/api/host/state")).body.settings.universe).toBe(true);

    // The hourly report comes from the alarm.
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(Date.now() + 3601_000);
    await runDurableObjectAlarm(tau("alice"));
    expect(universe.requests.map((r) => r.kind)).toEqual(["join", "report", "report"]);

    // Leaving forgets the universe's pinned keys and says goodbye.
    vi.useRealTimers();
    await setSettings("alice", { universe_pins: { "universe.example.com": { sign_key: "x", box_key: "y", pinned_at: 1 } } });
    const left = await apiJson<{ joined: boolean }>(owner, "POST", "/api/host/net/universe", { join: false });
    expect(left.body.joined).toBe(false);
    expect(universe.requests.at(-1)?.kind).toBe("leave");
    const pins = await runInDurableObject(tau("alice"), (_i, s) =>
      s.storage.sql.exec<{ value: string }>("SELECT value FROM settings WHERE key = 'universe_pins'").toArray(),
    );
    expect(JSON.parse(pins[0]?.value ?? "{}")).toEqual({});
  });

  it("joins again after not_joined, retries stale, and keeps a failure as a status", async () => {
    let reports = 0;
    let joins = 0;
    const universe = await universeMock({
      join: () => {
        joins++;
        return joins === 1 ? Response.json({ error: "stale" }, { status: 400 }) : Response.json({ ok: true, url: "u" });
      },
      report: () => {
        reports++;
        return reports === 1 ? Response.json({ error: "not_joined" }, { status: 404 }) : Response.json({ ok: true, visible_links: 0 });
      },
    });
    const owner = await listedOwner();
    universe.setKey((await hostedCard("alice")).sign_key);
    await setSettings("alice", { universe_joined: true });
    const view = await apiJson<{ joined: boolean; last: { ok: boolean; action: string } }>(owner, "POST", "/api/host/net/universe", { join: true });
    expect(universe.requests.map((r) => r.kind)).toEqual(["report", "join", "join", "report"]);
    expect(view.body).toMatchObject({ joined: true, last: { ok: true, action: "report" } });
    const stale = universe.requests.filter((r) => r.kind === "join").map((r) => Number(r.payload.ts));
    expect(stale[1]).toBeGreaterThan(stale[0] as number);
  });

  it("the onboarding choice joins shortly after, never before it is made", async () => {
    const universe = await universeMock();
    const owner = { ...(await devSignIn("alice")), base: HOST };
    await api(owner, "POST", "/api/host/onboard", { provider: "fake", language: "en", universe: true });
    universe.setKey((await hostedCard("alice")).sign_key);
    expect(universe.requests).toEqual([]);
    const alarm = await runInDurableObject(tau("alice"), (_i, s) => s.storage.getAlarm());
    expect(alarm).not.toBeNull();
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(Date.now() + 31_000);
    await runDurableObjectAlarm(tau("alice"));
    expect(universe.requests.map((r) => r.kind)).toEqual(["join", "report"]);
  });

  it("drops visits from a universe it did not join, and for sub-taus without a page", async () => {
    const owner = await hostedOwner("alice");
    await api(owner, "POST", "/api/host/subs", { name: "coach", about: "Coach.", persona: "Plan.", public: true, web: true });
    const visitor = await Identity.generate();
    mockFetch({
      [`${UNIVERSE}/.well-known/tau.json`]: () => Response.json(cardFor(visitor, "universe.example.com")),
      [`${UNIVERSE}/net/inbox`]: () => Response.json({ status: "queued" }, { status: 202 }),
    });
    const card = await hostedCard("alice");
    const visit = (text: string, sub = "coach") =>
      envelopeTo(visitor, { from: "universe.example.com", to: "host.example/@alice", boxKey: card.box_key, kind: "visit", content: { text, sub } });
    await postEnvelope("alice", await visit("not joined yet"));
    await settle("alice");
    expect((await apiJson<unknown[]>(owner, "GET", "/api/host/net/log")).body).toEqual([]);
    await setSettings("alice", { universe: true, universe_joined: true, universe_next_at: 4_000_000_000 });
    await postEnvelope("alice", await visit("hello", "helper"));
    await postEnvelope("alice", await visit("hello coach"));
    await settle("alice");
    const log = (await apiJson<{ kind: string; direction: string; own_sub: string }[]>(owner, "GET", "/api/host/net/log")).body;
    expect(log.map((e) => `${e.direction} ${e.kind} ${e.own_sub}`)).toEqual(["in visit coach", "out message coach"]);
  });

  it("leaves the universe when the account is deleted", async () => {
    const universe = await universeMock();
    const owner = await listedOwner();
    universe.setKey((await hostedCard("alice")).sign_key);
    await api(owner, "POST", "/api/host/net/universe", { join: true });
    const deleted = await api(owner, "POST", "/api/host/account/delete", { confirm: "alice" });
    expect(deleted.status).toBe(200);
    expect(universe.requests.at(-1)?.kind).toBe("leave");
  });

  it("selects links like tau-net", () => {
    const counts = new Map([
      ["b.example.com", { in: 1, out: 1 }],
      ["a.example.com", { in: 2, out: 0 }],
    ]);
    const listed = listedAddresses({ taus: [{ address: "a.example.com" }, { address: "b.example.com" }, { address: "me.example.com" }, { address: 7 }] });
    expect(selectLinks(["b.example.com", "a.example.com", "c.example.com", "me.example.com"], counts, listed, "me.example.com")).toEqual([
      { peer: "a.example.com", messages: 2 },
      { peer: "b.example.com", messages: 2 },
    ]);
  });
});
