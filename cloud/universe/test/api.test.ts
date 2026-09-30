import { reset } from "cloudflare:test";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { b64uEncode } from "../src/crypto";
import {
  ALICE,
  BOB,
  CAROL,
  card,
  mockCards,
  mockTaus,
  nextTs,
  nowSeconds,
  payloadOf,
  post,
  prepareTaus,
  resetClocks,
  send,
  signed,
  signRaw,
  snapshot,
  UNIVERSE,
  universe,
} from "./helpers";

beforeAll(prepareTaus);
beforeEach(async () => {
  await reset();
  resetClocks();
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

async function body(res: Response): Promise<unknown> {
  return res.json();
}

describe("POST /api/join", () => {
  it("lists the tau with its card name, owner and about", async () => {
    mockTaus(ALICE);
    const ts = nextTs(ALICE.address);
    const res = await send("join", ALICE, { ts, owner: "Alice", about: "Tinkers with robots." });
    expect(res.status).toBe(200);
    expect(await body(res)).toEqual({
      ok: true,
      url: `https://${UNIVERSE}/universe#${ALICE.address}`,
    });

    const snap = await snapshot();
    expect(snap.taus).toEqual([
      {
        address: ALICE.address,
        name: ALICE.name,
        owner: "Alice",
        about: "Tinkers with robots.",
        joined_at: ts,
        last_seen: ts,
        online: true,
        handle: null,
        subs: [],
      },
    ]);
    expect(snap.stats).toEqual({ taus: 1, online: 1, messages: 0 });
  });

  it("updates a joined tau and keeps its first joined_at", async () => {
    mockTaus(ALICE);
    const first = nextTs(ALICE.address);
    expect((await send("join", ALICE, { ts: first, owner: "Alice" })).status).toBe(200);
    const second = nextTs(ALICE.address);
    expect((await send("join", ALICE, { ts: second, owner: "A.", about: "new" })).status).toBe(200);
    const [tau] = (await snapshot()).taus;
    expect(tau).toMatchObject({ owner: "A.", about: "new", joined_at: first, last_seen: second });
  });

  it("accepts a join without owner and about", async () => {
    mockTaus(ALICE);
    const payload = payloadOf("join", ALICE);
    delete payload.owner;
    delete payload.about;
    const wire = await signRaw(new TextEncoder().encode(JSON.stringify(payload)), ALICE.seed);
    expect((await post("/api/join", wire)).status).toBe(200);
    expect((await snapshot()).taus[0]).toMatchObject({ owner: "", about: "" });
  });

  it("strips control characters from owner, about and the card name", async () => {
    mockCards({
      [`https://${ALICE.address}`]: card(ALICE, { name: "Alice\u0000's\ttau‮" }),
    });
    const res = await send("join", ALICE, {
      owner: " Al\u0007ice\n ",
      about: "line one\r\nline two⁦!",
    });
    expect(res.status).toBe(200);
    expect((await snapshot()).taus[0]).toMatchObject({
      name: "Alice 's tau",
      owner: "Al ice",
      about: "line one line two !",
    });
  });

  it("counts owner and about in characters, not UTF-16 units", async () => {
    mockTaus(ALICE);
    // 60 emoji are 120 UTF-16 units and still 60 characters.
    const owner = "🦊".repeat(60);
    expect((await send("join", ALICE, { owner })).status).toBe(200);
    expect((await snapshot()).taus[0]?.owner).toBe(owner);
    const res = await send("join", ALICE, { owner: `${owner}x` });
    expect(res.status).toBe(400);
  });
});

describe("POST /api/report", () => {
  beforeEach(async () => {
    mockTaus(ALICE, BOB, CAROL);
    for (const tau of [ALICE, BOB]) expect((await send("join", tau)).status).toBe(200);
  });

  it("shows a link only when both sides report it, with the smaller count", async () => {
    let res = await send("report", ALICE, { links: [{ peer: BOB.address, messages: 10 }] });
    expect(res.status).toBe(200);
    expect(await body(res)).toEqual({ ok: true, visible_links: 0 });
    expect((await snapshot()).links).toEqual([]);

    res = await send("report", BOB, { links: [{ peer: ALICE.address, messages: 4 }] });
    expect(await body(res)).toEqual({ ok: true, visible_links: 1 });
    const snap = await snapshot();
    expect(snap.links).toEqual([{ a: ALICE.address, b: BOB.address, messages: 4 }]);
    expect(snap.stats.messages).toBe(4);

    res = await send("report", ALICE, { links: [{ peer: BOB.address, messages: 2 }] });
    expect(await body(res)).toEqual({ ok: true, visible_links: 1 });
    expect((await snapshot()).links).toEqual([{ a: ALICE.address, b: BOB.address, messages: 2 }]);
  });

  it("orders a link's ends whoever reports first", async () => {
    await send("report", BOB, { links: [{ peer: ALICE.address, messages: 3 }] });
    await send("report", ALICE, { links: [{ peer: BOB.address, messages: 3 }] });
    expect((await snapshot()).links).toEqual([{ a: ALICE.address, b: BOB.address, messages: 3 }]);
  });

  it("keeps a mutual link with zero messages", async () => {
    await send("report", ALICE, { links: [{ peer: BOB.address, messages: 0 }] });
    await send("report", BOB, { links: [{ peer: ALICE.address, messages: 7 }] });
    expect((await snapshot()).links).toEqual([{ a: ALICE.address, b: BOB.address, messages: 0 }]);
  });

  it("replaces the reported links with the new list", async () => {
    await send("report", ALICE, { links: [{ peer: BOB.address, messages: 5 }] });
    await send("report", BOB, { links: [{ peer: ALICE.address, messages: 5 }] });
    expect((await snapshot()).links).toHaveLength(1);
    await send("report", ALICE, { links: [] });
    expect((await snapshot()).links).toEqual([]);
  });

  it("ignores peers that are not joined, and never stores them", async () => {
    // Carol is not joined when Alice reports her.
    const res = await send("report", ALICE, {
      links: [
        { peer: CAROL.address, messages: 9 },
        { peer: "stranger.example", messages: 1 },
      ],
    });
    expect(await body(res)).toEqual({ ok: true, visible_links: 0 });
    expect((await send("join", CAROL)).status).toBe(200);
    await send("report", CAROL, { links: [{ peer: ALICE.address, messages: 9 }] });
    // Alice's earlier claim was dropped, so the link waits for Alice's next report.
    expect((await snapshot()).links).toEqual([]);
    await send("report", ALICE, { links: [{ peer: CAROL.address, messages: 9 }] });
    expect((await snapshot()).links).toEqual([{ a: ALICE.address, b: CAROL.address, messages: 9 }]);
  });

  it("ignores a link to the reporter itself", async () => {
    const res = await send("report", ALICE, { links: [{ peer: ALICE.address, messages: 3 }] });
    expect(await body(res)).toEqual({ ok: true, visible_links: 0 });
    expect((await snapshot()).links).toEqual([]);
  });

  it("refreshes the card name and last_seen", async () => {
    vi.restoreAllMocks();
    mockCards({ [`https://${ALICE.address}`]: card(ALICE, { name: "Alice, renamed" }) });
    const ts = nextTs(ALICE.address) + 5;
    expect((await send("report", ALICE, { ts })).status).toBe(200);
    const tau = (await snapshot()).taus.find((t) => t.address === ALICE.address);
    expect(tau).toMatchObject({ name: "Alice, renamed", last_seen: ts });
  });

  it("is 404 not_joined for a tau that has not joined", async () => {
    const res = await send("report", CAROL);
    expect(res.status).toBe(404);
    expect(await body(res)).toEqual({ error: "not_joined" });
  });
});

describe("public sub-taus in reports", () => {
  beforeEach(async () => {
    mockTaus(ALICE, BOB);
    for (const tau of [ALICE, BOB]) expect((await send("join", tau)).status).toBe(200);
  });

  const aliceIn = async () => {
    const tau = (await snapshot()).taus.find((t) => t.address === ALICE.address);
    // Name and about only: the fields of ADR 0013 have their own tests below.
    return tau && { ...tau, subs: tau.subs.map(({ name, about }) => ({ name, about })) };
  };

  it("stores the reported sub-taus per tau, ordered by name, in the snapshot and /api/taus", async () => {
    const ts = nextTs(ALICE.address);
    const res = await send("report", ALICE, {
      ts,
      subs: [
        { name: "landing", about: "Writes landing-page copy." },
        { name: "coach", about: "A patient running coach." },
      ],
    });
    expect(res.status).toBe(200);
    const expected = [
      {
        name: "coach",
        about: "A patient running coach.",
        web: false,
        starters: [],
        first_seen: ts,
        slug: "coach",
      },
      {
        name: "landing",
        about: "Writes landing-page copy.",
        web: false,
        starters: [],
        first_seen: ts,
        slug: "landing",
      },
    ];
    expect((await snapshot()).taus.find((t) => t.address === ALICE.address)?.subs).toEqual(
      expected,
    );
    expect((await snapshot()).taus.find((t) => t.address === BOB.address)?.subs).toEqual([]);
    const tau = (await (await universe(`/api/taus/${ALICE.address}`)).json()) as {
      subs: unknown;
    };
    expect(tau.subs).toEqual(expected);
  });

  it("keeps an old report without subs valid, and it clears the earlier subs", async () => {
    await send("report", ALICE, { subs: [{ name: "coach", about: "Coach." }] });
    expect((await aliceIn())?.subs).toHaveLength(1);
    // payloadOf builds a report without `subs`, exactly as an older hub sends it.
    const old = payloadOf("report", ALICE, { links: [{ peer: BOB.address, messages: 1 }] });
    expect("subs" in old).toBe(false);
    const res = await post(
      "/api/report",
      await signRaw(new TextEncoder().encode(JSON.stringify(old)), ALICE.seed),
    );
    expect(res.status).toBe(200);
    expect(await body(res)).toEqual({ ok: true, visible_links: 0 });
    expect((await aliceIn())?.subs).toEqual([]);
  });

  it("replaces the list with every report", async () => {
    await send("report", ALICE, {
      subs: [
        { name: "coach", about: "Coach." },
        { name: "landing", about: "Landing." },
      ],
    });
    await send("report", ALICE, { subs: [{ name: "arm", about: "Robot arm helper." }] });
    expect((await aliceIn())?.subs).toEqual([{ name: "arm", about: "Robot arm helper." }]);
    await send("report", ALICE, { subs: [] });
    expect((await aliceIn())?.subs).toEqual([]);
  });

  it("keeps the last entry of a repeated name, sanitises about and allows an empty or missing one", async () => {
    await send("report", ALICE, {
      subs: [
        { name: "coach", about: "first" },
        { name: "coach", about: " second\u0000 line\n " },
        { name: "quiet", about: "" },
        { name: "silent" },
      ],
    });
    expect((await aliceIn())?.subs).toEqual([
      { name: "coach", about: "second line" },
      { name: "quiet", about: "" },
      { name: "silent", about: "" },
    ]);
  });

  it("accepts exactly 20 sub-taus and an about of 200 characters", async () => {
    const subs = Array.from({ length: 20 }, (_, i) => ({
      name: `sub-${String(i).padStart(2, "0")}`,
      about: "🦊".repeat(200),
    }));
    expect((await send("report", ALICE, { subs })).status).toBe(200);
    const stored = (await aliceIn())?.subs ?? [];
    expect(stored).toHaveLength(20);
    expect(stored[0]).toEqual({ name: "sub-00", about: "🦊".repeat(200) });
  });

  it("forgets the sub-taus when the tau leaves", async () => {
    await send("report", ALICE, { subs: [{ name: "coach", about: "Coach." }] });
    expect((await send("leave", ALICE)).status).toBe(200);
    expect(await aliceIn()).toBeUndefined();
    expect((await send("join", ALICE)).status).toBe(200);
    expect((await aliceIn())?.subs).toEqual([]);
  });

  it("never takes sub-taus from a join", async () => {
    await send("join", ALICE, { subs: [{ name: "coach", about: "Coach." }] });
    expect((await aliceIn())?.subs).toEqual([]);
  });
});

describe("POST /api/leave", () => {
  beforeEach(async () => {
    mockTaus(ALICE, BOB);
    for (const tau of [ALICE, BOB]) await send("join", tau);
    await send("report", ALICE, { links: [{ peer: BOB.address, messages: 5 }] });
    await send("report", BOB, { links: [{ peer: ALICE.address, messages: 5 }] });
  });

  it("removes the tau and its own reported links; the link stops being mutual", async () => {
    const res = await send("leave", ALICE);
    expect(res.status).toBe(200);
    expect(await body(res)).toEqual({ ok: true });
    const snap = await snapshot();
    expect(snap.taus.map((t) => t.address)).toEqual([BOB.address]);
    expect(snap.links).toEqual([]);
    expect((await (await universe(`/api/taus/${BOB.address}`)).json()) as object).toMatchObject({
      links: [],
    });

    // A rejoin starts without links of its own; Bob's report still stands, so the link
    // is back as soon as Alice reports Bob again.
    await send("join", ALICE);
    expect((await snapshot()).links).toEqual([]);
    await send("report", ALICE, { links: [{ peer: BOB.address, messages: 5 }] });
    expect((await snapshot()).links).toEqual([{ a: ALICE.address, b: BOB.address, messages: 5 }]);
  });

  it("lets the other side drop the departed tau with its next report", async () => {
    await send("leave", ALICE);
    await send("report", BOB, { links: [{ peer: ALICE.address, messages: 5 }] });
    await send("join", ALICE);
    await send("report", ALICE, { links: [{ peer: BOB.address, messages: 5 }] });
    // Bob reported while Alice was away, so his claim about her was not kept.
    expect((await snapshot()).links).toEqual([]);
  });

  it("is 404 not_joined the second time", async () => {
    expect((await send("leave", ALICE)).status).toBe(200);
    const res = await send("leave", ALICE);
    expect(res.status).toBe(404);
    expect(await body(res)).toEqual({ error: "not_joined" });
  });

  it("still refuses a replay of the join after leaving", async () => {
    vi.restoreAllMocks();
    mockTaus(ALICE, BOB);
    const join = await signed("join", ALICE);
    expect((await post("/api/join", join)).status).toBe(200);
    expect((await send("leave", ALICE)).status).toBe(200);
    const replay = await post("/api/join", join);
    expect(replay.status).toBe(400);
    expect(await body(replay)).toEqual({ error: "stale" });
    expect((await snapshot()).taus.map((t) => t.address)).toEqual([BOB.address]);
  });
});

describe("GET /api/universe", () => {
  it("answers an empty universe", async () => {
    const res = await universe("/api/universe");
    expect(res.status).toBe(200);
    expect(res.headers.get("cache-control")).toBe("public, max-age=60");
    expect(res.headers.get("access-control-allow-origin")).toBe("*");
    expect(res.headers.get("content-type")).toMatch(/^application\/json/);
    expect(res.headers.get("x-content-type-options")).toBe("nosniff");
    const snap = (await res.json()) as Record<string, unknown>;
    expect(Object.keys(snap)).toEqual(["universe", "generated_at", "stats", "taus", "links"]);
    expect(snap).toMatchObject({
      universe: UNIVERSE,
      stats: { taus: 0, online: 0, messages: 0 },
      taus: [],
      links: [],
    });
    expect(Math.abs((snap.generated_at as number) - nowSeconds())).toBeLessThanOrEqual(2);
  });

  it("orders taus by joined_at", async () => {
    mockTaus(ALICE, BOB, CAROL);
    for (const tau of [CAROL, ALICE, BOB]) {
      await send("join", tau, { ts: nextTs(tau.address) + [CAROL, ALICE, BOB].indexOf(tau) });
    }
    expect((await snapshot()).taus.map((t) => t.address)).toEqual([
      CAROL.address,
      ALICE.address,
      BOB.address,
    ]);
  });

  it("marks a tau online for two hours after its last report", async () => {
    mockTaus(ALICE);
    vi.useFakeTimers({ toFake: ["Date"] });
    const start = 1_800_000_000;
    vi.setSystemTime(start * 1000);
    expect((await send("join", ALICE, { ts: start })).status).toBe(200);
    vi.setSystemTime((start + 7_200) * 1000);
    expect((await snapshot()).taus[0]?.online).toBe(true);
    expect((await snapshot()).stats.online).toBe(1);
    vi.setSystemTime((start + 7_201) * 1000);
    expect((await snapshot()).taus[0]?.online).toBe(false);
    expect((await snapshot()).stats).toEqual({ taus: 1, online: 0, messages: 0 });
  });

  it("names the UNIVERSE host when it is set", async () => {
    const { env } = await import("cloudflare:workers");
    const worker = (await import("../src/index")).default;
    const res = await worker.fetch(new Request("https://other.example/api/universe"), {
      ...env,
      UNIVERSE: "Tau.Example.com",
    });
    expect(((await res.json()) as { universe: string }).universe).toBe("tau.example.com");
  });

  it("answers CORS preflight and refuses writes", async () => {
    const preflight = await universe("/api/universe", { method: "OPTIONS" });
    expect(preflight.status).toBe(204);
    expect(preflight.headers.get("access-control-allow-origin")).toBe("*");
    const put = await universe("/api/universe", { method: "PUT" });
    expect(put.status).toBe(405);
    expect(put.headers.get("allow")).toBe("GET, HEAD, OPTIONS");
  });
});

describe("GET /api/taus/<address>", () => {
  beforeEach(async () => {
    mockTaus(ALICE, BOB, CAROL);
    for (const tau of [ALICE, BOB, CAROL]) await send("join", tau, { owner: "O" });
    await send("report", ALICE, {
      links: [
        { peer: BOB.address, messages: 8 },
        { peer: CAROL.address, messages: 2 },
      ],
    });
    await send("report", BOB, { links: [{ peer: ALICE.address, messages: 6 }] });
    await send("report", CAROL, { links: [{ peer: ALICE.address, messages: 3 }] });
  });

  it("answers one tau with its visible links", async () => {
    const res = await universe(`/api/taus/${ALICE.address}`);
    expect(res.status).toBe(200);
    expect(res.headers.get("access-control-allow-origin")).toBe("*");
    const tau = (await res.json()) as Record<string, unknown>;
    expect(tau).toMatchObject({
      address: ALICE.address,
      name: ALICE.name,
      owner: "O",
      about: "",
      online: true,
      links: [
        { peer: BOB.address, messages: 6 },
        { peer: CAROL.address, messages: 2 },
      ],
    });
    expect(Object.keys(tau)).toEqual([
      "address",
      "name",
      "owner",
      "about",
      "joined_at",
      "last_seen",
      "online",
      "handle",
      "subs",
      "links",
    ]);
  });

  it("shows only mutual links", async () => {
    await send("report", CAROL, { links: [] });
    const tau = (await (await universe(`/api/taus/${ALICE.address}`)).json()) as {
      links: unknown[];
    };
    expect(tau.links).toEqual([{ peer: BOB.address, messages: 6 }]);
  });

  it("is 404 not_found for an unknown or invalid address", async () => {
    for (const path of ["/api/taus/nobody.example", "/api/taus/Not_An_Address", "/api/taus/%E0"]) {
      const res = await universe(path);
      expect(res.status).toBe(404);
      expect(await res.json()).toEqual({ error: "not_found" });
    }
  });

  it("decodes a percent-encoded address with a port", async () => {
    const local = { ...ALICE, address: "127.0.0.1:8791" };
    vi.restoreAllMocks();
    mockCards({ "https://127.0.0.1:8791": card(local) });
    expect((await send("join", local)).status).toBe(200);
    const res = await universe("/api/taus/127.0.0.1%3A8791");
    expect(res.status).toBe(200);
    expect(((await res.json()) as { address: string }).address).toBe("127.0.0.1:8791");
  });
});

describe("other /api paths", () => {
  it("allows only POST on the signed endpoints", async () => {
    for (const kind of ["join", "report", "leave"]) {
      const res = await universe(`/api/${kind}`);
      expect(res.status).toBe(405);
      expect(res.headers.get("allow")).toBe("POST");
    }
  });

  it("is 404 for unknown API paths", async () => {
    const res = await universe("/api/nothing");
    expect(res.status).toBe(404);
    expect(await res.json()).toEqual({ error: "not_found" });
  });
});

describe("rate limit and replay guard", () => {
  it("accepts 30 requests per address per hour, then 429 until the hour has passed", async () => {
    mockTaus(ALICE, BOB);
    vi.useFakeTimers({ toFake: ["Date"] });
    const start = 1_800_000_000;
    vi.setSystemTime(start * 1000);
    expect((await send("join", ALICE, { ts: start })).status).toBe(200);
    for (let i = 1; i < 30; i++) {
      expect((await send("report", ALICE, { ts: start + i })).status).toBe(200);
    }
    const limited = await send("report", ALICE, { ts: start + 30 });
    expect(limited.status).toBe(429);
    expect(await limited.json()).toEqual({ error: "rate_limited" });
    // Per address: Bob is not affected.
    expect((await send("join", BOB, { ts: start })).status).toBe(200);

    vi.setSystemTime((start + 3_601) * 1000);
    expect((await send("report", ALICE, { ts: start + 3_601 })).status).toBe(200);
  });

  it("does not count refused requests", async () => {
    mockTaus(ALICE);
    for (let i = 0; i < 35; i++) {
      expect((await send("report", ALICE)).status).toBe(404);
    }
    expect((await send("join", ALICE)).status).toBe(200);
  });

  it("refuses a ts that is not newer than the last accepted one", async () => {
    mockTaus(ALICE);
    const ts = nowSeconds();
    expect((await send("join", ALICE, { ts })).status).toBe(200);
    for (const older of [ts, ts - 1]) {
      const res = await send("join", ALICE, { ts: older });
      expect(res.status).toBe(400);
      expect(await res.json()).toEqual({ error: "stale" });
    }
    expect((await send("join", ALICE, { ts: ts + 1 })).status).toBe(200);
  });

  it("refuses the same signed request twice", async () => {
    mockTaus(ALICE);
    const wire = await signed("join", ALICE);
    expect((await post("/api/join", wire)).status).toBe(200);
    const again = await post("/api/join", wire);
    expect(again.status).toBe(400);
    expect(await again.json()).toEqual({ error: "stale" });
  });
});

describe("POST checks, in the reference's order", () => {
  beforeEach(() => {
    mockTaus(ALICE, BOB);
  });

  it("413 too_large", async () => {
    const res = await post("/api/join", "x".repeat(65_537));
    expect(res.status).toBe(413);
    expect(await res.json()).toEqual({ error: "too_large" });
  });

  it("413 too_large wins over everything else", async () => {
    const big = await signed("report", ALICE, { links: [], padding: "A".repeat(66_000) });
    expect((await post("/api/leave", big)).status).toBe(413);
  });

  const badBodies: [string, () => Promise<unknown>][] = [
    ["not JSON", async () => "{nope"],
    ["not an object", async () => "[1,2]"],
    ["missing sig", async () => ({ payload: (await signed("join", ALICE)).payload })],
    ["sig not a string", async () => ({ payload: (await signed("join", ALICE)).payload, sig: 5 })],
    ["payload not b64u", async () => ({ payload: "a+b/", sig: (await signed("join", ALICE)).sig })],
    ["sig not b64u", async () => ({ payload: (await signed("join", ALICE)).payload, sig: "***" })],
    ["payload not JSON", async () => signRaw(new TextEncoder().encode("hello"), ALICE.seed)],
    ["payload an array", async () => signRaw(new TextEncoder().encode("[]"), ALICE.seed)],
    [
      "payload not UTF-8",
      async () => signRaw(new Uint8Array([0x7b, 0xff, 0xfe, 0x7d]), ALICE.seed),
    ],
    ["v not 1", async () => signed("join", ALICE, { v: 2 })],
    ["v a string", async () => signed("join", ALICE, { v: "1" })],
    ["unknown kind", async () => signed("join", ALICE, { kind: "spam" })],
    ["kind missing", async () => signed("join", ALICE, { kind: undefined })],
    ["universe missing", async () => signed("join", ALICE, { universe: undefined })],
    ["universe not a string", async () => signed("join", ALICE, { universe: 7 })],
    ["bad address", async () => signed("join", ALICE, { address: "Alice.Example" })],
    ["address missing", async () => signed("join", ALICE, { address: undefined })],
    ["ts not an integer", async () => signed("join", ALICE, { ts: 1.5 })],
    ["ts a string", async () => signed("join", ALICE, { ts: String(nowSeconds()) })],
    ["owner too long", async () => signed("join", ALICE, { owner: "x".repeat(61) })],
    ["owner not a string", async () => signed("join", ALICE, { owner: 1 })],
    ["about too long", async () => signed("join", ALICE, { about: "x".repeat(201) })],
    ["links missing", async () => signed("report", ALICE, { links: undefined })],
    ["links not a list", async () => signed("report", ALICE, { links: {} })],
    [
      "more than 500 links",
      async () =>
        signed("report", ALICE, {
          links: Array.from({ length: 501 }, (_, i) => ({ peer: `p${i}.example`, messages: 1 })),
        }),
    ],
    ["link not an object", async () => signed("report", ALICE, { links: ["bob.example"] })],
    [
      "link peer invalid",
      async () => signed("report", ALICE, { links: [{ peer: "Bob Example", messages: 1 }] }),
    ],
    [
      "link messages negative",
      async () => signed("report", ALICE, { links: [{ peer: BOB.address, messages: -1 }] }),
    ],
    [
      "link messages not an integer",
      async () => signed("report", ALICE, { links: [{ peer: BOB.address, messages: 1.5 }] }),
    ],
    ["subs not a list", async () => signed("report", ALICE, { subs: { coach: "x" } })],
    [
      "subs more than 20",
      async () =>
        signed("report", ALICE, {
          subs: Array.from({ length: 21 }, (_, i) => ({ name: `s${i}x`, about: "" })),
        }),
    ],
    ["sub not an object", async () => signed("report", ALICE, { subs: ["coach"] })],
    [
      "sub name missing",
      async () => signed("report", ALICE, { subs: [{ about: "Coach." }] }),
    ],
    ...["Coach", "1coach", "c", "c".repeat(32), "co ach", "/coach", "coach_1", "çoach"].map(
      (name): [string, () => Promise<unknown>] => [
        `sub name ${JSON.stringify(name)}`,
        async () => signed("report", ALICE, { subs: [{ name, about: "" }] }),
      ],
    ),
    [
      "sub about not a string",
      async () => signed("report", ALICE, { subs: [{ name: "coach", about: 7 }] }),
    ],
    [
      "sub about too long",
      async () => signed("report", ALICE, { subs: [{ name: "coach", about: "x".repeat(201) }] }),
    ],
  ];
  for (const [name, make] of badBodies) {
    it(`400 bad_request: ${name}`, async () => {
      const made = await make();
      // Report payloads (links, subs) go to /api/report, everything else to /api/join.
      const path =
        typeof made === "object" && made !== null && /link|sub/.test(name)
          ? "/api/report"
          : "/api/join";
      const res = await post(path, made);
      expect(res.status).toBe(400);
      const answer = (await res.json()) as { error: string; detail: string };
      expect(answer.error).toBe("bad_request");
      expect(typeof answer.detail).toBe("string");
    });
  }

  it("accepts exactly 500 links", async () => {
    await send("join", ALICE);
    const links = Array.from({ length: 500 }, (_, i) => ({ peer: `p${i}.example`, messages: i }));
    expect((await send("report", ALICE, { links })).status).toBe(200);
  });

  it("400 wrong_universe", async () => {
    const res = await send("join", ALICE, { universe: "tau.getporti.com" });
    expect(res.status).toBe(400);
    expect(await res.json()).toEqual({ error: "wrong_universe" });
  });

  it("400 wrong_universe comes before stale", async () => {
    const res = await send("join", ALICE, { universe: "other.example", ts: 1 });
    expect(await res.json()).toEqual({ error: "wrong_universe" });
  });

  it("400 stale, both ways of the 300 s window", async () => {
    // Read the clock right before each request; +302, because the Worker's clock may tick
    // once between here and its check.
    for (const offset of [-301, 302]) {
      const res = await send("join", ALICE, { ts: nowSeconds() + offset });
      expect(res.status).toBe(400);
      expect(await res.json()).toEqual({ error: "stale" });
    }
    expect((await send("join", ALICE, { ts: nowSeconds() - 290 })).status).toBe(200);
  });

  it("400 bad_request when the path does not match the kind, after the stale check", async () => {
    const wrongPath = await post("/api/report", await signed("join", ALICE));
    expect(wrongPath.status).toBe(400);
    expect(((await wrongPath.json()) as { error: string }).error).toBe("bad_request");

    const staleAndWrong = await post(
      "/api/report",
      await signed("join", ALICE, { ts: nowSeconds() - 1_000 }),
    );
    expect(await staleAndWrong.json()).toEqual({ error: "stale" });
  });

  it("400 bad_request for a wrong path comes before the card fetch", async () => {
    vi.restoreAllMocks();
    const spy = mockCards({});
    const res = await post("/api/leave", await signed("join", ALICE));
    expect(res.status).toBe(400);
    expect(spy).not.toHaveBeenCalled();
  });

  const unavailable: [string, () => ReturnType<typeof mockCards>][] = [
    ["network error", () => mockCards({})],
    ["404", () => mockCards({ [`https://${ALICE.address}`]: new Response("no", { status: 404 }) })],
    [
      "redirect",
      () =>
        mockCards({
          [`https://${ALICE.address}`]: new Response(null, {
            status: 302,
            headers: { location: "https://elsewhere.example/" },
          }),
        }),
    ],
    ["not JSON", () => mockCards({ [`https://${ALICE.address}`]: new Response("<html>") })],
    [
      "larger than 8 KiB",
      () =>
        mockCards({
          [`https://${ALICE.address}`]: card(ALICE, { padding: "x".repeat(9_000) }),
        }),
    ],
    [
      "another address",
      () => mockCards({ [`https://${ALICE.address}`]: card(ALICE, { address: "bob.example" }) }),
    ],
    ["v not 1", () => mockCards({ [`https://${ALICE.address}`]: card(ALICE, { v: 2 }) })],
    [
      "sign_key not 32 bytes",
      () => mockCards({ [`https://${ALICE.address}`]: card(ALICE, { sign_key: "AAAA" }) }),
    ],
    ["no name", () => mockCards({ [`https://${ALICE.address}`]: card(ALICE, { name: 5 }) })],
  ];
  for (const [name, mock] of unavailable) {
    it(`502 card_unavailable: ${name}`, async () => {
      vi.restoreAllMocks();
      mock();
      const res = await send("join", ALICE);
      expect(res.status).toBe(502);
      expect(await res.json()).toEqual({ error: "card_unavailable" });
    });
  }

  it("fetches the card over https with a 5 s timeout and no redirects", async () => {
    vi.restoreAllMocks();
    const spy = mockTaus(ALICE);
    expect((await send("join", ALICE)).status).toBe(200);
    expect(spy).toHaveBeenCalledTimes(1);
    const [url, init] = spy.mock.calls[0]!;
    expect(String(url)).toBe(`https://${ALICE.address}/.well-known/tau.json`);
    expect(init?.redirect).toBe("manual");
    expect(init?.signal).toBeInstanceOf(AbortSignal);
  });

  it("never uses http for a loopback tau while insecure peers are off", async () => {
    vi.restoreAllMocks();
    const local = { ...ALICE, address: "127.0.0.1:8791" };
    const spy = mockCards({ "http://127.0.0.1:8791": card(local) });
    const res = await send("join", local);
    expect(res.status).toBe(502);
    expect(String(spy.mock.calls[0]?.[0])).toBe("https://127.0.0.1:8791/.well-known/tau.json");
  });

  it("uses http for a loopback tau when ALLOW_INSECURE_PEERS=1, and still answers an https url", async () => {
    vi.restoreAllMocks();
    const { env } = await import("cloudflare:workers");
    const worker = (await import("../src/index")).default;
    const local = { ...ALICE, address: "127.0.0.1:8791" };
    const spy = mockCards({ "http://127.0.0.1:8791": card(local) });
    // A local universe on http://127.0.0.1:8790, as in `bun run dev`.
    const payload = payloadOf("join", local, { universe: "127.0.0.1:8790" });
    const wire = await signRaw(new TextEncoder().encode(JSON.stringify(payload)), local.seed);
    const res = await worker.fetch(
      new Request("http://127.0.0.1:8790/api/join", { method: "POST", body: JSON.stringify(wire) }),
      { ...env, ALLOW_INSECURE_PEERS: "1" },
    );
    expect(res.status).toBe(200);
    expect(String(spy.mock.calls[0]?.[0])).toBe("http://127.0.0.1:8791/.well-known/tau.json");
    expect(((await res.json()) as { url: string }).url).toBe(
      "https://127.0.0.1:8790/universe#127.0.0.1:8791",
    );
  });

  it("403 bad_signature: another key", async () => {
    const res = await post("/api/join", await signed("join", ALICE, {}, BOB.seed));
    expect(res.status).toBe(403);
    expect(await res.json()).toEqual({ error: "bad_signature" });
  });

  it("403 bad_signature: the tau-net/1 context of envelopes", async () => {
    const payload = new TextEncoder().encode(JSON.stringify(payloadOf("join", ALICE)));
    const res = await post("/api/join", await signRaw(payload, ALICE.seed, "tau-net/1\n"));
    expect(res.status).toBe(403);
  });

  it("403 bad_signature: tampered payload", async () => {
    const wire = await signed("join", ALICE, { owner: "Alice" });
    const tampered = JSON.stringify(payloadOf("join", ALICE, { owner: "Mallory" }));
    const res = await post("/api/join", {
      payload: b64uEncode(new TextEncoder().encode(tampered)),
      sig: wire.sig,
    });
    expect(res.status).toBe(403);
  });

  it("403 bad_signature: a signature of the wrong length", async () => {
    const wire = await signed("join", ALICE);
    const res = await post("/api/join", { payload: wire.payload, sig: "AAAA" });
    expect(res.status).toBe(403);
  });

  it("403 bad_signature comes before not_joined", async () => {
    const res = await post("/api/leave", await signed("leave", ALICE, {}, BOB.seed));
    expect(res.status).toBe(403);
  });

  it("404 not_joined comes before rate_limited", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    const start = 1_800_000_000;
    vi.setSystemTime(start * 1000);
    await send("join", ALICE, { ts: start });
    for (let i = 1; i < 29; i++) await send("report", ALICE, { ts: start + i });
    expect((await send("leave", ALICE, { ts: start + 29 })).status).toBe(200);
    // 30 accepted requests: Alice is at her limit and no longer joined.
    const report = await send("report", ALICE, { ts: start + 30 });
    expect(report.status).toBe(404);
    const join = await send("join", ALICE, { ts: start + 31 });
    expect(join.status).toBe(429);
  });

  it("stale comes before the card fetch", async () => {
    vi.restoreAllMocks();
    const spy = mockCards({});
    const res = await send("join", ALICE, { ts: 5 });
    expect(res.status).toBe(400);
    expect(spy).not.toHaveBeenCalled();
  });
});
