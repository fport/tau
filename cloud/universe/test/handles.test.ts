/**
 * ADR 0013 §6 on the universe: hosted taus, handle claims, slugs, and the person and
 * sub-tau APIs. tau-host is a fake behind the `HOST` binding (test/helpers.ts).
 */

import { reset } from "cloudflare:test";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import {
  ALICE,
  BOB,
  CAROL,
  directory,
  FakeHost,
  GITHUB_ALICE,
  GITHUB_BOB,
  mockCards,
  mockTaus,
  nextTs,
  nowSeconds,
  post,
  prepareTaus,
  resetClocks,
  send,
  sendClaim,
  sendVia,
  signed,
  snapshot,
  type Tau,
  UNIVERSE,
  universe,
} from "./helpers";

/** A tau hosted by the fake tau-host on the universe's own host. */
const DANA: Tau = { address: `${UNIVERSE}/@dana`, name: "Dana's tau", seed: "", signKey: "" };
/** A hosted tau whose handle is the same GitHub login as Alice's claim. */
const HOSTED_ALICE: Tau = {
  address: `${UNIVERSE}/@alice`,
  name: "Alice's hosted tau",
  seed: "",
  signKey: "",
};
const GITHUB_DANA = { handle: "dana", github_id: 1004, session: "s-dana" };

beforeAll(async () => {
  await prepareTaus();
  Object.assign(DANA, { seed: CAROL.seed, signKey: CAROL.signKey });
  Object.assign(HOSTED_ALICE, { seed: BOB.seed, signKey: BOB.signKey });
});
beforeEach(async () => {
  await reset();
  resetClocks();
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

async function tauOf(address: string) {
  return (await snapshot()).taus.find((tau) => tau.address === address);
}

async function handleOf(address: string): Promise<string | null | undefined> {
  return (await tauOf(address))?.handle;
}

function sub(name: string, about = "", extra: Record<string, unknown> = {}) {
  return { name, about, ...extra };
}

describe("hosted taus", () => {
  it("get the handle of their address, with the card fetched through HOST", async () => {
    const spy = mockCards({});
    const host = new FakeHost().hosts(DANA);
    expect((await sendVia(host, "join", DANA)).status).toBe(200);
    expect(await handleOf(DANA.address)).toBe("dana");
    expect(host.requests.map((request) => request.url)).toEqual([
      `https://${UNIVERSE}/@dana/.well-known/tau.json`,
    ]);
    expect(spy).not.toHaveBeenCalled();
    // Reports keep it.
    expect((await sendVia(host, "report", DANA)).status).toBe(200);
    expect(await handleOf(DANA.address)).toBe("dana");
  });

  it("cannot join a universe without tau-host behind it", async () => {
    mockCards({});
    const res = await send("join", DANA);
    expect(res.status).toBe(502);
    expect(await res.json()).toEqual({ error: "card_unavailable" });
  });

  it("fetch the card of a hosted address on another universe like any other", async () => {
    const elsewhere = { ...DANA, address: "tau.example.com/@dana" };
    const spy = mockCards({ "https://tau.example.com/@dana": { ...cardOf(elsewhere) } });
    expect((await send("join", elsewhere)).status).toBe(200);
    expect(String(spy.mock.calls[0]?.[0])).toBe(
      "https://tau.example.com/@dana/.well-known/tau.json",
    );
    // Only the universe's own host hands out handles by address.
    expect(await handleOf(elsewhere.address)).toBeNull();
  });

  it("take their handle from a tau that claimed it, which cannot claim it back", async () => {
    mockTaus(ALICE);
    const host = new FakeHost(GITHUB_ALICE).hosts(HOSTED_ALICE);
    await send("join", ALICE);
    expect((await sendClaim(host, ALICE, { account: GITHUB_ALICE })).status).toBe(200);
    expect(await handleOf(ALICE.address)).toBe("alice");

    expect((await sendVia(host, "join", HOSTED_ALICE)).status).toBe(200);
    expect(await handleOf(HOSTED_ALICE.address)).toBe("alice");
    expect(await handleOf(ALICE.address)).toBeNull();

    const again = await sendClaim(host, ALICE, { account: GITHUB_ALICE });
    expect(again.status).toBe(409);
    expect(await again.json()).toEqual({ error: "handle_taken" });
  });
});

function cardOf(tau: Tau): Record<string, unknown> {
  return {
    v: 1,
    address: tau.address,
    name: tau.name,
    sign_key: tau.signKey,
    box_key: "NYBy1jZYgNGu6jKa35EhODhR7SGijjt16WXQ0s0WYlQ",
    inbox: `https://${tau.address}/net/inbox`,
    software: "tau-host/0.1.0",
  };
}

describe("POST /api/claim", () => {
  let host: FakeHost;
  beforeEach(async () => {
    mockTaus(ALICE, BOB, CAROL);
    host = new FakeHost(GITHUB_ALICE, GITHUB_BOB, GITHUB_DANA).hosts(DANA);
    for (const tau of [ALICE, BOB]) expect((await send("join", tau)).status).toBe(200);
  });

  it("binds the signed-in GitHub login to the tau", async () => {
    const res = await sendClaim(host, ALICE, { account: GITHUB_ALICE });
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({
      ok: true,
      handle: "alice",
      url: `https://${UNIVERSE}/@alice`,
      moved_from: null,
    });
    expect(await handleOf(ALICE.address)).toBe("alice");
    const tau = (await (await universe(`/api/taus/${ALICE.address}`)).json()) as {
      handle: string;
    };
    expect(tau.handle).toBe("alice");
    // tau-host was asked with the page's cookies, on the universe's own origin.
    const [whoami] = host.requests;
    expect(whoami?.url).toBe(`https://${UNIVERSE}/api/host/whoami`);
    expect(whoami?.method).toBe("GET");
    expect(whoami?.headers.get("cookie")).toBe("lang=en; tau_session=s-alice");
  });

  it("is 501 claims_unavailable without tau-host, before anything else", async () => {
    const res = await sendClaim(null, ALICE, { account: GITHUB_ALICE, origin: null });
    expect(res.status).toBe(501);
    expect(await res.json()).toEqual({ error: "claims_unavailable" });
  });

  it("is 403 bad_origin unless it comes from the universe's own pages", async () => {
    for (const origin of [null, "https://evil.example", `http://${UNIVERSE}`]) {
      const res = await sendClaim(host, ALICE, { account: GITHUB_ALICE, origin });
      expect(res.status, String(origin)).toBe(403);
      expect(await res.json()).toEqual({ error: "bad_origin" });
    }
    expect(host.requests).toEqual([]);
  });

  it("is 401 not_signed_in without a tau-host session, and keeps the claim usable", async () => {
    const wire = await signed("claim", ALICE);
    for (const account of [null, { ...GITHUB_ALICE, session: "unknown" }]) {
      const res = await sendClaim(host, ALICE, { account, wire });
      expect(res.status).toBe(401);
      expect(await res.json()).toEqual({ error: "not_signed_in" });
    }
    expect((await sendClaim(host, ALICE, { account: GITHUB_ALICE, wire })).status).toBe(200);
  });

  it("uses a nonce once", async () => {
    const wire = await signed("claim", ALICE);
    expect((await sendClaim(host, ALICE, { account: GITHUB_ALICE, wire })).status).toBe(200);
    const replay = await sendClaim(host, ALICE, { account: GITHUB_ALICE, wire });
    expect(replay.status).toBe(400);
    expect(await replay.json()).toEqual({ error: "stale" });
  });

  it("is valid for an hour, even when the tau reported after signing it", async () => {
    const now = nowSeconds();
    expect((await send("report", ALICE, { ts: nextTs(ALICE.address) })).status).toBe(200);
    const hourOld = await sendClaim(host, ALICE, {
      account: GITHUB_ALICE,
      overrides: { ts: now - 3_500 },
    });
    expect(hourOld.status).toBe(200);
    for (const ts of [now - 3_700, now + 3_700]) {
      const res = await sendClaim(host, BOB, { account: GITHUB_BOB, overrides: { ts } });
      expect(res.status).toBe(400);
      expect(await res.json()).toEqual({ error: "stale" });
    }
    // A claim does not move the tau's clock: its next report is fine.
    expect((await send("report", ALICE, { ts: nextTs(ALICE.address) })).status).toBe(200);
  });

  it("moves the handle to another tau of the same GitHub account", async () => {
    await sendClaim(host, ALICE, { account: GITHUB_ALICE });
    const res = await sendClaim(host, BOB, { account: GITHUB_ALICE });
    expect(res.status).toBe(200);
    expect(await res.json()).toMatchObject({ handle: "alice", moved_from: ALICE.address });
    expect(await handleOf(BOB.address)).toBe("alice");
    expect(await handleOf(ALICE.address)).toBeNull();
  });

  it("refuses a handle held under another GitHub id", async () => {
    await sendClaim(host, ALICE, { account: GITHUB_ALICE });
    // Someone who got the login "alice" after a rename has another id.
    host.sessions.set("s-new-alice", { handle: "alice", github_id: 9999, session: "s-new-alice" });
    for (const tau of [BOB, ALICE]) {
      const res = await sendClaim(host, tau, {
        account: { handle: "alice", github_id: 9999, session: "s-new-alice" },
      });
      expect(res.status).toBe(409);
      expect(await res.json()).toEqual({ error: "handle_taken" });
    }
    expect(await handleOf(ALICE.address)).toBe("alice");
    expect(await handleOf(BOB.address)).toBeNull();
  });

  it("gives a tau one handle: a new claim replaces its old one", async () => {
    await sendClaim(host, ALICE, { account: GITHUB_ALICE });
    expect((await sendClaim(host, ALICE, { account: GITHUB_BOB })).status).toBe(200);
    expect(await handleOf(ALICE.address)).toBe("bob");
    expect((await universe("/api/people/alice")).status).toBe(404);
  });

  it("lets a hosted tau claim only its own handle", async () => {
    expect((await sendVia(host, "join", DANA)).status).toBe(200);
    const other = await sendClaim(host, DANA, { account: GITHUB_ALICE });
    expect(other.status).toBe(409);
    expect(await other.json()).toEqual({ error: "handle_mismatch" });
    expect((await sendClaim(host, DANA, { account: GITHUB_DANA })).status).toBe(200);
    expect(await handleOf(DANA.address)).toBe("dana");
  });

  it("is 404 not_joined for a tau that has not joined", async () => {
    const res = await sendClaim(host, CAROL, { account: GITHUB_ALICE });
    expect(res.status).toBe(404);
    expect(await res.json()).toEqual({ error: "not_joined" });
  });

  it("checks the claim like any signed request", async () => {
    const claim = (options: Parameters<typeof sendClaim>[2]) =>
      sendClaim(host, ALICE, { account: GITHUB_ALICE, ...options });
    const cases: [string, () => Promise<Response>, number, string][] = [
      [
        "another key",
        async () => claim({ wire: await signed("claim", ALICE, {}, BOB.seed) }),
        403,
        "bad_signature",
      ],
      ["no nonce", () => claim({ overrides: { nonce: undefined } }), 400, "bad_request"],
      ["a short nonce", () => claim({ overrides: { nonce: "abc" } }), 400, "bad_request"],
      [
        "another universe",
        () => claim({ overrides: { universe: "tau.example" } }),
        400,
        "wrong_universe",
      ],
      [
        "a join at the claim path",
        async () => claim({ wire: await signed("join", ALICE) }),
        400,
        "bad_request",
      ],
    ];
    for (const [name, make, status, code] of cases) {
      const res = await make();
      expect(res.status, name).toBe(status);
      expect(((await res.json()) as { error: string }).error, name).toBe(code);
    }
    // A claim at the join path is refused too, and a GET is not a claim.
    const atJoin = await post("/api/join", await signed("claim", ALICE));
    expect(atJoin.status).toBe(400);
    expect((await universe("/api/claim")).status).toBe(405);
    expect(await handleOf(ALICE.address)).toBeNull();
  });

  it("is 502 host_unavailable when tau-host answers something else", async () => {
    const answers = [
      () => new Response("down", { status: 500 }),
      () => Response.json({ handle: "Not A Login", github_id: 1 }),
      () => Response.json({ handle: "alice", github_id: -1 }),
      () => Response.json({ handle: "alice" }),
      () => new Response("not json"),
    ];
    for (const answer of answers) {
      host.whoami = answer;
      const res = await sendClaim(host, ALICE, { account: GITHUB_ALICE });
      expect(res.status).toBe(502);
      expect(await res.json()).toEqual({ error: "host_unavailable" });
    }
    host.whoami = () => Response.json({ handle: "Alice", github_id: "1001" });
    const res = await sendClaim(host, ALICE, { account: GITHUB_ALICE });
    expect(await res.json()).toMatchObject({ ok: true, handle: "alice" });
  });
});

describe("slugs", () => {
  beforeEach(async () => {
    mockTaus(ALICE, BOB, CAROL);
    for (const tau of [ALICE, BOB]) expect((await send("join", tau)).status).toBe(200);
  });

  const slugOf = async (address: string, name: string) =>
    (await tauOf(address))?.subs.find((candidate) => candidate.name === name)?.slug;

  it("go to the first tau that reports a public sub-tau with the name", async () => {
    await send("report", ALICE, { subs: [sub("coach")] });
    await send("report", BOB, { subs: [sub("coach"), sub("landing")] });
    expect(await slugOf(ALICE.address, "coach")).toBe("coach");
    expect(await slugOf(BOB.address, "coach")).toBeNull();
    expect(await slugOf(BOB.address, "landing")).toBe("landing");
  });

  it("are never a name of the site", async () => {
    const names = ["universe", "how-it-works", "tr", "docs", "person", "brand", "claim", "app"];
    await send("report", ALICE, { subs: names.map((name) => sub(name)) });
    const subs = (await tauOf(ALICE.address))?.subs ?? [];
    // claim and app are reserved sub-tau names (ADR 0013 §3): dropped from the report.
    expect(subs.map((candidate) => [candidate.name, candidate.slug])).toEqual([
      ["brand", null],
      ["docs", null],
      ["how-it-works", null],
      ["person", null],
      ["tr", null],
      ["universe", null],
    ]);
  });

  it("stay with their tau while it is listed, even when it stops listing the sub-tau", async () => {
    await send("report", ALICE, { subs: [sub("coach")] });
    await send("report", ALICE, { subs: [] });
    expect((await universe("/api/subs/coach")).status).toBe(404);
    await send("report", BOB, { subs: [sub("coach")] });
    expect(await slugOf(BOB.address, "coach")).toBeNull();
    await send("report", ALICE, { subs: [sub("coach")] });
    expect(await slugOf(ALICE.address, "coach")).toBe("coach");
  });

  it("are released when the tau leaves", async () => {
    await send("report", ALICE, { subs: [sub("coach")] });
    await send("report", BOB, { subs: [sub("coach")] });
    expect((await send("leave", ALICE)).status).toBe(200);
    expect(await slugOf(BOB.address, "coach")).toBeNull();
    await send("report", BOB, { subs: [sub("coach")] });
    expect(await slugOf(BOB.address, "coach")).toBe("coach");
  });

  it("are released when the tau expires", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    const start = nowSeconds() + 10;
    vi.setSystemTime(start * 1000);
    await send("report", ALICE, { ts: start, subs: [sub("coach")] });
    const later = start + 31 * 86_400;
    vi.setSystemTime(later * 1000);
    await send("report", BOB, { ts: later, subs: [sub("coach")] });
    expect(await directory().prune(later)).toMatchObject({ taus: 1 });
    await send("report", BOB, { ts: later + 1, subs: [sub("coach")] });
    expect(await slugOf(BOB.address, "coach")).toBe("coach");
  });
});

describe("web sub-taus in reports", () => {
  beforeEach(async () => {
    mockTaus(ALICE);
    expect((await send("join", ALICE)).status).toBe(200);
  });

  it("store web and starters, sanitised; missing ones are false and none", async () => {
    const res = await send("report", ALICE, {
      subs: [
        sub("coach", "Runs.", { web: true, starters: ["Plan my week", " Why\nrest? ", "\u0007"] }),
        sub("landing", "Copy."),
      ],
    });
    expect(res.status).toBe(200);
    const subs = (await tauOf(ALICE.address))?.subs ?? [];
    expect(subs.map(({ name, web, starters }) => ({ name, web, starters }))).toEqual([
      { name: "coach", web: true, starters: ["Plan my week", "Why rest?"] },
      { name: "landing", web: false, starters: [] },
    ]);
  });

  it("keep first_seen across reports, and start it again after a sub-tau was absent", async () => {
    const first = nextTs(ALICE.address);
    await send("report", ALICE, { ts: first, subs: [sub("coach")] });
    const second = nextTs(ALICE.address);
    await send("report", ALICE, { ts: second, subs: [sub("coach", "New about."), sub("arm")] });
    let subs = (await tauOf(ALICE.address))?.subs ?? [];
    expect(subs.map(({ name, first_seen }) => [name, first_seen])).toEqual([
      ["arm", second],
      ["coach", first],
    ]);
    await send("report", ALICE, { subs: [] });
    const back = nextTs(ALICE.address);
    await send("report", ALICE, { ts: back, subs: [sub("coach")] });
    subs = (await tauOf(ALICE.address))?.subs ?? [];
    expect(subs.map(({ name, first_seen }) => [name, first_seen])).toEqual([["coach", back]]);
  });

  it("refuse malformed web flags and starters", async () => {
    const bads = [{ web: "yes" }, { starters: ["a", "b", "c", "d", "e"] }, { starters: [""] }];
    for (const bad of bads) {
      const res = await send("report", ALICE, { subs: [sub("coach", "", bad)] });
      expect(res.status, JSON.stringify(bad)).toBe(400);
    }
  });
});

describe("person and sub-tau APIs", () => {
  let joined: number;
  let reported: number;
  beforeEach(async () => {
    mockTaus(ALICE, BOB, CAROL);
    const host = new FakeHost(GITHUB_ALICE, GITHUB_BOB);
    joined = nextTs(ALICE.address);
    await send("join", ALICE, { ts: joined, owner: "Alice", about: "Tinkers with robots." });
    await send("join", BOB, { owner: "Bob" });
    await send("join", CAROL);
    reported = nextTs(ALICE.address);
    await send("report", ALICE, {
      ts: reported,
      links: [
        { peer: BOB.address, messages: 12 },
        { peer: CAROL.address, messages: 3 },
      ],
      subs: [
        sub("coach", "A patient running coach.", { web: true, starters: ["Plan my week"] }),
        sub("landing", "Writes landing-page copy."),
      ],
    });
    await send("report", BOB, {
      links: [{ peer: ALICE.address, messages: 10 }],
      subs: [sub("coach", "Bob's coach.")],
    });
    await send("report", CAROL, { links: [{ peer: ALICE.address, messages: 5 }] });
    await sendClaim(host, ALICE, { account: GITHUB_ALICE });
    await sendClaim(host, BOB, { account: GITHUB_BOB });
  });

  it("answer a person page", async () => {
    const res = await universe("/api/people/alice");
    expect(res.status).toBe(200);
    expect(res.headers.get("access-control-allow-origin")).toBe("*");
    expect(res.headers.get("cache-control")).toBe("public, max-age=30");
    const alice = (await res.json()) as { last_seen: number };
    expect(alice).toEqual({
      handle: "alice",
      github: "https://github.com/alice",
      building_since: joined,
      counts: { subs: 2, links: 2, messages: 13 },
      address: ALICE.address,
      name: ALICE.name,
      owner: "Alice",
      about: "Tinkers with robots.",
      joined_at: joined,
      last_seen: reported,
      online: true,
      hosted: false,
      subs: [
        {
          name: "coach",
          about: "A patient running coach.",
          web: true,
          starters: ["Plan my week"],
          first_seen: reported,
          slug: "coach",
          path: "/coach",
          url: `https://${UNIVERSE}/coach`,
        },
        {
          name: "landing",
          about: "Writes landing-page copy.",
          web: false,
          starters: [],
          first_seen: reported,
          slug: "landing",
          path: "/landing",
          url: `https://${UNIVERSE}/landing`,
        },
      ],
      links: [
        { peer: BOB.address, messages: 10, name: BOB.name, handle: "bob", online: true },
        { peer: CAROL.address, messages: 3, name: CAROL.name, handle: null, online: true },
      ],
    });
    // Handles are GitHub logins: any case finds them.
    expect((await universe("/api/people/Alice")).status).toBe(200);
  });

  it("answer a sub-tau page by slug and by handle", async () => {
    const res = await universe("/api/subs/coach");
    expect(res.status).toBe(200);
    expect(res.headers.get("access-control-allow-origin")).toBe("*");
    expect(res.headers.get("cache-control")).toBe("public, max-age=30");
    const coach = {
      name: "coach",
      about: "A patient running coach.",
      web: true,
      starters: ["Plan my week"],
      first_seen: reported,
      slug: "coach",
      path: "/coach",
      url: `https://${UNIVERSE}/coach`,
      online: true,
      hosted: false,
      owner: { handle: "alice", name: ALICE.name, address: ALICE.address },
    };
    expect(await res.json()).toEqual(coach);
    expect(await (await universe("/api/subs/@alice/coach")).json()).toEqual(coach);
    expect(await (await universe("/api/subs/@Bob/coach")).json()).toMatchObject({
      name: "coach",
      about: "Bob's coach.",
      slug: null,
      path: "/@bob/coach",
      url: `https://${UNIVERSE}/@bob/coach`,
      owner: { handle: "bob", name: BOB.name, address: BOB.address },
    });
  });

  it("are 404 not_found for what is not there", async () => {
    for (const path of [
      "/api/people/nobody",
      "/api/people/not_a_login",
      "/api/people/",
      "/api/subs/nope",
      "/api/subs/Coach",
      "/api/subs/@alice/nope",
      "/api/subs/@nobody/coach",
      "/api/subs/@alice/coach/extra",
      "/api/subs/",
    ]) {
      const res = await universe(path);
      expect(res.status, path).toBe(404);
      expect(res.headers.get("access-control-allow-origin"), path).toBe("*");
      expect(await res.json(), path).toEqual({ error: "not_found" });
    }
    // Carol has no handle: no person page, and her sub-tau-less tau has no pages at all.
    expect((await universe("/api/people/carol")).status).toBe(404);
  });

  it("answer CORS preflight and refuse writes", async () => {
    for (const path of ["/api/people/alice", "/api/subs/coach"]) {
      expect((await universe(path, { method: "OPTIONS" })).status).toBe(204);
      const res = await universe(path, { method: "POST" });
      expect(res.status).toBe(405);
      expect(res.headers.get("allow")).toBe("GET, HEAD, OPTIONS");
    }
  });

  it("drop a person with their tau", async () => {
    await send("leave", ALICE);
    expect((await universe("/api/people/alice")).status).toBe(404);
    expect((await universe("/api/subs/coach")).status).toBe(404);
    expect(await directory().pageExists({ handle: "bob" })).toBe(true);
  });

  it("put the handle into the snapshot", async () => {
    const snap = await snapshot();
    expect(snap.taus.map((tau) => [tau.address, tau.handle])).toEqual([
      [ALICE.address, "alice"],
      [BOB.address, "bob"],
      [CAROL.address, null],
    ]);
  });
});
