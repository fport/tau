/** The character generator (cloud/shared/character.ts): pure, deterministic, safe SVG. */

import { describe, expect, it } from "vitest";
import {
  ACCESSORIES,
  BODIES,
  character,
  describe as describeTraits,
  EYES,
  fnv1a,
  PALETTE,
  traits,
} from "../../shared/character";

/** 200 seeds the way the site makes them: tau addresses and `<address>/<name>` sub-taus. */
const SEEDS = Array.from({ length: 200 }, (_, i) =>
  i % 2 === 0 ? `tau-${i}.example.com` : `tau-${i - 1}.example.com/sub-${i}`,
);

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

describe("character", () => {
  it("is the same for the same seed, every time", () => {
    for (const seed of ["alice.example.com", "tau.example.com/@alice", "alice.example.com/coach"]) {
      expect(character(seed)).toBe(character(seed));
      expect(traits(seed)).toEqual(traits(seed));
      expect(character(seed, { size: 40, animated: false })).toBe(
        character(seed, { size: 40, animated: false }),
      );
    }
  });

  it("keeps its creatures: the trait draw order is frozen", () => {
    // tau-host and the site draw the same creature for an address. If this changes, every
    // tau changes its face: do it only on purpose, and update both.
    expect(fnv1a("alice.example.com")).toBe(fnv1a("alice.example.com"));
    expect(traits("alice.example.com")).toMatchObject({
      color: "violet",
      body: "sharp",
      eyes: "sleepy",
      mouth: "flat",
      accessory: "halo",
      mark: "core",
      feet: "stubs",
      glow: false,
      phase: 7,
    });
    expect(traits("alice.example.com/coach")).toMatchObject({
      color: "orange",
      body: "lean",
      eyes: "sleepy",
      mouth: "grin",
      accessory: "beret",
    });
    expect(traits("tau.example.com/@alice")).toMatchObject({
      color: "teal",
      body: "tall",
      eyes: "dots",
      accessory: "glasses",
    });
  });

  it("gives 200 seeds 200 different creatures, and uses every part of the kit", () => {
    const svgs = new Set(SEEDS.map((seed) => character(seed)));
    expect(svgs.size).toBe(SEEDS.length);
    const all = SEEDS.map((seed) => traits(seed));
    const looks = new Set(all.map((t) => `${t.color} ${t.body} ${t.eyes} ${t.accessory}`));
    expect(looks.size).toBeGreaterThan(180);
    expect(new Set(all.map((t) => t.color))).toEqual(new Set(PALETTE.map((entry) => entry.name)));
    expect(new Set(all.map((t) => t.body))).toEqual(new Set(BODIES));
    expect(new Set(all.map((t) => t.eyes))).toEqual(new Set(EYES));
    expect(new Set(all.map((t) => t.accessory))).toEqual(new Set(ACCESSORIES));
    // A tau and its sub-tau, or a hosted tau and a hub with the same name, differ.
    expect(character("alice.example.com")).not.toBe(character("alice.example.com/coach"));
    expect(character("tau.example.com/@alice")).not.toBe(character("alice.example.com"));
  });

  it("is well-formed SVG that the pages' CSP allows: no script, style, ids or handlers", () => {
    for (const seed of SEEDS) {
      const svg = character(seed);
      expect(svg.startsWith('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"')).toBe(
        true,
      );
      expect(svg.endsWith("</svg>")).toBe(true);
      const names = parseXml(svg);
      expect(names[0]).toBe("svg");
      for (const name of names) {
        expect(["svg", "g", "path", "circle", "ellipse", "rect"], `${seed}: <${name}>`).toContain(
          name,
        );
      }
      expect(svg).not.toMatch(/<script|<style|\sstyle=|\sid=|\son[a-z]+=|href=|url\(/i);
      expect(svg).not.toMatch(/NaN|Infinity|undefined/);
    }
  });

  it("is an image with a name, or decorative when the label is empty", () => {
    const seed = "alice.example.com";
    const plain = character(seed);
    expect(attribute(plain, "role")).toBe("img");
    const label = attribute(plain, "aria-label");
    expect(label).toBe(describeTraits(traits(seed)));
    expect(label).toMatch(/^Violet sharp triangle creature with a halo$/);
    for (const other of SEEDS.slice(0, 40)) {
      expect(attribute(character(other), "aria-label")?.length ?? 0).toBeGreaterThan(10);
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

  it("takes a size and turns the idle motion on or off", () => {
    const seed = "tau-4.example.com/coach";
    expect(attribute(character(seed), "width")).toBe("96");
    const small = character(seed, { size: 28 });
    expect(attribute(small, "width")).toBe("28");
    expect(attribute(small, "height")).toBe("28");
    expect(attribute(small, "class")).toMatch(/^ch ch-anim ch-p[0-7]$/);
    expect(small).toContain('class="ch-body"');
    const still = character(seed, { animated: false });
    expect(attribute(still, "class")).toBe("ch");
  });
});
