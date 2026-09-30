/** Cards: the shape a tau serves, the checks a receiver makes and a fetch within the limits. */

import { describe, expect, it } from "vitest";

import { fetchCard, Identity, makeCard, MAX_CARD_BYTES, parseCard } from "../index.ts";

const ADDRESS = "tau.example.com/@alice";

async function card() {
  const id = await Identity.generate();
  return makeCard({
    address: ADDRESS,
    name: "Alice's tau",
    signKey: id.signKey,
    boxKey: id.boxKey,
    software: "tau-host/0.1.0",
  });
}

function fakeFetch(response: () => Response, seen: string[] = []): typeof fetch {
  return (async (input: RequestInfo | URL) => {
    seen.push(String(input));
    return response();
  }) as typeof fetch;
}

describe("cards", () => {
  it("serves the inbox under the whole address", async () => {
    const c = await card();
    expect(c).toMatchObject({ v: 1, address: ADDRESS, inbox: `https://${ADDRESS}/net/inbox` });
    expect(parseCard(c, ADDRESS)).toEqual(c);
  });

  it("refuses cards a receiver cannot use", async () => {
    const c = await card();
    expect(parseCard(c, "tau.example.com/@bob")).toBeNull();
    expect(parseCard({ ...c, v: true }, ADDRESS)).toBeNull();
    expect(parseCard({ ...c, sign_key: "short" }, ADDRESS)).toBeNull();
    expect(parseCard({ ...c, box_key: undefined }, ADDRESS)).toBeNull();
    expect(parseCard([c], ADDRESS)).toBeNull();
  });

  it("cuts the name to 80 characters and fills what is missing", async () => {
    const c = await card();
    const parsed = parseCard(
      { ...c, name: "🌟".repeat(90), inbox: undefined, software: 7 },
      ADDRESS,
    );
    expect(parsed?.name).toBe("🌟".repeat(80));
    expect(parsed?.inbox).toBe("");
    expect(parsed?.software).toBe("");
    expect(parseCard({ ...c, name: null }, ADDRESS)?.name).toBe("");
  });
});

describe("fetching a card", () => {
  it("fetches the card URL of the address", async () => {
    const c = await card();
    const seen: string[] = [];
    const fetched = await fetchCard(ADDRESS, { fetcher: fakeFetch(() => Response.json(c), seen) });
    expect(fetched).toEqual(c);
    expect(seen).toEqual([`https://${ADDRESS}/.well-known/tau.json`]);
    await fetchCard("localhost:8787/@alice", {
      allowInsecure: true,
      fetcher: fakeFetch(() => Response.json(c), seen),
    });
    expect(seen[1]).toBe("http://localhost:8787/@alice/.well-known/tau.json");
  });

  it("gives null for every failure", async () => {
    const c = await card();
    const failures: (() => Response)[] = [
      () => new Response("nope", { status: 404 }),
      () =>
        new Response(null, { status: 302, headers: { location: "https://elsewhere.example.com" } }),
      () => new Response("x".repeat(MAX_CARD_BYTES + 1)),
      () => new Response("{}", { headers: { "content-length": String(MAX_CARD_BYTES + 1) } }),
      () => new Response("not json"),
      () => Response.json({ ...c, address: "tau.example.com/@bob" }),
      () => {
        throw new TypeError("network down");
      },
    ];
    for (const response of failures) {
      expect(await fetchCard(ADDRESS, { fetcher: fakeFetch(response) })).toBeNull();
    }
    expect(
      await fetchCard("not an address", { fetcher: fakeFetch(() => Response.json(c)) }),
    ).toBeNull();
  });
});
