/** The universe page's data helpers (client/layout.ts): pure, no DOM. */

import { describe, expect, it } from "vitest";
import { matches, parseTarget } from "../client/layout";
import type { PublicTau } from "../src/snapshot";

function tau(address: string, subs: string[] = [], owner = ""): PublicTau {
  return {
    address,
    name: `${address} tau`,
    owner,
    about: "",
    joined_at: 1,
    last_seen: 1,
    online: true,
    handle: null,
    subs: subs.map((name) => ({
      name,
      about: `About ${name}.`,
      web: false,
      starters: [],
      first_seen: 1,
      slug: null,
    })),
  };
}

describe("page helpers", () => {
  it("find a tau or one of its sub-taus from the URL's #", () => {
    const snapshot = {
      taus: [tau("alice.example", ["coach"]), tau("127.0.0.1:8862", ["coach"])],
    };
    expect(parseTarget(snapshot, "alice.example")).toEqual({ address: "alice.example", sub: null });
    expect(parseTarget(snapshot, "alice.example/coach")).toEqual({
      address: "alice.example",
      sub: "coach",
    });
    expect(parseTarget(snapshot, "127.0.0.1:8862/coach")).toEqual({
      address: "127.0.0.1:8862",
      sub: "coach",
    });
    const misses = ["", "alice.example/landing", "bob.example", "bob.example/coach", "/coach"];
    for (const hash of misses) {
      expect(parseTarget(snapshot, hash), hash).toBeNull();
    }
  });

  it("match a search on name, owner, address and sub-tau names", () => {
    const alice = tau("alice.example", ["coach"], "Alice");
    for (const query of ["", "alice", "example", "coach", "/coach", "/co"]) {
      expect(matches(alice, query), query).toBe(true);
    }
    expect(matches(alice, "landing")).toBe(false);
    expect(matches(tau("bob.example"), "coach")).toBe(false);
  });
});
