/** The landing page's universe without the DOM (client/cosmos.ts): pure, no canvas. */

import { describe, expect, it } from "vitest";
import {
  type Camera,
  frame,
  hash,
  LINK_LENGTH,
  orbits,
  PORTAL,
  positions,
  project,
  reachOf,
  STAR_INNER,
  STAR_OUTER,
  stars,
  tauPath,
} from "../client/cosmos";

const ORIGIN = { x: 0, y: 0, z: 0 };

function distance(
  a: { x: number; y: number; z: number },
  b: { x: number; y: number; z: number },
): number {
  return Math.hypot(a.x - b.x, a.y - b.y, a.z - b.z);
}

describe("stars", () => {
  it("gives the same sky for the same seed, inside the shell", () => {
    const sky = stars(500);
    expect(sky).toHaveLength(500);
    expect(stars(500)).toEqual(sky);
    expect(stars(500, 8)).not.toEqual(sky);
    for (const star of sky) {
      const radius = distance(star, ORIGIN);
      expect(radius).toBeGreaterThanOrEqual(STAR_INNER - 1e-6);
      expect(radius).toBeLessThanOrEqual(STAR_OUTER + 1e-6);
      expect(star.alpha).toBeGreaterThan(0);
      expect(star.alpha).toBeLessThanOrEqual(1);
    }
  });

  it("keeps most stars dim and grey", () => {
    const sky = stars(2_000);
    expect(sky.filter((star) => star.warm).length).toBeLessThan(sky.length * 0.12);
    expect(sky.filter((star) => star.size > 1).length).toBeLessThan(sky.length * 0.15);
  });
});

describe("positions", () => {
  const taus = ["alice.example", "bob.example", "carol.example", "dave.example", "erin.example"];
  const links = [
    { a: "alice.example", b: "bob.example", messages: 12 },
    { a: "bob.example", b: "carol.example", messages: 3 },
  ];

  it("puts a lone tau at the origin", () => {
    expect(positions(["alice.example"], [])).toEqual(new Map([["alice.example", ORIGIN]]));
  });

  it("is deterministic and centred", () => {
    const placed = positions(taus, links);
    expect(positions(taus, links)).toEqual(placed);
    const points = [...placed.values()];
    for (const axis of ["x", "y", "z"] as const) {
      const mean = points.reduce((sum, p) => sum + p[axis], 0) / points.length;
      expect(Math.abs(mean)).toBeLessThan(1e-6);
    }
  });

  it("keeps taus apart and linked taus near each other", () => {
    const placed = positions(taus, links);
    for (const a of taus) {
      for (const b of taus) {
        if (a < b)
          expect(distance(placed.get(a)!, placed.get(b)!), `${a} ${b}`).toBeGreaterThan(80);
      }
    }
    for (const link of links) {
      expect(distance(placed.get(link.a)!, placed.get(link.b)!)).toBeLessThan(LINK_LENGTH * 1.6);
    }
  });

  it("ignores links to taus it was not given", () => {
    const placed = positions(
      ["alice.example", "bob.example"],
      [{ a: "alice.example", b: "gone.example", messages: 1 }],
    );
    expect([...placed.keys()]).toEqual(["alice.example", "bob.example"]);
  });

  it("frames at least a few taus' room", () => {
    expect(reachOf([])).toBe(220);
    expect(reachOf([{ x: 300, y: 0, z: 400 }])).toBe(560);
  });
});

describe("orbits", () => {
  it("gives each public sub-tau an orbit, seeded by the tau's address", () => {
    const subs = [{ name: "coach", web: true }, { name: "chef" }];
    const one = orbits("alice.example", subs);
    expect(one.map((orbit) => [orbit.name, orbit.web])).toEqual([
      ["coach", true],
      ["chef", false],
    ]);
    expect(orbits("alice.example", subs)).toEqual(one);
    expect(orbits("bob.example", subs)).not.toEqual(one);
    expect(one[1]!.radius).toBeGreaterThan(one[0]!.radius);
  });
});

describe("project", () => {
  const cam: Camera = {
    target: ORIGIN,
    yaw: 0.7,
    pitch: -0.3,
    dist: 1_000,
    cx: 900,
    cy: 400,
    focal: 1_200,
  };

  it("puts the target where the camera says, at focal / dist", () => {
    const p = project(cam, ORIGIN)!;
    expect(p.x).toBeCloseTo(900);
    expect(p.y).toBeCloseTo(400);
    expect(p.scale).toBeCloseTo(1.2);
  });

  it("draws nearer points larger and drops points behind the camera", () => {
    const flat = { ...cam, yaw: 0, pitch: 0 };
    expect(project(flat, { x: 0, y: 0, z: -500 })!.scale).toBeGreaterThan(
      project(flat, { x: 0, y: 0, z: 500 })!.scale,
    );
    expect(project(flat, { x: 0, y: 0, z: -1_200 })).toBeNull();
    expect(project(flat, { x: 0, y: 0, z: -1_200 }, 2_000)).not.toBeNull();
  });
});

describe("frame", () => {
  it("puts the universe beside the text when there is room", () => {
    const place = frame(
      1_440,
      900,
      { left: 40, top: 330, right: 808, bottom: 830 },
      64,
      400,
      1_123,
    );
    expect(place.layout).toBe("side");
    expect(place.cx).toBeGreaterThan(808);
    expect(place.cx).toBeLessThan(1_440);
  });

  it("puts it above the text on narrow and tall screens", () => {
    const phone = frame(
      390,
      1_400,
      { left: 16, top: 380, right: 374, bottom: 1_300 },
      100,
      400,
      700,
    );
    expect(phone.layout).toBe("stacked");
    expect(phone.cy).toBeGreaterThan(100);
    expect(phone.cy).toBeLessThan(380);
  });

  it("moves the camera back for a bigger universe, within bounds", () => {
    const copy = { left: 40, top: 330, right: 808, bottom: 830 };
    const small = frame(1_440, 900, copy, 64, 220, 1_123);
    const big = frame(1_440, 900, copy, 64, 900, 1_123);
    expect(big.dist).toBeGreaterThan(small.dist);
    expect(frame(1_440, 900, copy, 64, 1e6, 1_123).dist).toBe(4_200);
  });
});

describe("the portal", () => {
  it("opens after the camera is through, and each step follows the one before", () => {
    expect(PORTAL.outer[0]).toBeGreaterThanOrEqual(PORTAL.floor[0]);
    expect(PORTAL.inner[0]).toBeGreaterThan(PORTAL.outer[0]);
    expect(PORTAL.grow[0]).toBeGreaterThan(PORTAL.sky[0]);
    expect(PORTAL.through[0]).toBeLessThan(PORTAL.grow[1]);
    expect(PORTAL.open).toBeGreaterThan(PORTAL.through[1]);
    expect(PORTAL.open).toBeLessThan(PORTAL.settle[1]);
  });
});

describe("tauPath", () => {
  it("opens the person page when the tau has a handle", () => {
    expect(tauPath({ address: "tau.example/@alice", handle: "alice" }, "en")).toBe("/@alice");
    expect(tauPath({ address: "tau.example/@alice", handle: "alice" }, "tr")).toBe("/tr/@alice");
  });

  it("falls back to the tau's place on /universe", () => {
    expect(tauPath({ address: "bob.example", handle: null }, "en")).toBe("/universe#bob.example");
    expect(tauPath({ address: "bob.example" }, "tr")).toBe("/tr/universe#bob.example");
    expect(tauPath({ address: "eve.example", handle: "../evil" }, "en")).toBe(
      "/universe#eve.example",
    );
  });
});

describe("hash", () => {
  it("is FNV-1a", () => {
    expect(hash("")).toBe(0x811c9dc5);
    expect(hash("a")).toBe(0xe40c292c);
  });
});
