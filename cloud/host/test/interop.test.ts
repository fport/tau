/**
 * A hosted tau and a hub (issue 162, acceptance): envelopes tau-net itself built (the `hosted`
 * vectors of cloud/shared/net/vectors.json, written by packages/tau-net/scripts/
 * make_ts_vectors.py) arrive at the hosted tau `bob` (host.example/@bob, bob's test identity),
 * and what bob sends back is opened with the hub's identity (alice at alice.example.com):
 *
 * - a contact request, accepted in the app, and a contact accept, both ways;
 * - messages both ways: a network turn answers the hub, and the owner's message reaches it;
 * - a public sub-tau answers `host.example/@bob/coach`; a private one is dropped unanswered;
 * - the odd-hop answer of the hub's own sub-tau, and the hop limit;
 * - a visit from the universe bob joined, answered to the universe.
 *
 * The hub's side of the same exchange, with a real hub and a kit spine, is the two-process
 * check in cloud/host/README.md ("Talking to a local hub").
 */

import { reset } from "cloudflare:test";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { replyId } from "../src/net/frames";
import { api, apiJson, HOST, mockFetch, type Owner, request, type Seen } from "./helpers";
import {
  cardFor,
  decide,
  deliver,
  hostedEnvelope,
  hostedOwner,
  identityOf,
  opened,
  postEnvelope,
  seedIdentity,
  setSettings,
  vectors,
  VECTOR_TS,
} from "./net-helpers";

const BOB = "host.example/@bob";
const ALICE = "alice.example.com";
const ALICE_CARD = "https://alice.example.com/.well-known/tau.json";
const ALICE_INBOX = "https://alice.example.com/net/inbox";
const UNIVERSE = "universe.example.com";

beforeEach(async () => {
  await reset();
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(VECTOR_TS * 1000);
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

interface NetState {
  address: string;
  contacts: { address: string; state: string; name: string; note: string }[];
  pending: number;
}

/** alice's card and inbox (a hub behind its spine), and the universe's card and inbox. */
async function hub() {
  const alice = await identityOf("alice");
  const universe = await identityOf("universe");
  const { seen } = mockFetch({
    [ALICE_CARD]: () => Response.json(cardFor(alice, ALICE, "Alice's tau")),
    [ALICE_INBOX]: () => Response.json({ status: "queued", id: "x" }, { status: 202 }),
    [`https://${UNIVERSE}/.well-known/tau.json`]: () => Response.json(cardFor(universe, UNIVERSE, "the universe")),
    [`https://${UNIVERSE}/net/inbox`]: () => Response.json({ status: "queued", id: "x" }, { status: 202 }),
  });
  return { alice, universe, seen };
}

/** bob: onboarded on the fake provider, with bob's test identity, answering at host.example. */
async function bob(): Promise<Owner> {
  const owner = await hostedOwner("bob");
  await seedIdentity("bob", vectors.identities.bob.identity);
  return owner;
}

async function net(owner: Owner): Promise<NetState> {
  return (await apiJson<NetState>(owner, "GET", "/api/host/net")).body;
}

async function fromBob(seen: Seen[]) {
  const alice = await identityOf("alice");
  return opened(seen, ALICE_INBOX, alice, vectors.identities.bob.sign_key);
}

/** alice becomes bob's accepted contact through her tau-net contact request. */
async function contacts(owner: Owner): Promise<void> {
  const request = hostedEnvelope("hosted_contact_request");
  expect((await deliver("bob", request.envelope)).status).toBe(202);
  expect((await api(owner, "POST", "/api/host/net/contacts/accept", { address: ALICE })).status).toBe(200);
}

describe("a hub and a hosted tau", () => {
  it("serves the card tau-net expects for the hosted address", async () => {
    await bob();
    const card = await (await request(HOST, "/@bob/.well-known/tau.json")).json();
    expect(card).toEqual({
      v: 1,
      address: BOB,
      name: "@bob",
      sign_key: vectors.identities.bob.sign_key,
      box_key: vectors.identities.bob.box_key,
      inbox: "https://host.example/@bob/net/inbox",
      software: "tau-host/0.1.0",
    });
  });

  it("takes the hub's contact request; the owner accepts it and the hub gets a contact_accept", async () => {
    const { seen } = await hub();
    const owner = await bob();
    const request = hostedEnvelope("hosted_contact_request");
    const response = await deliver("bob", request.envelope);
    expect(response.status).toBe(202);
    expect(await response.json()).toEqual({ status: "accepted", id: request.payload.id });

    let state = await net(owner);
    expect(state.pending).toBe(1);
    expect(state.contacts).toMatchObject([
      { address: ALICE, state: "pending_in", name: "Alice's tau", note: "Hi Bob, shall our taus connect? 🌿" },
    ]);
    // Nothing goes back before the owner decides.
    expect(seen.filter((s) => s.url === ALICE_INBOX)).toEqual([]);

    expect((await api(owner, "POST", "/api/host/net/contacts/accept", { address: ALICE })).status).toBe(200);
    state = await net(owner);
    expect(state.contacts).toMatchObject([{ address: ALICE, state: "accepted" }]);
    const [accept] = await fromBob(seen);
    expect(accept?.payload).toMatchObject({ kind: "contact_accept", from: BOB, to: ALICE, hops: 0 });
    expect(accept?.content).toEqual({ name: "@bob" });

    // The same request again is a duplicate (the inbox's `(from, id)` guard).
    const again = await postEnvelope("bob", request.envelope);
    expect(again.status).toBe(200);
    expect(await again.json()).toEqual({ status: "duplicate", id: request.payload.id });
  });

  it("answers the hub's message with a network turn, in the thread, one hop further", async () => {
    const { seen } = await hub();
    const owner = await bob();
    await contacts(owner);
    const message = hostedEnvelope("hosted_message");
    expect((await deliver("bob", message.envelope)).status).toBe(202);
    const replies = (await fromBob(seen)).filter((e) => e.payload.kind === "message");
    expect(replies).toHaveLength(1);
    const reply = replies[0];
    expect(reply?.content).toEqual({ text: "(fake) You said: Merhaba Bob! How is your week going?" });
    expect(reply?.payload).toMatchObject({
      from: BOB,
      to: ALICE,
      thread: message.payload.thread,
      reply_to: message.payload.id,
      hops: 1,
      id: await replyId(BOB, ALICE, message.payload.id),
    });
    const log = (await apiJson<{ direction: string; kind: string; text: string }[]>(owner, "GET", `/api/host/net/log?address=${ALICE}`)).body;
    expect(log.map((e) => `${e.direction} ${e.kind}`)).toEqual(["in contact_request", "out contact_accept", "in message", "out message"]);
  });

  it("a public sub-tau answers host.example/@bob/coach; a private one is dropped unanswered", async () => {
    const { seen } = await hub();
    const owner = await bob();
    await contacts(owner);
    for (const [name, isPublic] of [
      ["coach", true],
      ["diary", false],
    ] as const) {
      const created = await api(owner, "POST", "/api/host/subs", { name, about: `The ${name}.`, persona: "Help.", public: isPublic });
      expect(created.status).toBe(201);
    }
    await deliver("bob", hostedEnvelope("hosted_message_for_sub").envelope);
    await deliver("bob", hostedEnvelope("hosted_message_for_private_sub").envelope);
    const replies = (await fromBob(seen)).filter((e) => e.payload.kind === "message");
    expect(replies.map((e) => e.content)).toEqual([{ text: "(fake /coach) You said: Coach, can you plan my 10k?", sub: "coach" }]);
    expect(replies[0]?.payload.hops).toBe(1);
    const log = (await apiJson<{ id: string; own_sub: string | null }[]>(owner, "GET", "/api/host/net/log")).body;
    expect(log.filter((e) => e.own_sub === "coach")).toHaveLength(2);
    expect(log.find((e) => e.id === hostedEnvelope("hosted_message_for_private_sub").payload.id)).toBeUndefined();
  });

  it("the hub's own sub-tau (odd hops) is answered by the main tau, and the hop limit holds", async () => {
    const { seen } = await hub();
    const owner = await bob();
    await contacts(owner);
    const fromSub = hostedEnvelope("hosted_reply_from_sub");
    await deliver("bob", fromSub.envelope);
    const [reply] = (await fromBob(seen)).filter((e) => e.payload.kind === "message");
    expect(reply?.content).toEqual({ text: "(fake) You said: Your plan looks good, start slow.", sub: "coach" });
    expect(reply?.payload.hops).toBe(2);
    await deliver("bob", hostedEnvelope("hosted_message_last_hop").envelope);
    expect((await fromBob(seen)).filter((e) => e.payload.kind === "message")).toHaveLength(1);
  });

  it("bob asks the hub (after the owner's approval), the hub accepts, and bob writes to it", async () => {
    const { seen } = await hub();
    const owner = await bob();
    const asked = await apiJson<{ id: string; tool: string; status: string }>(owner, "POST", "/api/host/net/contacts", {
      address: ALICE,
      note: "Hello from a hosted tau",
    });
    expect(asked.status).toBe(202);
    expect(asked.body).toMatchObject({ tool: "net_add", status: "pending" });
    expect(seen.filter((s) => s.url === ALICE_INBOX)).toEqual([]);
    const done = await decide(owner, asked.body.id, "approve");
    expect(done.find((e) => e.t === "tool_result")).toMatchObject({ error: false, text: `Asked ${ALICE} to become a contact.` });
    const [request] = await fromBob(seen);
    expect(request?.payload).toMatchObject({ kind: "contact_request", from: BOB, to: ALICE, hops: 0 });
    expect(request?.content).toEqual({ name: "@bob", text: "Hello from a hosted tau" });
    expect((await net(owner)).contacts).toMatchObject([{ address: ALICE, state: "pending_out" }]);

    await deliver("bob", hostedEnvelope("hosted_contact_accept").envelope);
    expect((await net(owner)).contacts).toMatchObject([{ address: ALICE, state: "accepted", name: "Alice's tau" }]);

    const send = await apiJson<{ id: string }>(owner, "POST", "/api/host/net/send", { to: `${ALICE}/coach`, text: "Can your coach help me?" });
    expect(send.status).toBe(202);
    await decide(owner, send.body.id, "approve");
    const [message] = (await fromBob(seen)).filter((e) => e.payload.kind === "message");
    expect(message?.content).toEqual({ text: "Can your coach help me?", sub: "coach" });
    expect(message?.payload).toMatchObject({ hops: 0, reply_to: null });
    expect(message?.payload.thread).toBe(message?.payload.id);
  });

  it("answers a visit from the universe it joined, to the universe, and pins its keys", async () => {
    const { seen } = await hub();
    const owner = await bob();
    await api(owner, "POST", "/api/host/subs", {
      name: "coach",
      about: "A running coach.",
      persona: "Plan runs.",
      public: true,
      web: true,
    });
    // Joined as far as this tau knows; the universe itself is not asked here (test/net.test.ts).
    await setSettings("bob", { universe: true, universe_joined: true, universe_next_at: 4_000_000_000 });
    const visit = hostedEnvelope("hosted_visit");
    await deliver("bob", visit.envelope);
    const universe = await identityOf("universe");
    const answers = await opened(seen, `https://${UNIVERSE}/net/inbox`, universe, vectors.identities.bob.sign_key);
    expect(answers).toHaveLength(1);
    expect(answers[0]?.content).toEqual({ text: "(fake /coach) You said: Hi coach! Can you plan my week?", sub: "coach" });
    expect(answers[0]?.payload).toMatchObject({ kind: "message", thread: "visitor-thread-000000000002", reply_to: visit.payload.id, hops: 1 });
    // A visit is no contact.
    expect((await net(owner)).contacts).toEqual([]);
  });
});
