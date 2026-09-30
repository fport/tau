/** Universe requests: all four kinds, the ADR 0013 sub-tau fields, windows and claim links. */

import { describe, expect, it } from "vitest";

import {
  b64uEncode,
  checkRequestPayload,
  CLAIM_WINDOW_SECONDS,
  claimFragment,
  claimLink,
  compactJson,
  encodeRequest,
  ID_PATTERN,
  Identity,
  isFresh,
  makeRequestPayload,
  MalformedRequest,
  parseClaimFragment,
  parseRequest,
  REQUEST_WINDOW_SECONDS,
  requestWindowSeconds,
  signPayload,
  signRequest,
  verifyRequest,
  type ClaimPayload,
} from "../index.ts";

const common = {
  universe: "universe.example.com",
  address: "own.example.com/@alice",
  ts: 1_790_000_000,
};

describe("payloads", () => {
  it("makes a claim with a fresh nonce, for either address form", () => {
    const claim = makeRequestPayload("claim", common) as ClaimPayload;
    expect(Object.keys(claim)).toEqual(["v", "kind", "universe", "address", "ts", "nonce"]);
    expect(claim.nonce).toMatch(ID_PATTERN);
    expect(makeRequestPayload("claim", { ...common, address: "bob.example.com" }).address).toBe(
      "bob.example.com",
    );
  });

  it("sends subs only when there are some, and web and starters only when set", () => {
    expect(makeRequestPayload("report", { ...common, links: [], subs: [] })).toEqual({
      v: 1,
      kind: "report",
      ...common,
      links: [],
    });
    const report = makeRequestPayload("report", {
      ...common,
      links: [{ peer: "bob.example.com", messages: 2 }],
      subs: [
        { name: "coach", about: "", web: true, starters: ["Plan my 5k"] },
        { name: "study-buddy", about: "Helps with exams." },
      ],
    });
    expect(report).toMatchObject({
      subs: [
        { name: "coach", about: "", web: true, starters: ["Plan my 5k"] },
        { name: "study-buddy", about: "Helps with exams." },
      ],
    });
  });

  it("reads a missing owner, about or sub about as empty, as a universe does", () => {
    expect(checkRequestPayload({ v: 1, kind: "join", ...common })).toMatchObject({
      owner: "",
      about: "",
    });
    const report = checkRequestPayload({
      v: 1,
      kind: "report",
      ...common,
      links: [],
      subs: [{ name: "coach" }],
    });
    expect(report).toMatchObject({ subs: [{ name: "coach", about: "" }] });
    expect(
      checkRequestPayload({ v: 1, kind: "report", ...common, links: [], subs: null }),
    ).not.toHaveProperty("subs");
  });

  it("counts limits in code points", () => {
    expect(() => makeRequestPayload("join", { ...common, owner: "🌟".repeat(60) })).not.toThrow();
    expect(() => makeRequestPayload("join", { ...common, owner: "🌟".repeat(61) })).toThrow(
      MalformedRequest,
    );
  });

  const report = { v: 1, kind: "report", ...common, links: [] };
  it.each([
    [{ v: 2, kind: "leave", ...common }],
    [{ v: 1, kind: "shout", ...common }],
    [{ v: 1, kind: "leave", ...common, universe: "" }],
    [{ v: 1, kind: "leave", ...common, address: "own.example.com/@Alice" }],
    [{ v: 1, kind: "leave", ...common, ts: 1.5 }],
    [{ v: 1, kind: "join", ...common, about: "x".repeat(201) }],
    [{ ...report, links: null }],
    [
      {
        ...report,
        links: Array.from({ length: 501 }, () => ({ peer: "a.example.com", messages: 0 })),
      },
    ],
    [{ ...report, links: [{ peer: "a.example.com", messages: -1 }] }],
    [{ ...report, links: [{ peer: "not an address", messages: 1 }] }],
    [{ ...report, subs: Array.from({ length: 21 }, (_, i) => ({ name: `sub${i}`, about: "" })) }],
    [{ ...report, subs: [{ name: "X", about: "" }] }],
    [{ ...report, subs: [{ name: "coach", about: "", web: "yes" }] }],
    [{ ...report, subs: [{ name: "coach", about: "", starters: ["a", "b", "c", "d", "e"] }] }],
    [{ ...report, subs: [{ name: "coach", about: "", starters: [""] }] }],
    [{ ...report, subs: [{ name: "coach", about: "", starters: ["x".repeat(81)] }] }],
    [{ v: 1, kind: "claim", ...common }],
    [{ v: 1, kind: "claim", ...common, nonce: "short" }],
  ])("refuses %j", (payload) => {
    expect(() => checkRequestPayload(payload)).toThrow(MalformedRequest);
  });
});

describe("signed requests", () => {
  it("signs, parses and verifies, in the universe domain only", async () => {
    const tau = await Identity.generate();
    const request = await signRequest(tau, makeRequestPayload("claim", common));
    for (const body of [encodeRequest(request), request]) {
      const parsed = parseRequest(body);
      expect(parsed.payload.kind).toBe("claim");
      expect(await verifyRequest(tau.signKey, parsed.payloadBytes, parsed.sig)).toBe(true);
      expect(
        await verifyRequest((await Identity.generate()).signKey, parsed.payloadBytes, parsed.sig),
      ).toBe(false);
      const envelopeSig = await signPayload(tau, parsed.payloadBytes);
      expect(await verifyRequest(tau.signKey, parsed.payloadBytes, envelopeSig)).toBe(false);
    }
  });

  it("refuses malformed bodies", () => {
    const huge = b64uEncode(compactJson({ pad: "x".repeat(70_000) }));
    for (const body of [
      new TextEncoder().encode("nope"),
      [],
      { payload: 1, sig: "" },
      { payload: "a b", sig: "" },
      { payload: huge, sig: "" },
      { payload: b64uEncode(new TextEncoder().encode("[]")), sig: "" },
    ]) {
      expect(() => parseRequest(body)).toThrow(MalformedRequest);
    }
  });

  it("gives a claim an hour and every other kind five minutes", () => {
    expect(requestWindowSeconds("claim")).toBe(CLAIM_WINDOW_SECONDS);
    expect(requestWindowSeconds("join")).toBe(REQUEST_WINDOW_SECONDS);
    expect(isFresh({ kind: "claim", ts: 1000 }, 1000 + 3600)).toBe(true);
    expect(isFresh({ kind: "claim", ts: 1000 }, 1000 + 3601)).toBe(false);
    expect(isFresh({ kind: "report", ts: 1000 }, 1000 - 300)).toBe(true);
    expect(isFresh({ kind: "report", ts: 1000 }, 1000 + 301)).toBe(false);
  });
});

describe("claim links", () => {
  it("carries the signed request in the fragment", async () => {
    const request = await signRequest(
      await Identity.generate(),
      makeRequestPayload("claim", common),
    );
    const link = claimLink("universe.example.com", request);
    expect(link).toBe(`https://universe.example.com/claim#${claimFragment(request)}`);
    expect(parseClaimFragment(claimFragment(request))).toEqual(request);
    expect(parseClaimFragment(`#${claimFragment(request)}`)).toEqual(request);
    expect(
      claimLink("localhost:8788", request, true).startsWith("http://localhost:8788/claim#"),
    ).toBe(true);
  });

  it("refuses fragments that are not a wire body", () => {
    for (const fragment of [
      "",
      "#",
      "%%%",
      b64uEncode(compactJson({ payload: 1 })),
      b64uEncode(compactJson([])),
    ]) {
      expect(parseClaimFragment(fragment)).toBeNull();
    }
  });
});
