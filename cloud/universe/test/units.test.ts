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
import {
  authorityOf,
  baseUrl,
  handleOfAddress,
  hostedHandle,
  hostOf,
  isAddress,
  isHandle,
  universeHost,
} from "../src/address";
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

  it("accept host/@handle with a GitHub login in lower case", () => {
    for (const address of [
      "tau.example.com/@alice",
      "tau.example.com/@a",
      "127.0.0.1:8790/@bob-2",
      `tau.example.com/@${"a".repeat(39)}`,
    ]) {
      expect(isAddress(address), address).toBe(true);
    }
    for (const address of [
      "tau.example.com/@",
      "tau.example.com/@Alice",
      "tau.example.com/@-alice",
      "tau.example.com/@alice-",
      "tau.example.com/@al_ice",
      `tau.example.com/@${"a".repeat(40)}`,
      "tau.example.com/alice",
      "tau.example.com/@alice/coach",
      "tau.example.com/@alice/",
      "/@alice",
    ]) {
      expect(isAddress(address), address).toBe(false);
    }
    expect(isHandle("alice")).toBe(true);
    expect(isHandle("a-b-c")).toBe(true);
    expect(isHandle("Alice")).toBe(false);
    expect(isHandle("")).toBe(false);
  });

  it("split an address into its host, authority and handle", () => {
    expect(hostOf("tau.example.com:8443/@alice")).toBe("tau.example.com");
    expect(hostOf("127.0.0.1:8790")).toBe("127.0.0.1");
    expect(authorityOf("tau.example.com:8443/@alice")).toBe("tau.example.com:8443");
    expect(handleOfAddress("tau.example.com/@alice")).toBe("alice");
    expect(handleOfAddress("tau.example.com")).toBeNull();
    expect(hostedHandle("tau.example.com/@alice", "tau.example.com")).toBe("alice");
    expect(hostedHandle("tau.example.com/@alice", "other.example")).toBeNull();
    expect(hostedHandle("tau.example.com", "tau.example.com")).toBeNull();
    expect(hostedHandle("127.0.0.1:8790/@alice", "127.0.0.1:8790")).toBe("alice");
  });

  it("use http only for loopback hosts with insecure peers allowed", () => {
    expect(baseUrl("127.0.0.1:8790", true)).toBe("http://127.0.0.1:8790");
    expect(baseUrl("localhost:8790", true)).toBe("http://localhost:8790");
    expect(baseUrl("127.0.0.1:8790", false)).toBe("https://127.0.0.1:8790");
    expect(baseUrl("tau.example.com", true)).toBe("https://tau.example.com");
    expect(baseUrl("localhost:8790/@alice", true)).toBe("http://localhost:8790/@alice");
    expect(baseUrl("tau.example.com/@alice", true)).toBe("https://tau.example.com/@alice");
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
    expect(parsePayload({ ...base, kind: "claim", nonce: "AAECAwQFBgcICQoLDA0ODw" })).toEqual({
      ok: true,
      value: { ...base, kind: "claim", nonce: "AAECAwQFBgcICQoLDA0ODw" },
    });
  });

  it("parse a claim's nonce: 16-64 base64url characters", () => {
    const claim = (nonce: unknown) => parsePayload({ ...base, kind: "claim", nonce });
    for (const nonce of ["0123456789abcdef", "AAECAwQFBgcICQoLDA0ODw", "A-_z".repeat(16)]) {
      expect(claim(nonce).ok, nonce).toBe(true);
    }
    const bad = [
      undefined,
      7,
      "",
      "abcdefgh",
      "has space!0123456",
      "a".repeat(65),
      "a+b/cdefg=1234567",
    ];
    for (const nonce of bad) {
      expect(claim(nonce).ok, String(nonce)).toBe(false);
    }
    expect(parsePayload({ ...base, kind: "join", address: "tau.example/@alice" }).ok).toBe(true);
  });

  it("parse a report's sub-taus: absent is none, the name rule, at most 20", () => {
    expect(parseSubs(undefined)).toEqual({ ok: true, value: [] });
    expect(parseSubs(null)).toEqual({ ok: true, value: [] });
    expect(parseSubs([{ name: "coach", about: "A", extra: 1 }, { name: "ab" }])).toEqual({
      ok: true,
      value: [
        { name: "coach", about: "A", web: false, starters: [] },
        { name: "ab", about: "", web: false, starters: [] },
      ],
    });
    expect(parseSubs([{ name: `a${"b".repeat(30)}`, about: "" }]).ok).toBe(true);
    for (const bad of [
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

  it("parse a sub-tau's web flag and starters", () => {
    const starters = ["Plan my week", "🦊".repeat(80), "x", "How do I start?"];
    expect(parseSubs([{ name: "coach", about: "", web: true, starters }])).toEqual({
      ok: true,
      value: [{ name: "coach", about: "", web: true, starters }],
    });
    expect(parseSubs([{ name: "coach", web: false, starters: [] }]).ok).toBe(true);
    for (const bad of [
      { web: "yes" },
      { web: 1 },
      { web: null },
      { starters: "hi" },
      { starters: [""] },
      { starters: [7] },
      { starters: ["x".repeat(81)] },
      { starters: ["a", "b", "c", "d", "e"] },
    ]) {
      expect(parseSubs([{ name: "coach", ...bad }]).ok, JSON.stringify(bad)).toBe(false);
    }
  });

  it("normalise sub-taus: the last entry of a name wins, sanitised, ordered by name", () => {
    const sub = (name: string, about: string, starters: string[] = []) => ({
      name,
      about,
      web: false,
      starters,
    });
    expect(
      normalizeSubs([
        sub("zeta", "z"),
        sub("alpha", "one"),
        sub("alpha", "two\u0007 lines\n", [" Hi\nthere ", "\u0000", "ok"]),
      ]),
    ).toEqual([sub("alpha", "two lines", ["Hi there", "ok"]), sub("zeta", "z")]);
  });

  it("drop the sub-tau names ADR 0013 reserves", () => {
    const names = ["net", "app", "api", "auth", "claim", "hub", "coach", "universe"];
    const subs = names.map((name) => ({ name, about: "", web: false, starters: [] }));
    expect(normalizeSubs(subs).map((sub) => sub.name)).toEqual(["coach", "universe"]);
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

  it("tracks the brand files as exact copies of docs/brand (run `bun run sync-brand`)", () => {
    expect(heroCopy).toBe(hero);
    expect(lockupCopy).toBe(lockup);
    expect(markCopy).toBe(mark);
    expect(iconCopy).toBe(icon);
    expect(coinCopy).toBe(coin);
    expect(coinEmber).toBe(coin.replaceAll("currentColor", "#FF7A3D"));
  });
});
