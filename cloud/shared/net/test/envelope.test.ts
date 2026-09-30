/** Identities, seals and envelopes: round trips, defaults, limits and every refusal. */

import { describe, expect, it } from "vitest";

import {
  aadFor,
  b64uDecode,
  b64uEncode,
  BadSignature,
  BoxError,
  buildEnvelope,
  compactJson,
  encodePayload,
  EnvelopeError,
  EnvelopeTooLarge,
  Identity,
  IdentityError,
  ID_PATTERN,
  MalformedEnvelope,
  MAX_MESSAGE_CHARS,
  newId,
  openBox,
  openEnvelope,
  openVerified,
  parseContent,
  parsePayload,
  parseWireEnvelope,
  peekSender,
  seal,
  sealBytes,
  signPayload,
  utf8Encode,
  type Kind,
} from "../index.ts";

const HOST = "tau.example.com/@alice";
const HUB = "bob.example.com";

async function pair() {
  return { alice: await Identity.generate(), bob: await Identity.generate() };
}

describe("identities", () => {
  it("round-trips through the stored form and the env value", async () => {
    const id = await Identity.generate();
    const again = await Identity.fromJson(id.toIdentityJson());
    expect(again.signKey).toBe(id.signKey);
    expect(again.boxKey).toBe(id.boxKey);
    expect((await Identity.fromEnvValue(` ${id.toEnvValue()}\n`)).boxKey).toBe(id.boxKey);
    expect(id.publicFields("Alice's tau")).toEqual({
      name: "Alice's tau",
      sign_key: id.signKey,
      box_key: id.boxKey,
    });
  });

  it("never shows its seeds when serialised or printed", async () => {
    const id = await Identity.generate();
    const seeds = Object.values(id.toIdentityJson()).filter((v) => typeof v === "string");
    for (const text of [JSON.stringify(id), String(id), JSON.stringify({ id })]) {
      for (const seed of seeds) expect(text).not.toContain(seed);
    }
  });

  it("refuses malformed identities without echoing them", async () => {
    const seed = b64uEncode(new Uint8Array(32).fill(7));
    const bad = [
      null,
      { v: 2, sign_seed: seed, box_seed: seed },
      { v: 1, sign_seed: seed },
      { v: 1, sign_seed: "not base64url!", box_seed: seed },
      { v: 1, sign_seed: b64uEncode(new Uint8Array(31)), box_seed: seed },
    ];
    for (const data of bad) {
      const error = await Identity.fromJson(data).catch((e: unknown) => e);
      expect(error).toBeInstanceOf(IdentityError);
      expect(String(error)).not.toContain(seed);
    }
    await expect(Identity.fromEnvValue("%%%")).rejects.toBeInstanceOf(IdentityError);
    await expect(Identity.fromEnvValue(b64uEncode(utf8Encode("[]")))).rejects.toBeInstanceOf(
      IdentityError,
    );
    await expect(Identity.fromSeeds(new Uint8Array(32), new Uint8Array(3))).rejects.toBeInstanceOf(
      IdentityError,
    );
  });
});

describe("envelopes", () => {
  const cases: [Kind, Record<string, unknown>][] = [
    ["contact_request", { name: "Alice's tau", text: "Merhaba!" }],
    ["contact_accept", { name: "Bob's tau" }],
    ["message", { text: "Hello 🌟" }],
    ["message", { text: "For your coach", sub: "coach" }],
    ["visit", { text: "Hi from a visitor", sub: "coach" }],
  ];

  it.each(cases)("round-trips a %s between both address forms", async (kind, content) => {
    const { alice, bob } = await pair();
    const { envelope, payload } = await buildEnvelope(alice, {
      from: HOST,
      to: HUB,
      recipientBoxKey: bob.boxKey,
      kind,
      content,
    });
    expect(peekSender(envelope)).toBe(HOST);
    const opened = await openEnvelope(parseWireEnvelope(envelope), alice.signKey, bob);
    expect(opened.payload).toEqual(payload);
    expect(opened.content).toEqual(content);
  });

  it("starts a new conversation by default", async () => {
    const { alice, bob } = await pair();
    const before = Math.floor(Date.now() / 1000);
    const { payload } = await buildEnvelope(alice, {
      from: HUB,
      to: HOST,
      recipientBoxKey: bob.boxKeyBytes,
      kind: "message",
      content: { text: "hi" },
    });
    expect(payload.id).toMatch(ID_PATTERN);
    expect(payload.id).toHaveLength(24);
    expect(payload.thread).toBe(payload.id);
    expect(payload.reply_to).toBeNull();
    expect(payload.hops).toBe(0);
    expect(payload.ts).toBeGreaterThanOrEqual(before);
    expect(newId()).not.toBe(newId());
  });

  it("counts message length in code points, like Python", () => {
    const emoji = "🌟".repeat(MAX_MESSAGE_CHARS);
    expect(parseContent("message", { text: emoji })).toEqual({ text: emoji });
    expect(() => parseContent("message", { text: `${emoji}x` })).toThrow(BoxError);
    expect(() => parseContent("visit", { text: `${emoji}x`, sub: "coach" })).toThrow(BoxError);
  });

  it.each([
    ["contact_request", { name: "x" }],
    ["contact_accept", {}],
    ["message", { text: 1 }],
    ["message", { text: "x", sub: "Coach" }],
    ["message", { text: "x", sub: 5 }],
    ["visit", { text: "x" }],
    ["visit", { text: "x", sub: null }],
    ["other", { text: "x" }],
  ])("refuses %s content %j", (kind, content) => {
    expect(() => parseContent(kind, content)).toThrow(BoxError);
  });

  it("refuses to build what a recipient would refuse", async () => {
    const { alice, bob } = await pair();
    const base = { from: HOST, to: HUB, recipientBoxKey: bob.boxKey };
    await expect(
      buildEnvelope(alice, { ...base, kind: "gossip" as Kind, content: { text: "x" } }),
    ).rejects.toBeInstanceOf(MalformedEnvelope);
    await expect(
      buildEnvelope(alice, { ...base, kind: "visit", content: { text: "x" } }),
    ).rejects.toBeInstanceOf(BoxError);
    await expect(
      buildEnvelope(alice, {
        ...base,
        from: "tau.example.com/@Alice",
        kind: "message",
        content: { text: "x" },
      }),
    ).rejects.toBeInstanceOf(MalformedEnvelope);
    await expect(
      buildEnvelope(alice, {
        ...base,
        recipientBoxKey: "short",
        kind: "message",
        content: { text: "x" },
      }),
    ).rejects.toBeInstanceOf(BoxError);
    await expect(
      buildEnvelope(alice, {
        ...base,
        kind: "contact_request",
        content: { name: "x", text: "x".repeat(60_000) },
      }),
    ).rejects.toBeInstanceOf(EnvelopeTooLarge);
  });

  it("refuses a bad signature, then malformed payloads after the check", async () => {
    const { alice, bob } = await pair();
    const { envelope, payloadBytes } = await buildEnvelope(alice, {
      from: HOST,
      to: HUB,
      recipientBoxKey: bob.boxKey,
      kind: "message",
      content: { text: "hi" },
    });
    await expect(openVerified(envelope, bob.signKey)).rejects.toBeInstanceOf(BadSignature);
    await expect(openVerified(envelope, "not a key")).rejects.toBeInstanceOf(BadSignature);
    const tampered = new TextDecoder().decode(payloadBytes).replace('"hops":0', '"hops":1');
    await expect(
      openVerified({ payload: b64uEncode(utf8Encode(tampered)), sig: envelope.sig }, alice.signKey),
    ).rejects.toBeInstanceOf(BadSignature);

    const notJson = utf8Encode("not json");
    const signed = {
      payload: b64uEncode(notJson),
      sig: b64uEncode(await signPayload(alice, notJson)),
    };
    await expect(openVerified(signed, alice.signKey)).rejects.toBeInstanceOf(MalformedEnvelope);
    expect(() => peekSender(signed)).toThrow(MalformedEnvelope);
    expect(() => parseWireEnvelope({ payload: "a b", sig: "" })).toThrow(MalformedEnvelope);
    expect(() => parseWireEnvelope([])).toThrow(EnvelopeError);
  });

  it("validates every header field", async () => {
    const { alice, bob } = await pair();
    const { payload } = await buildEnvelope(alice, {
      from: HOST,
      to: HUB,
      recipientBoxKey: bob.boxKey,
      kind: "message",
      content: { text: "hi" },
    });
    const good = JSON.parse(new TextDecoder().decode(encodePayload(payload))) as Record<
      string,
      unknown
    >;
    expect(parsePayload(good)).toEqual(payload);
    const broken: Record<string, unknown>[] = [
      { v: 2 },
      { v: true },
      { id: "short" },
      { kind: "gossip" },
      { from: "tau.example.com/@" },
      { to: "Bob.example.com" },
      { ts: 1.5 },
      { thread: "" },
      { reply_to: "short" },
      { hops: -1 },
      { box: { epk: "a b", nonce: "", ct: "" } },
      { box: null },
    ];
    for (const change of broken) {
      expect(() => parsePayload({ ...good, ...change })).toThrow(MalformedEnvelope);
    }
    const missing = { ...good };
    delete missing.hops;
    expect(() => parsePayload(missing)).toThrow(/payload misses hops/);
  });
});

describe("seals", () => {
  it("binds a box to its header and to its recipient", async () => {
    const { alice, bob } = await pair();
    const aad = aadFor("x".repeat(16), "message", HOST, HUB);
    const box = await seal({ text: "hi" }, bob.boxKey, aad);
    expect(await openBox(box, bob, aad)).toEqual({ text: "hi" });
    await expect(openBox(box, alice, aad)).rejects.toBeInstanceOf(BoxError);
    await expect(
      openBox(box, bob, aadFor("y".repeat(16), "message", HOST, HUB)),
    ).rejects.toBeInstanceOf(BoxError);
    const ct = b64uDecode(box.ct)!;
    ct[0] = (ct[0] as number) ^ 1;
    await expect(openBox({ ...box, ct: b64uEncode(ct) }, bob, aad)).rejects.toBeInstanceOf(
      BoxError,
    );
    await expect(openBox({ ...box, nonce: "AAAA" }, bob, aad)).rejects.toBeInstanceOf(BoxError);
  });

  it("refuses a low-order recipient key and content that is not an object", async () => {
    const { bob } = await pair();
    const aad = utf8Encode("aad");
    await expect(seal({}, new Uint8Array(32), aad)).rejects.toBeInstanceOf(BoxError);
    const list = await sealBytes(compactJson([1, 2]), bob.boxKey, aad);
    await expect(openBox(list, bob, aad)).rejects.toThrow(/not an object/);
    const bom = await sealBytes(utf8Encode("﻿{}"), bob.boxKey, aad);
    await expect(openBox(bom, bob, aad)).rejects.toThrow(/not UTF-8 JSON/);
  });

  it("draws a fresh ephemeral key and nonce for every seal", async () => {
    const { bob } = await pair();
    const aad = utf8Encode("aad");
    const [a, b] = await Promise.all([
      seal({ t: 1 }, bob.boxKey, aad),
      seal({ t: 1 }, bob.boxKey, aad),
    ]);
    expect(a.epk).not.toBe(b.epk);
    expect(a.nonce).not.toBe(b.nonce);
  });
});
