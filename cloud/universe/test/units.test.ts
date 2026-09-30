/** Small pure pieces: crypto, addresses, payload parsing, sanitising, versions, brand copies. */

import { describe, expect, it } from "vitest";
import pkg from "../package.json";
import heroCopy from "../public/brand/tau-hero.svg?raw";
import lockupCopy from "../public/brand/tau-lockup-dark.svg?raw";
import markCopy from "../public/brand/tau-mark.svg?raw";
import iconCopy from "../public/brand/tau-app-icon.svg?raw";
import coinCopy from "../public/brand/tau-coin.svg?raw";
import coinEmber from "../public/brand/tau-coin-ember.svg?raw";
import hero from "../../../docs/brand/tau-hero.svg?raw";
import lockup from "../../../docs/brand/tau-lockup-dark.svg?raw";
import mark from "../../../docs/brand/tau-mark.svg?raw";
import icon from "../../../docs/brand/tau-app-icon.svg?raw";
import coin from "../../../docs/brand/tau-coin.svg?raw";
import { baseUrl, isAddress, universeHost } from "../src/address";
import { b64uDecode, b64uEncode, signedMessage, verifyEd25519 } from "../src/crypto";
import {
  charCount,
  normalizeSubs,
  parsePayload,
  parseSubs,
  sanitizeText,
} from "../src/protocol";
import { VERSION } from "../src/version";
import { ALICE, publicKeyOf, signRaw } from "./helpers";

describe("signatures", () => {
  it("derive the network reference's sign_key from its test seed", async () => {
    expect(await publicKeyOf(ALICE.seed)).toBe(ALICE.signKey);
  });

  it("verify over tau-universe/1 and never over the envelope context", async () => {
    const payload = new TextEncoder().encode('{"v":1}');
    const key = b64uDecode(ALICE.signKey)!;
    const universe = await signRaw(payload, ALICE.seed);
    const envelope = await signRaw(payload, ALICE.seed, "tau-net/1\n");
    expect(await verifyEd25519(key, b64uDecode(universe.sig)!, signedMessage(payload))).toBe(true);
    expect(await verifyEd25519(key, b64uDecode(envelope.sig)!, signedMessage(payload))).toBe(false);
    expect(new TextDecoder().decode(signedMessage(new Uint8Array()))).toBe("tau-universe/1\n");
  });

  it("round-trip base64url without padding", () => {
    for (let length = 0; length < 40; length++) {
      const data = crypto.getRandomValues(new Uint8Array(length));
      const text = b64uEncode(data);
      expect(text).not.toMatch(/[=+/]/);
      expect(b64uDecode(text)).toEqual(data);
    }
    expect(b64uDecode("AAE=")).toEqual(new Uint8Array([0, 1]));
    expect(b64uDecode("AA+/")).toBeNull();
  });
});

describe("addresses", () => {
  it("follow the network reference", () => {
    expect(isAddress("tau.example.com")).toBe(true);
    expect(isAddress("127.0.0.1:8790")).toBe(true);
    expect(isAddress("Tau.Example.com")).toBe(false);
    expect(isAddress("tau..example")).toBe(false);
  });

  it("use http only for loopback hosts with insecure peers allowed", () => {
    expect(baseUrl("127.0.0.1:8790", true)).toBe("http://127.0.0.1:8790");
    expect(baseUrl("localhost:8790", true)).toBe("http://localhost:8790");
    expect(baseUrl("127.0.0.1:8790", false)).toBe("https://127.0.0.1:8790");
    expect(baseUrl("tau.example.com", true)).toBe("https://tau.example.com");
  });

  it("name the universe by UNIVERSE, else by the request host", () => {
    const url = new URL("https://Req.Example:8443/api/universe");
    const env = (UNIVERSE: string) => ({ UNIVERSE }) as Env;
    expect(universeHost(env(""), url)).toBe("req.example:8443");
    expect(universeHost(env(" Tau.Example.com "), url)).toBe("tau.example.com");
  });
});

describe("payloads", () => {
  const base = { v: 1, universe: "u", address: "a.example", ts: 1 };

  it("parse each kind with its fields", () => {
    expect(parsePayload({ ...base, kind: "join", owner: "O", about: "A", extra: 1 })).toEqual({
      ok: true,
      value: { ...base, kind: "join", owner: "O", about: "A" },
    });
    expect(
      parsePayload({ ...base, kind: "report", links: [{ peer: "b.example", messages: 2, x: 1 }] }),
    ).toEqual({
      ok: true,
      value: { ...base, kind: "report", links: [{ peer: "b.example", messages: 2 }], subs: [] },
    });
    expect(parsePayload({ ...base, kind: "leave" })).toEqual({
      ok: true,
      value: { ...base, kind: "leave" },
    });
  });

  it("parse a report's sub-taus: absent is none, the name rule, at most 20", () => {
    expect(parseSubs(undefined)).toEqual({ ok: true, value: [] });
    expect(parseSubs([{ name: "coach", about: "A", extra: 1 }, { name: "ab" }])).toEqual({
      ok: true,
      value: [
        { name: "coach", about: "A" },
        { name: "ab", about: "" },
      ],
    });
    expect(parseSubs([{ name: `a${"b".repeat(30)}`, about: "" }]).ok).toBe(true);
    for (const bad of [
      null,
      "coach",
      [{ name: `a${"b".repeat(31)}`, about: "" }],
      [{ name: "a", about: "" }],
      [{ name: "-coach", about: "" }],
      [{ name: "coach", about: null }],
      Array.from({ length: 21 }, (_, i) => ({ name: `s${i}x`, about: "" })),
    ]) {
      expect(parseSubs(bad).ok, JSON.stringify(bad)).toBe(false);
    }
    expect(parseSubs(Array.from({ length: 20 }, (_, i) => ({ name: `s${i}x` }))).ok).toBe(true);
  });

  it("normalise sub-taus: the last entry of a name wins, sanitised, ordered by name", () => {
    expect(
      normalizeSubs([
        { name: "zeta", about: "z" },
        { name: "alpha", about: "one" },
        { name: "alpha", about: "two\u0007 lines\n" },
      ]),
    ).toEqual([
      { name: "alpha", about: "two lines" },
      { name: "zeta", about: "z" },
    ]);
  });

  it("count characters the way Python does", () => {
    expect(charCount("abc")).toBe(3);
    expect(charCount("🦊🦊")).toBe(2);
    expect(charCount("şğı")).toBe(3);
  });
});

describe("sanitizeText", () => {
  it("turns control characters into spaces and trims", () => {
    expect(sanitizeText("  a\u0000b\nc\td\u007f\u0085e  ", 60)).toBe("a b c d e");
  });

  it("drops bidi overrides and isolates", () => {
    expect(sanitizeText("abc‮def⁧", 60)).toBe("abc def");
  });

  it("keeps emoji, accents and joiners, and cuts at the limit", () => {
    expect(sanitizeText("Şule 👩‍💻", 60)).toBe("Şule 👩‍💻");
    expect(sanitizeText("x".repeat(90), 80)).toBe("x".repeat(80));
  });
});

describe("the package", () => {
  it("keeps VERSION in step with package.json", () => {
    expect(VERSION).toBe(pkg.version);
  });

  it("tracks the brand files as exact copies of docs/brand (run `pnpm run sync-brand`)", () => {
    expect(heroCopy).toBe(hero);
    expect(lockupCopy).toBe(lockup);
    expect(markCopy).toBe(mark);
    expect(iconCopy).toBe(icon);
    expect(coinCopy).toBe(coin);
    expect(coinEmber).toBe(coin.replaceAll("currentColor", "#FF7A3D"));
  });
});
