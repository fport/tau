import { describe, expect, it } from "vitest";
import {
  ADDRESS_PATTERN,
  baseUrl,
  HANDLE_PATTERN,
  hostOf,
  isAddress,
  isHost,
  ownAddress,
} from "../src/address";
import {
  b64uDecode,
  b64uEncode,
  b64uKey,
  signedMessage,
  tokenEquals,
  verifyEd25519,
} from "../src/crypto";
import type { SpineEnv } from "../src/env";
import { VERSION } from "../src/version";
import pkg from "../package.json";
import { publicKeyOf, VECTOR } from "./helpers";

function bytes(text: string): Uint8Array {
  const decoded = b64uDecode(text);
  if (decoded === null) throw new Error(`not b64u: ${text}`);
  return decoded;
}

describe("the §3 test vector", () => {
  it("derives the published sign_key from the seed", async () => {
    expect(await publicKeyOf(VECTOR.signSeed)).toBe(VECTOR.signKey);
  });

  it("decodes the payload to the documented JSON", () => {
    expect(new TextDecoder().decode(bytes(VECTOR.payload))).toBe(VECTOR.decoded);
  });

  it("verifies with WebCrypto Ed25519", async () => {
    const ok = await verifyEd25519(
      bytes(VECTOR.signKey),
      bytes(VECTOR.sig),
      signedMessage(bytes(VECTOR.payload)),
    );
    expect(ok).toBe(true);
  });

  it("fails for a tampered payload", async () => {
    const tampered = new TextEncoder().encode(VECTOR.decoded.replace('"hops":0', '"hops":1'));
    const ok = await verifyEd25519(
      bytes(VECTOR.signKey),
      bytes(VECTOR.sig),
      signedMessage(tampered),
    );
    expect(ok).toBe(false);
  });

  it("fails without the tau-net/1 context", async () => {
    const ok = await verifyEd25519(bytes(VECTOR.signKey), bytes(VECTOR.sig), bytes(VECTOR.payload));
    expect(ok).toBe(false);
  });

  it("fails for a wrong key or a malformed signature", async () => {
    const message = signedMessage(bytes(VECTOR.payload));
    expect(await verifyEd25519(bytes(VECTOR.boxKey), bytes(VECTOR.sig), message)).toBe(false);
    expect(await verifyEd25519(bytes(VECTOR.signKey), new Uint8Array(10), message)).toBe(false);
  });
});

describe("base64url", () => {
  it("round-trips without padding", () => {
    for (let length = 0; length < 40; length++) {
      const data = crypto.getRandomValues(new Uint8Array(length));
      const text = b64uEncode(data);
      expect(text).not.toMatch(/[=+/]/);
      expect(b64uDecode(text)).toEqual(data);
    }
  });

  it("accepts padding and rejects other alphabets", () => {
    expect(b64uDecode("AAE=")).toEqual(new Uint8Array([0, 1]));
    expect(b64uDecode("AAE")).toEqual(new Uint8Array([0, 1]));
    expect(b64uDecode("AA+/")).toBeNull();
    expect(b64uDecode("A")).toBeNull();
    expect(b64uDecode("AAE==")).toBeNull();
    expect(b64uDecode("not base64!")).toBeNull();
  });

  it("checks key lengths", () => {
    expect(b64uKey(VECTOR.signKey)).toHaveLength(32);
    expect(b64uKey("AAAA")).toBeNull();
    expect(b64uKey(42)).toBeNull();
  });
});

describe("tokens", () => {
  it("compares in constant time, whatever the lengths", async () => {
    expect(await tokenEquals("secret", "secret")).toBe(true);
    expect(await tokenEquals("secret", "Secret")).toBe(false);
    expect(await tokenEquals("", "secret")).toBe(false);
    expect(await tokenEquals("secret-and-more", "secret")).toBe(false);
  });
});

describe("addresses", () => {
  it("follows the §1 pattern", () => {
    for (const ok of [
      "tau.example.com",
      "tau-spine.alice.workers.dev",
      "127.0.0.1:8787",
      "localhost",
    ]) {
      expect(isAddress(ok), ok).toBe(true);
    }
    for (const bad of [
      "Tau.example.com",
      "-tau.example",
      "tau..example",
      "tau.example:",
      "https://tau.example",
      "tau.example/x",
      "",
    ]) {
      expect(isAddress(bad), bad).toBe(false);
    }
    expect(ADDRESS_PATTERN.test("a".repeat(63))).toBe(true);
    expect(ADDRESS_PATTERN.test("a".repeat(64))).toBe(false);
  });

  it("takes host/@handle addresses (ADR 0013)", () => {
    for (const ok of [
      "tau.example.com/@alice",
      "tau.example.com/@a",
      "tau.example.com/@alice-bob",
      `tau.example.com/@${"a".repeat(39)}`,
      "127.0.0.1:8787/@alice",
    ]) {
      expect(isAddress(ok), ok).toBe(true);
      expect(isHost(ok), ok).toBe(false);
    }
    for (const bad of [
      "tau.example.com/@",
      "tau.example.com/@Upper",
      "tau.example.com/@a/b/c",
      "tau.example.com/@alice/coach",
      "tau.example.com/@alice/",
      "tau.example.com/@-alice",
      "tau.example.com/@alice-",
      `tau.example.com/@${"a".repeat(40)}`,
      "tau.example.com/alice",
      "tau.example.com//@alice",
      "/@alice",
      "@alice",
    ]) {
      expect(isAddress(bad), bad).toBe(false);
    }
    expect(isHost("tau.example.com")).toBe(true);
    expect(HANDLE_PATTERN.test("alice")).toBe(true);
    expect(hostOf("127.0.0.1:8787/@alice")).toBe("127.0.0.1");
    expect(hostOf("tau.example.com/@alice")).toBe("tau.example.com");
    expect(baseUrl("tau.example.com/@alice", true)).toBe("https://tau.example.com/@alice");
    expect(baseUrl("127.0.0.1:8787/@alice", true)).toBe("http://127.0.0.1:8787/@alice");
  });

  it("uses http only for localhost and 127.0.0.1 with insecure peers allowed", () => {
    expect(hostOf("127.0.0.1:8787")).toBe("127.0.0.1");
    expect(baseUrl("127.0.0.1:8787", true)).toBe("http://127.0.0.1:8787");
    expect(baseUrl("localhost:8788", true)).toBe("http://localhost:8788");
    expect(baseUrl("127.0.0.1:8787", false)).toBe("https://127.0.0.1:8787");
    expect(baseUrl("tau.example.com", true)).toBe("https://tau.example.com");
    expect(baseUrl("10.0.0.1:80", true)).toBe("https://10.0.0.1:80");
  });

  it("is the ADDRESS variable when set, else the request host", () => {
    const url = new URL("https://Tau-Spine.Example.workers.dev/net/inbox");
    expect(ownAddress({ ADDRESS: "" } as SpineEnv, url)).toBe("tau-spine.example.workers.dev");
    expect(ownAddress({ ADDRESS: " Tau.Example.com " } as SpineEnv, url)).toBe("tau.example.com");
    expect(ownAddress({ ADDRESS: "" } as SpineEnv, new URL("http://127.0.0.1:8787/"))).toBe(
      "127.0.0.1:8787",
    );
  });
});

it("reports the package version", () => {
  expect(VERSION).toBe(pkg.version);
});
