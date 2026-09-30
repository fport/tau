/** The sigil generator (cloud/shared/character.ts): pure, deterministic, safe SVG. */

import { describe, expect, it } from "vitest";
import {
  character,
  describe as describeTraits,
  FRAMES,
  fnv1a,
  HUES,
  kindOf,
  ownerOf,
  SECONDS,
  traits,
} from "../../shared/character";

/** 200 seeds the way the site makes them: tau addresses and `<address>/<name>` sub-taus. */
const SEEDS = Array.from({ length: 200 }, (_, i) =>
  i % 2 === 0 ? `tau-${i}.example.com` : `tau-${i - 1}.example.com/sub-${i}`,
);

/** The sizes the site and tau-host draw sigils at, from graph nodes to the sub-tau page. */
const SIZES = [16, 21.6, 24, 28, 40, 48.6, 56, 88, 96, 144, 176];

/**
 * A small well-formedness check (the Workers runtime has no DOMParser): every tag is closed
 * in order, every attribute is quoted, and nothing but elements and whitespace sits between
 * the tags. Returns the element names in document order.
 */
function parseXml(xml: string): string[] {
  const names: string[] = [];
  const stack: string[] = [];
  const tag = /<(\/?)([a-zA-Z][\w-]*)((?:\s+[\w:-]+="[^"<>]*")*)\s*(\/?)>/y;
  let at = 0;
  while (at < xml.length) {
    const next = xml.indexOf("<", at);
    if (next === -1) {
      expect(xml.slice(at).trim(), "text after the last tag").toBe("");
      break;
    }
    expect(xml.slice(at, next).trim(), `text at ${at}`).toBe("");
    tag.lastIndex = next;
    const match = tag.exec(xml);
    expect(match, `a well-formed tag at ${next}: ${xml.slice(next, next + 40)}`).not.toBeNull();
    const [whole, closing, name, , selfClosing] = match!;
    if (closing === "/") {
      expect(stack.pop(), `closing </${name}>`).toBe(name);
    } else {
      names.push(name!);
      if (selfClosing !== "/") stack.push(name!);
    }
    at = next + whole.length;
  }
  expect(stack, "unclosed elements").toEqual([]);
  return names;
}

function attribute(svg: string, name: string): string | null {
  const match = new RegExp(`^<svg[^>]*\\s${name}="([^"]*)"`).exec(svg);
  return match === null ? null : match[1]!;
}

describe("sigils", () => {
  it("are the same for the same seed, every time", () => {
    for (const seed of ["alice.example.com", "tau.example.com/@alice", "alice.example.com/coach"]) {
      expect(character(seed)).toBe(character(seed));
      expect(traits(seed)).toEqual(traits(seed));
      expect(character(seed, { size: 40, animated: false })).toBe(
        character(seed, { size: 40, animated: false }),
      );
    }
  });

  it("keeps its sigils: the trait draw order is frozen", () => {
    // tau-host and the site draw the same sigil for an address. If this changes, every tau
    // changes its sigil: do it only on purpose, and update both.
    expect(fnv1a("alice.example.com")).toBe(fnv1a("alice.example.com"));
    expect(traits("alice.example.com")).toMatchObject({
      kind: "tau",
      hue: "plasma",
      frame: "equilateral",
      second: "nested",
      tongues: 2,
      height: 3,
      lean: 0.5,
      sparks: 4,
      embers: true,
      ringSpan: 320,
      ticks: 24,
      scan: null,
      floor: true,
      phase: 5,
    });
    expect(traits("alice.example.com/coach")).toMatchObject({
      kind: "sub",
      hue: "plasma",
      frame: "notched",
      second: "none",
      tongues: 1,
      lean: 1,
      ringSpan: 0,
      ticks: 0,
    });
    expect(traits("tau.example.com/@alice")).toMatchObject({
      kind: "tau",
      hue: "flare",
      frame: "split",
      second: "echo",
      tongues: 2,
      ticks: 12,
    });
  });

  it("tells taus from sub-taus by the seed, or by the kind it is given", () => {
    expect(kindOf("alice.example.com")).toBe("tau");
    expect(kindOf("127.0.0.1:8787")).toBe("tau");
    expect(kindOf("tau.example.com/@alice")).toBe("tau");
    expect(kindOf("alice.example.com/coach")).toBe("sub");
    expect(kindOf("tau.example.com/@alice/coach")).toBe("sub");
    expect(ownerOf("tau.example.com/@alice/coach")).toBe("tau.example.com/@alice");
    expect(ownerOf("alice.example.com/coach")).toBe("alice.example.com");
    expect(ownerOf("alice.example.com/")).toBeNull();
    expect(ownerOf("alice.example.com")).toBeNull();

    const tau = character("alice.example.com");
    expect(attribute(tau, "class")).toMatch(/\bch-tau\b/);
    expect(tau).toContain('class="ch-ring"');
    const sub = character("alice.example.com/coach");
    expect(attribute(sub, "class")).toMatch(/\bch-sub\b/);
    expect(sub).not.toContain("ch-ring");

    // An explicit kind wins over the seed.
    expect(traits("alice.example.com/coach", "tau").kind).toBe("tau");
    expect(attribute(character("alice.example.com", { kind: "sub" }), "class")).toMatch(
      /\bch-sub\b/,
    );
  });

  it("burns a sub-tau in its tau's hue, with one flame and no ring", () => {
    for (const seed of SEEDS.filter((seed) => kindOf(seed) === "sub")) {
      const tr = traits(seed);
      expect(tr.hue, seed).toBe(traits(ownerOf(seed)!).hue);
      expect(tr).toMatchObject({ kind: "sub", second: "none", tongues: 1, ringSpan: 0, ticks: 0 });
    }
  });

  it("gives 200 seeds 200 different sigils, and uses every part of the kit", () => {
    const svgs = new Set(SEEDS.map((seed) => character(seed)));
    expect(svgs.size).toBe(SEEDS.length);
    const all = SEEDS.map((seed) => traits(seed));
    const looks = new Set(
      all.map((t) => `${t.kind} ${t.hue} ${t.frame} ${t.second} ${t.tongues} ${t.height} ${t.lean}`),
    );
    expect(looks.size).toBeGreaterThan(180);
    expect(new Set(all.map((t) => t.hue))).toEqual(new Set(HUES.map((hue) => hue.name)));
    expect(new Set(all.map((t) => t.frame))).toEqual(new Set(FRAMES));
    const taus = all.filter((t) => t.kind === "tau");
    expect(new Set(taus.map((t) => t.second))).toEqual(new Set(SECONDS));
    expect(new Set(taus.map((t) => t.tongues))).toEqual(new Set([1, 2, 3]));
    // Mostly fire, some cold fire: neighbours differ, and the family stays one.
    const cold = all.filter((t) => HUES.find((hue) => hue.name === t.hue)!.cold).length;
    expect(cold).toBeGreaterThan(20);
    expect(cold).toBeLessThan(80);
    // A tau and its sub-tau, or a hosted tau and a hub with the same name, differ.
    expect(character("alice.example.com")).not.toBe(character("alice.example.com/coach"));
    expect(character("tau.example.com/@alice")).not.toBe(character("alice.example.com"));
  });

  it("is well-formed SVG that the pages' CSP allows: no script, style, ids or handlers", () => {
    for (const seed of SEEDS) {
      for (const size of [24, 48.6, 96]) {
        const svg = character(seed, { size });
        expect(
          svg.startsWith('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"'),
        ).toBe(true);
        expect(svg.endsWith("</svg>")).toBe(true);
        const names = parseXml(svg);
        expect(names[0]).toBe("svg");
        for (const name of names) {
          expect(["svg", "g", "path", "rect"], `${seed}: <${name}>`).toContain(name);
        }
        expect(svg).not.toMatch(/<script|<style|\sstyle=|\sid=|\son[a-z]+=|href=|url\(/i);
        expect(svg).not.toMatch(/NaN|Infinity|undefined/);
      }
    }
  });

  it("has no faces or mascot parts: triangles, flames and HUD lines only", () => {
    for (const seed of SEEDS.slice(0, 40)) {
      const svg = character(seed, { size: 176 });
      // Eyes, mouths, cheeks and halos were circles and ellipses.
      expect(svg).not.toMatch(/<circle|<ellipse/);
      expect(svg).toContain('class="ch-flame"');
      expect(svg).toContain('class="ch-core"');
      expect(svg).not.toMatch(/ch-eyes|ch-body|ch-wiggle|ch-bob/);
    }
  });

  it("drops the fine details at small sizes and keeps the lines visible", () => {
    const seed = "alice.example.com";
    const full = character(seed, { size: 176 });
    const small = character(seed, { size: 24 });
    expect(attribute(full, "class")).toMatch(/\bch-l2\b/);
    expect(attribute(small, "class")).toMatch(/\bch-l0\b/);
    expect(attribute(character(seed, { size: 48.6 }), "class")).toMatch(/\bch-l1\b/);
    expect(full).toContain("ch-ring-back");
    expect(full).toContain("ch-spark");
    expect(small).not.toMatch(/ch-ring-back|ch-spark|ch-ember|ch-flame-in/);
    expect(small).toContain('class="ch-ring"');
    expect(small.length).toBeLessThan(full.length / 2);
    // No stroke is thinner than about half a pixel on screen at any size.
    for (const size of SIZES) {
      const svg = character(seed, { size });
      for (const match of svg.matchAll(/stroke-width="([\d.]+)"/g)) {
        expect(Number(match[1]) * (size / 100), `${size}px`).toBeGreaterThanOrEqual(0.45);
      }
    }
  });

  it("is an image with a name, or decorative when the label is empty", () => {
    const seed = "alice.example.com";
    const plain = character(seed);
    expect(attribute(plain, "role")).toBe("img");
    const label = attribute(plain, "aria-label");
    expect(label).toBe(describeTraits(traits(seed)));
    expect(label).toBe(
      "ember sigil: equilateral triangle with a nested triangle, twin flame, plasma violet",
    );
    expect(attribute(character("alice.example.com/coach"), "aria-label")).toBe(
      "ember sub-sigil: notched triangle, single flame, plasma violet",
    );
    for (const other of SEEDS.slice(0, 40)) {
      expect(attribute(character(other), "aria-label")).toMatch(
        /^ember (sub-)?sigil: [a-z-]+ triangle( with an? [a-z ]+ triangle)?, (single|twin|triple) flame, [a-z]+ [a-z]+$/,
      );
    }

    const named = character(seed, { label: 'Alice’s <tau> & "friends"' });
    expect(attribute(named, "aria-label")).toBe(
      "Alice’s &lt;tau&gt; &amp; &quot;friends&quot;",
    );
    parseXml(named);

    const decorative = character(seed, { label: "" });
    expect(attribute(decorative, "aria-hidden")).toBe("true");
    expect(attribute(decorative, "role")).toBeNull();
    expect(attribute(decorative, "aria-label")).toBeNull();
  });

  it("takes a size and turns the motion on or off", () => {
    const seed = "tau-4.example.com/coach";
    expect(attribute(character(seed), "width")).toBe("96");
    const small = character(seed, { size: 28 });
    expect(attribute(small, "width")).toBe("28");
    expect(attribute(small, "height")).toBe("28");
    expect(attribute(small, "class")).toMatch(/^ch ch-sub ch-l0 ch-anim ch-p[0-7]$/);
    const still = character(seed, { animated: false });
    expect(attribute(still, "class")).toBe("ch ch-sub ch-l2");
    expect(attribute(still, "data-hue")).toBe(traits(seed).hue);
  });
});
