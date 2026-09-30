/** The snapshot builder on its own: no storage, no Worker. */

import { describe, expect, it } from "vitest";
import {
  buildSnapshot,
  isOnline,
  ONLINE_WINDOW_SECONDS,
  type ReportRow,
  type TauRow,
  tauView,
} from "../src/snapshot";

const NOW = 1_800_000_000;

function tau(address: string, joinedAt: number, lastSeen = NOW): TauRow {
  return {
    address,
    name: `${address} tau`,
    owner: "",
    about: "",
    joined_at: joinedAt,
    last_seen: lastSeen,
  };
}

function report(reporter: string, peer: string, messages: number): ReportRow {
  return { reporter, peer, messages };
}

describe("buildSnapshot", () => {
  it("is empty for an empty directory", () => {
    expect(buildSnapshot("u.example", NOW, [], [])).toEqual({
      universe: "u.example",
      generated_at: NOW,
      stats: { taus: 0, online: 0, messages: 0 },
      taus: [],
      links: [],
    });
  });

  it("orders taus by joined_at, then address", () => {
    const snap = buildSnapshot(
      "u",
      NOW,
      [tau("c.example", 3), tau("b.example", 1), tau("a.example", 3)],
      [],
    );
    expect(snap.taus.map((t) => t.address)).toEqual(["b.example", "a.example", "c.example"]);
  });

  it("marks taus online within two hours of their last report", () => {
    const snap = buildSnapshot(
      "u",
      NOW,
      [
        tau("fresh.example", 1, NOW),
        tau("edge.example", 2, NOW - ONLINE_WINDOW_SECONDS),
        tau("old.example", 3, NOW - ONLINE_WINDOW_SECONDS - 1),
        tau("ahead.example", 4, NOW + 200),
      ],
      [],
    );
    expect(snap.taus.map((t) => [t.address, t.online])).toEqual([
      ["fresh.example", true],
      ["edge.example", true],
      ["old.example", false],
      ["ahead.example", true],
    ]);
    expect(snap.stats.online).toBe(3);
    expect(isOnline(NOW - 7_200, NOW)).toBe(true);
    expect(isOnline(NOW - 7_201, NOW)).toBe(false);
  });

  it("keeps only mutual links between joined taus, with the smaller count", () => {
    const taus = [tau("a.example", 1), tau("b.example", 2), tau("c.example", 3)];
    const reports = [
      report("b.example", "a.example", 12),
      report("a.example", "b.example", 7),
      // One-sided: c reports a, a does not report c.
      report("c.example", "a.example", 5),
      // Mutual, but d is not joined.
      report("c.example", "d.example", 4),
      report("d.example", "c.example", 4),
    ];
    const snap = buildSnapshot("u", NOW, taus, reports);
    expect(snap.links).toEqual([{ a: "a.example", b: "b.example", messages: 7 }]);
    expect(snap.stats).toEqual({ taus: 3, online: 3, messages: 7 });
  });

  it("sums messages over the visible links and orders them by a, then b", () => {
    const taus = ["a", "b", "c", "d"].map((x, i) => tau(`${x}.example`, i));
    const both = (x: string, y: string, m: number, n: number) => [
      report(`${x}.example`, `${y}.example`, m),
      report(`${y}.example`, `${x}.example`, n),
    ];
    const reports = [...both("c", "d", 3, 9), ...both("b", "a", 5, 2), ...both("a", "c", 0, 4)];
    const snap = buildSnapshot("u", NOW, taus, reports);
    expect(snap.links).toEqual([
      { a: "a.example", b: "b.example", messages: 2 },
      { a: "a.example", b: "c.example", messages: 0 },
      { a: "c.example", b: "d.example", messages: 3 },
    ]);
    expect(snap.stats.messages).toBe(5);
  });

  it("never exposes sign keys or other stored columns", () => {
    const row = { ...tau("a.example", 1), sign_key: "secret-ish" } as TauRow;
    const snap = buildSnapshot("u", NOW, [row], []);
    expect(Object.keys(snap.taus[0]!)).toEqual([
      "address",
      "name",
      "owner",
      "about",
      "joined_at",
      "last_seen",
      "online",
    ]);
  });
});

describe("tauView", () => {
  const taus = [tau("a.example", 1), tau("b.example", 2), tau("c.example", 3)];
  const reports = [
    report("a.example", "b.example", 3),
    report("b.example", "a.example", 3),
    report("c.example", "a.example", 8),
    report("a.example", "c.example", 9),
  ];
  const snap = buildSnapshot("u", NOW, taus, reports);

  it("lists a tau's links by peer", () => {
    expect(tauView(snap, "a.example")?.links).toEqual([
      { peer: "b.example", messages: 3 },
      { peer: "c.example", messages: 8 },
    ]);
    expect(tauView(snap, "c.example")?.links).toEqual([{ peer: "a.example", messages: 8 }]);
  });

  it("is null for a tau that is not listed", () => {
    expect(tauView(snap, "z.example")).toBeNull();
  });
});
