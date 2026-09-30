import { env } from "cloudflare:workers";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { b64uEncode } from "../src/crypto";
import {
  envelope,
  inMailbox,
  mailboxCount,
  mockCards,
  newId,
  nowSeconds,
  PEER,
  peerCard,
  postEnvelope,
  publishCard,
  resetStore,
  SELF,
  signRaw,
  spine,
  VECTOR,
} from "./helpers";

const PEER_URL = `https://${PEER}`;

/** The only envelope in the mailbox, as stored. */
async function storedEnvelope(): Promise<string> {
  const row = await inMailbox((sql) =>
    sql.exec<{ envelope: string }>("SELECT envelope FROM mailbox").one(),
  );
  return row.envelope;
}

/** Seeds `count` replay-guard rows for `sender` at the given arrival times. */
async function seedSeen(sender: string, count: number, ts: (i: number) => number, prefix: string) {
  await inMailbox((sql) => {
    for (let i = 0; i < count; i++) {
      sql.exec(
        "INSERT INTO seen (sender, id, ts) VALUES (?, ?, ?)",
        sender,
        `${prefix}-${String(i).padStart(4, "0")}`,
        ts(i),
      );
    }
  });
}

beforeEach(resetStore);
afterEach(() => {
  vi.restoreAllMocks();
});

describe("GET /", () => {
  it("names the spine", async () => {
    const res = await spine("/");
    expect(res.status).toBe(200);
    expect(await res.text()).toBe(`tau spine ${SELF}`);
  });
});

describe("card", () => {
  it("is 404 no_card before the hub publishes one", async () => {
    const res = await spine("/.well-known/tau.json");
    expect(res.status).toBe(404);
    expect(await res.json()).toEqual({ error: "no_card" });
  });

  it("is served with CORS and caching after PUT /hub/card", async () => {
    const put = await publishCard();
    expect(put.status).toBe(200);
    const expected = {
      v: 1,
      address: SELF,
      name: "Bob's tau",
      sign_key: VECTOR.signKey,
      box_key: VECTOR.boxKey,
      inbox: `https://${SELF}/net/inbox`,
      software: "tau-spine/0.1.0",
    };
    expect(await put.json()).toEqual(expected);

    const res = await spine("/.well-known/tau.json");
    expect(res.status).toBe(200);
    expect(res.headers.get("access-control-allow-origin")).toBe("*");
    expect(res.headers.get("cache-control")).toBe("public, max-age=300");
    const card = await res.json();
    expect(card).toEqual(expected);
    // Field order as in §2.
    expect(Object.keys(card as object)).toEqual(Object.keys(expected));
  });
});

describe("POST /net/inbox", () => {
  beforeEach(async () => {
    await publishCard();
  });

  it("queues a valid envelope and fetches the sender's card once", async () => {
    const fetchSpy = mockCards({ [PEER_URL]: peerCard() });
    const first = await envelope();
    const res = await postEnvelope(first);
    expect(res.status).toBe(202);
    expect(await res.json()).toEqual({ status: "queued", id: first.id });

    const second = await envelope({ kind: "contact_request" });
    expect((await postEnvelope(second)).status).toBe(202);
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    expect(String(fetchSpy.mock.calls[0]?.[0])).toBe(`${PEER_URL}/.well-known/tau.json`);
    expect(await env.TAU.get(`peer:${PEER}`, "json")).toEqual(peerCard());

    const rows = await inMailbox((sql) =>
      sql
        .exec<{ sender: string; envelope: string }>(
          "SELECT sender, envelope FROM mailbox ORDER BY seq",
        )
        .toArray(),
    );
    expect(rows.map((row) => row.sender)).toEqual([PEER, PEER]);
    expect(JSON.parse(rows[0]!.envelope)).toEqual({
      payload: first.payload,
      sig: first.sig,
    });
  });

  it("accepts the static test vector at its own time, and nothing tampered", async () => {
    // The vector goes from alice.example to bob.example at ts 1790000000.
    vi.useFakeTimers({ toFake: ["Date"] });
    try {
      vi.setSystemTime(new Date(1_790_000_000 * 1000 + 30_000));
      mockCards({ [PEER_URL]: peerCard() });
      const tampered = b64uEncode(
        new TextEncoder().encode(VECTOR.decoded.replace('"hops":0', '"hops":1')),
      );
      const bad = await postEnvelope({ payload: tampered, sig: VECTOR.sig });
      expect(bad.status).toBe(403);
      const res = await postEnvelope({ payload: VECTOR.payload, sig: VECTOR.sig });
      expect(res.status).toBe(202);
      expect(await res.json()).toEqual({ status: "queued", id: "01J0000000000000000000TEST" });
    } finally {
      vi.useRealTimers();
    }
  });

  it("rejects the static test vector as stale today", async () => {
    const res = await postEnvelope({ payload: VECTOR.payload, sig: VECTOR.sig });
    expect(await res.json()).toEqual({ error: "stale" });
  });

  it("drops unknown top-level keys and stores payload and sig as posted", async () => {
    mockCards({ [PEER_URL]: peerCard() });
    const env1 = await envelope();
    expect((await postEnvelope({ ...env1, extra: "x" })).status).toBe(202);
    expect(JSON.parse(await storedEnvelope())).toEqual({ payload: env1.payload, sig: env1.sig });
  });

  describe("rejects in the §4 order", () => {
    it("413 too_large", async () => {
      const res = await postEnvelope("x".repeat(65_537));
      expect(res.status).toBe(413);
      expect(await res.json()).toEqual({ error: "too_large" });
    });

    it("413 too_large wins over everything else", async () => {
      const big = await envelope({ box: { epk: "AAAA", nonce: "AAAA", ct: "A".repeat(66_000) } });
      expect((await postEnvelope(big)).status).toBe(413);
    });

    const badBodies: [string, () => Promise<unknown>][] = [
      ["not JSON", async () => "{nope"],
      ["not an object", async () => "[1,2]"],
      ["missing sig", async () => ({ payload: (await envelope()).payload })],
      ["sig not a string", async () => ({ payload: (await envelope()).payload, sig: 5 })],
      ["payload not b64u", async () => ({ payload: "a+b/", sig: (await envelope()).sig })],
      ["sig not b64u", async () => ({ payload: (await envelope()).payload, sig: "***" })],
      ["payload not JSON", async () => signRaw(new TextEncoder().encode("hello"))],
      ["payload an array", async () => signRaw(new TextEncoder().encode("[]"))],
      ["missing field", async () => envelope({ thread: undefined })],
      ["v not 1", async () => envelope({ v: 2 })],
      ["v a string", async () => envelope({ v: "1" })],
      ["unknown kind", async () => envelope({ kind: "spam" })],
      ["bad from", async () => envelope({ from: "Alice.Example" })],
      ["bad id", async () => envelope({ id: "short" })],
      ["ts not an integer", async () => envelope({ ts: 1.5 })],
      ["hops negative", async () => envelope({ hops: -1 })],
      ["reply_to a number", async () => envelope({ reply_to: 3 })],
      ["box without ct", async () => envelope({ box: { epk: "AAAA", nonce: "AAAA" } })],
    ];
    for (const [name, make] of badBodies) {
      it(`400 bad_request: ${name}`, async () => {
        const res = await postEnvelope(await make());
        expect(res.status).toBe(400);
        const body = (await res.json()) as { error: string; detail: string };
        expect(body.error).toBe("bad_request");
        expect(typeof body.detail).toBe("string");
      });
    }

    it("400 wrong_recipient", async () => {
      const res = await postEnvelope(await envelope({ to: "carol.example" }));
      expect(res.status).toBe(400);
      expect(await res.json()).toEqual({ error: "wrong_recipient" });
    });

    it("400 stale, both ways", async () => {
      for (const ts of [nowSeconds() - 301, nowSeconds() + 301]) {
        const res = await postEnvelope(await envelope({ ts }));
        expect(res.status).toBe(400);
        expect(await res.json()).toEqual({ error: "stale" });
      }
      mockCards({ [PEER_URL]: peerCard() });
      expect((await postEnvelope(await envelope({ ts: nowSeconds() - 290 }))).status).toBe(202);
    });

    const unavailable: [string, () => ReturnType<typeof mockCards>][] = [
      ["network error", () => mockCards({})],
      ["404", () => mockCards({ [PEER_URL]: new Response("no", { status: 404 }) })],
      [
        "redirect",
        () =>
          mockCards({
            [PEER_URL]: new Response(null, {
              status: 302,
              headers: { location: "https://elsewhere.example/" },
            }),
          }),
      ],
      ["not JSON", () => mockCards({ [PEER_URL]: new Response("<html>") })],
      ["too large", () => mockCards({ [PEER_URL]: { ...peerCard(), pad: "x".repeat(9_000) } })],
      ["wrong address", () => mockCards({ [PEER_URL]: peerCard("mallory.example") })],
      ["wrong version", () => mockCards({ [PEER_URL]: { ...peerCard(), v: 2 } })],
      ["short sign_key", () => mockCards({ [PEER_URL]: peerCard(PEER, "AAAA") })],
    ];
    for (const [name, mock] of unavailable) {
      it(`502 sender_card_unavailable: ${name}`, async () => {
        mock();
        const res = await postEnvelope(await envelope());
        expect(res.status).toBe(502);
        expect(await res.json()).toEqual({ error: "sender_card_unavailable" });
        expect(await env.TAU.get(`peer:${PEER}`)).toBeNull();
      });
    }

    it("502 sender_card_unavailable: timeout after 5 s", async () => {
      vi.spyOn(globalThis, "fetch").mockImplementation(
        (_input, init) =>
          new Promise((_resolve, reject) => {
            init?.signal?.addEventListener("abort", () => reject(init.signal?.reason));
          }),
      );
      const started = Date.now();
      const res = await postEnvelope(await envelope());
      expect(res.status).toBe(502);
      expect(Date.now() - started).toBeGreaterThanOrEqual(4_900);
    }, 10_000);

    it("fetches http:// only for loopback peers when ALLOW_INSECURE_PEERS=1", async () => {
      // This project runs with ALLOW_INSECURE_PEERS=0: a 127.0.0.1 sender is fetched over https.
      const spy = mockCards({});
      await postEnvelope(await envelope({ from: "127.0.0.1:8787" }));
      expect(String(spy.mock.calls[0]?.[0])).toBe("https://127.0.0.1:8787/.well-known/tau.json");
    });

    it("403 bad_signature", async () => {
      mockCards({ [PEER_URL]: peerCard() });
      const signedByOther = await envelope({}, VECTOR.boxSeed);
      const res = await postEnvelope(signedByOther);
      expect(res.status).toBe(403);
      expect(await res.json()).toEqual({ error: "bad_signature" });

      // A valid signature over different bytes (payload swapped) fails too.
      const a = await envelope();
      const b = await envelope();
      expect((await postEnvelope({ payload: a.payload, sig: b.sig })).status).toBe(403);
      expect(await mailboxCount()).toBe(0);
    });

    it("200 duplicate, idempotent and not stored twice", async () => {
      mockCards({ [PEER_URL]: peerCard() });
      const one = await envelope();
      expect((await postEnvelope(one)).status).toBe(202);
      const again = await postEnvelope(one);
      expect(again.status).toBe(200);
      expect(await again.json()).toEqual({ status: "duplicate", id: one.id });
      // The same id with a new signature (new ts) is still a duplicate.
      const resent = await envelope({ id: one.id, ts: nowSeconds() - 1 });
      expect(await (await postEnvelope(resent)).json()).toEqual({
        status: "duplicate",
        id: one.id,
      });
      expect(await mailboxCount()).toBe(1);
    });

    it("429 rate_limited after 60 envelopes from one sender in an hour", async () => {
      mockCards({ [PEER_URL]: peerCard(), "https://carol.example": peerCard("carol.example") });
      const now = nowSeconds();
      await seedSeen(PEER, 60, (i) => now - 3_500 + i, "old-envelope");
      const res = await postEnvelope(await envelope());
      expect(res.status).toBe(429);
      expect(await res.json()).toEqual({ error: "rate_limited" });
      // Another sender is not affected.
      expect((await postEnvelope(await envelope({ from: "carol.example" }))).status).toBe(202);
      // Rows older than an hour do not count.
      await inMailbox((sql) => sql.exec("UPDATE seen SET ts = ts - 200 WHERE sender = ?", PEER));
      expect((await postEnvelope(await envelope())).status).toBe(202);
    });

    it("duplicate is judged before the rate limit", async () => {
      mockCards({ [PEER_URL]: peerCard() });
      const one = await envelope();
      expect((await postEnvelope(one)).status).toBe(202);
      await seedSeen(PEER, 60, () => nowSeconds(), "filler-envelope");
      expect(await (await postEnvelope(one)).json()).toEqual({ status: "duplicate", id: one.id });
    });

    it("503 mailbox_full at 1000 undelivered envelopes", async () => {
      mockCards({ [PEER_URL]: peerCard() });
      await inMailbox((sql) =>
        sql.exec(
          "WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM n WHERE x < 1000) " +
            "INSERT INTO mailbox (sender, envelope, received_at) SELECT 'other.example', '{}', ? FROM n",
          nowSeconds(),
        ),
      );
      const res = await postEnvelope(await envelope());
      expect(res.status).toBe(503);
      expect(await res.json()).toEqual({ error: "mailbox_full" });
      expect(await mailboxCount()).toBe(1000);
    });
  });

  it("accepts mail to itself using its own card, without a fetch", async () => {
    const spy = mockCards({});
    const res = await postEnvelope(await envelope({ from: SELF }));
    expect(res.status).toBe(202);
    expect(spy).not.toHaveBeenCalled();
  });

  it("verifies the exact payload bytes, whatever their JSON formatting", async () => {
    mockCards({ [PEER_URL]: peerCard() });
    const id = newId();
    const text = `{ "v": 1, "id": "${id}", "kind": "message", "from": "${PEER}", "to": "${SELF}",
      "ts": ${nowSeconds()}, "thread": "${id}", "reply_to": null, "hops": 2,
      "box": {"epk": "AAAA", "nonce": "AAAA", "ct": "AAAA"}, "extra": true }`;
    const res = await postEnvelope(await signRaw(new TextEncoder().encode(text)));
    expect(res.status).toBe(202);
    const stored = JSON.parse(await storedEnvelope()) as { payload: string };
    expect(stored.payload).toBe(b64uEncode(new TextEncoder().encode(text)));
  });

  it("405 for other methods", async () => {
    expect((await spine("/net/inbox")).status).toBe(405);
  });
});
