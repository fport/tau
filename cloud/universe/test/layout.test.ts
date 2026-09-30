/** The universe page's layout data (client/layout.ts): pure, no DOM. */

import { describe, expect, it } from "vitest";
import {
  groupKey,
  hash01,
  matches,
  MIN_ORBIT,
  NODE_RADIUS,
  nameOffset,
  orbitRadius,
  parseTarget,
  reach,
  SUB_RADIUS,
  subAngle,
  subNodes,
  tauSubNodes,
} from "../client/layout";
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
    subs: subs.map((name) => ({ name, about: `About ${name}.` })),
  };
}

describe("sub-tau nodes", () => {
  it("are built for every public sub-tau, with the network address as id", () => {
    const snapshot = {
      taus: [
        tau("alice.example", ["coach", "landing"]),
        tau("bob.example"),
        tau("c.example", ["arm"]),
      ],
    };
    const nodes = subNodes(snapshot);
    expect(nodes.map((node) => [node.id, node.parent, node.label, node.about])).toEqual([
      ["alice.example/coach", "alice.example", "/coach", "About coach."],
      ["alice.example/landing", "alice.example", "/landing", "About landing."],
      ["c.example/arm", "c.example", "/arm", "About arm."],
    ]);
  });

  it("are none for a snapshot without sub-taus, including one from an older universe", () => {
    const old = { ...tau("old.example") } as Partial<PublicTau>;
    delete old.subs;
    expect(subNodes({ taus: [old as PublicTau, tau("new.example")] })).toEqual([]);
    expect(tauSubNodes(old as PublicTau)).toEqual([]);
  });

  it("sit on an orbit around their tau, never on its disc and never on each other", () => {
    for (const count of [1, 2, 3, 5, 8, 13, 20]) {
      const names = Array.from({ length: count }, (_, i) => `sub-${i}`);
      const nodes = tauSubNodes(tau("a.example", names));
      const orbit = orbitRadius(count);
      expect(orbit).toBeGreaterThanOrEqual(MIN_ORBIT);
      for (const node of nodes) {
        expect(Math.hypot(node.dx, node.dy)).toBeCloseTo(orbit, 1);
        expect(Math.hypot(node.dx, node.dy)).toBeGreaterThan(NODE_RADIUS + SUB_RADIUS);
      }
      for (let i = 0; i < nodes.length; i++) {
        for (let j = i + 1; j < nodes.length; j++) {
          const a = nodes[i]!;
          const b = nodes[j]!;
          expect(Math.hypot(a.dx - b.dx, a.dy - b.dy), `${count}: ${i}-${j}`).toBeGreaterThan(
            2 * SUB_RADIUS,
          );
        }
      }
      expect(reach(count)).toBeCloseTo(orbit + SUB_RADIUS, 5);
    }
    expect(reach(0)).toBe(NODE_RADIUS);
    expect(orbitRadius(20)).toBeGreaterThan(orbitRadius(3));
  });

  it("keep clear of the owner's name above and the tau's name below", () => {
    // The distance of a direction from straight down (π/2) or straight up (3π/2).
    const fromVertical = (angle: number) =>
      Math.min(
        ...[Math.PI / 2, (3 * Math.PI) / 2].map((vertical) => {
          const turn = Math.abs(angle - vertical) % (2 * Math.PI);
          return Math.min(turn, 2 * Math.PI - turn);
        }),
      );
    for (const count of [1, 2, 3, 4, 5, 6, 7, 8, 12, 20]) {
      const names = Array.from({ length: count }, (_, i) => `s${i}x`);
      const nodes = tauSubNodes(tau("a.example", names));
      for (const node of nodes) {
        // A few sub-taus stay well to the side; a crowded orbit is never exactly vertical.
        expect(fromVertical(node.angle)).toBeGreaterThan(count <= 6 ? Math.PI / 12 : 0.01);
        // The name's baseline is a label's height below the lowest disc.
        expect(nameOffset(nodes)).toBeGreaterThanOrEqual(node.dy + SUB_RADIUS + 12);
      }
    }
    // One sub-tau goes to the right; two go right and left.
    expect(subAngle(0, 1)).toBe(0);
    const [right, left] = tauSubNodes(tau("a.example", ["aa", "bb"]));
    expect(left!.dx).toBeLessThan(0);
    expect(right!.dx).toBeGreaterThan(0);
    expect(Math.abs(left!.dy)).toBeLessThan(0.01);
    expect(nameOffset([])).toBe(NODE_RADIUS + 16);
    // Sub-taus beside or above the tau leave its name where it always is.
    expect(nameOffset(tauSubNodes(tau("a.example", ["aa", "bb"])))).toBe(NODE_RADIUS + 16);
    expect(nameOffset(tauSubNodes(tau("a.example", ["aa"])))).toBe(NODE_RADIUS + 16);
  });

  it("put the label outside the orbit, anchored away from the tau", () => {
    const [only] = tauSubNodes(tau("a.example", ["coach"]));
    expect(only).toMatchObject({ anchor: "start" });
    expect(only!.labelX).toBeGreaterThan(SUB_RADIUS);
    const over = tauSubNodes(tau("a.example", ["aa", "bb", "cc", "dd", "ee", "ff"])).filter(
      (node) => node.dy < -10 && Math.abs(node.dx) < 10,
    );
    expect(over).toEqual([]); // nothing sits right over the tau, under the owner's name
    const [right, left] = tauSubNodes(tau("a.example", ["aa", "bb"]));
    expect(left!.anchor).toBe("end");
    expect(left!.labelX).toBeLessThan(0);
    expect(right!.anchor).toBe("start");
    expect(right!.labelX).toBeGreaterThan(0);
  });

  it("are the same on every run", () => {
    const snapshot = { taus: [tau("alice.example", ["coach", "landing", "arm"])] };
    expect(subNodes(snapshot)).toEqual(subNodes(structuredClone(snapshot)));
  });
});

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

  it("group taus by owner, and a tau without an owner on its own", () => {
    expect(groupKey(tau("a.example", [], "  Alice   Smith "))).toBe("owner:alice smith");
    expect(groupKey(tau("a.example"))).toBe("tau:a.example");
  });

  it("hash strings to stable numbers in [0, 1)", () => {
    expect(hash01("alice.example")).toBe(hash01("alice.example"));
    expect(hash01("alice.example")).not.toBe(hash01("bob.example"));
    for (const text of ["", "a", "alice.example/coach"]) {
      expect(hash01(text)).toBeGreaterThanOrEqual(0);
      expect(hash01(text)).toBeLessThan(1);
    }
  });
});
