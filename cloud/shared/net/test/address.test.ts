/** Both address forms of ADR 0013 §3, the scheme rule, card and inbox URLs, and targets. */

import { describe, expect, it } from "vitest";

import {
  AddressError,
  addressParts,
  baseUrl,
  cardUrl,
  formatTarget,
  hostOf,
  inboxUrl,
  isAddress,
  isHandle,
  isPlainAddress,
  isSubName,
  parseAddress,
  parseTarget,
  RESERVED_SUB_NAMES,
} from "../index.ts";

const HANDLE_39 = "a" + "b".repeat(37) + "c";

describe("addresses", () => {
  it.each([
    "tau.example.com",
    "127.0.0.1:8787",
    "localhost",
    "tau.example.com/@alice",
    "tau.example.com/@a",
    "tau.example.com/@0",
    "tau.example.com/@alice-bob",
    `tau.example.com/@${HANDLE_39}`,
    "127.0.0.1:8787/@alice",
    "localhost:8788/@a1",
  ])("accepts %s", (address) => {
    expect(isAddress(address)).toBe(true);
  });

  it.each([
    "/@",
    "/@alice",
    "tau.example.com/@",
    "tau.example.com/@Upper",
    "tau.example.com/@a/b/c",
    "tau.example.com/@alice/coach",
    "tau.example.com/@-alice",
    "tau.example.com/@alice-",
    `tau.example.com/@${HANDLE_39}d`,
    "tau.example.com/alice",
    "tau.example.com//@alice",
    "tau.example.com/@al ice",
    "tau.example.com/@alice/",
    "tau.example.com/@alice\n",
    "Tau.example.com/@alice",
    "tau.example.com@alice",
    "",
  ])("refuses %j", (address) => {
    expect(isAddress(address)).toBe(false);
  });

  it("refuses what is not a string", () => {
    for (const value of [null, undefined, 1, {}, ["tau.example.com"]]) {
      expect(isAddress(value)).toBe(false);
    }
  });

  it("splits an address into its parts", () => {
    expect(addressParts("tau.example.com:8443/@alice")).toEqual({
      address: "tau.example.com:8443/@alice",
      host: "tau.example.com:8443",
      hostname: "tau.example.com",
      port: 8443,
      handle: "alice",
    });
    expect(addressParts("tau.example.com")).toEqual({
      address: "tau.example.com",
      host: "tau.example.com",
      hostname: "tau.example.com",
      port: null,
      handle: null,
    });
    expect(hostOf("127.0.0.1:8787/@alice")).toBe("127.0.0.1");
    expect(() => hostOf("nope/")).toThrow(AddressError);
  });

  it("tells plain addresses and handles apart", () => {
    expect(isPlainAddress("tau.example.com")).toBe(true);
    expect(isPlainAddress("tau.example.com/@alice")).toBe(false);
    expect(isHandle("alice")).toBe(true);
    expect(isHandle(HANDLE_39)).toBe(true);
    expect(isHandle(`${HANDLE_39}d`)).toBe(false);
    expect(isHandle("Alice")).toBe(false);
  });
});

describe("the scheme rule and URLs", () => {
  it("puts the card and the inbox under the whole address", () => {
    expect(cardUrl("tau.example.com/@alice")).toBe(
      "https://tau.example.com/@alice/.well-known/tau.json",
    );
    expect(inboxUrl("tau.example.com/@alice")).toBe("https://tau.example.com/@alice/net/inbox");
    expect(inboxUrl("bob.example.com")).toBe("https://bob.example.com/net/inbox");
  });

  it("uses http only for localhost and 127.0.0.1 when insecure peers are allowed", () => {
    expect(baseUrl("localhost:8787/@alice", true)).toBe("http://localhost:8787/@alice");
    expect(baseUrl("127.0.0.1:8787/@alice", true)).toBe("http://127.0.0.1:8787/@alice");
    expect(baseUrl("localhost:8787/@alice", false)).toBe("https://localhost:8787/@alice");
    expect(baseUrl("tau.example.com/@alice", true)).toBe("https://tau.example.com/@alice");
    expect(baseUrl("localhost.example.com/@alice", true)).toBe(
      "https://localhost.example.com/@alice",
    );
  });

  it("never builds a URL from text that is not an address", () => {
    for (const text of ["evil.example.com/../x", "a.com/@alice?x=1", "a.com#@b", "https://a.com"]) {
      expect(() => baseUrl(text)).toThrow(AddressError);
      expect(() => cardUrl(text)).toThrow(AddressError);
    }
  });
});

describe("addresses and targets typed by a person", () => {
  it("forgives case, a scheme and trailing slashes", () => {
    expect(parseAddress(" HTTPS://Tau.Example.com/@Alice/ ")).toBe("tau.example.com/@alice");
    expect(parseAddress("http://localhost:8787/@a")).toBe("localhost:8787/@a");
    expect(parseAddress("tau.example.com/@")).toBeNull();
    expect(parseAddress("tau.example.com/coach")).toBeNull();
  });

  it.each([
    ["tau.example.com/@alice/coach", { address: "tau.example.com/@alice", sub: "coach" }],
    ["tau.example.com/@alice", { address: "tau.example.com/@alice", sub: null }],
    ["tau.example.com/coach", { address: "tau.example.com", sub: "coach" }],
    ["https://Tau.Example.com/@Alice/Coach/", { address: "tau.example.com/@alice", sub: "coach" }],
    ["127.0.0.1:8787/@alice/study-buddy", { address: "127.0.0.1:8787/@alice", sub: "study-buddy" }],
  ])("parses %s", (text, target) => {
    expect(parseTarget(text)).toEqual(target);
    expect(parseTarget(formatTarget(target))).toEqual(target);
  });

  it.each([
    "tau.example.com/@alice/coach/x",
    "tau.example.com/@/coach",
    "tau.example.com/@alice/@bob",
    "tau.example.com/@alice/c",
    "tau.example.com/coach/x",
    "tau.example.com//coach",
    "tau.example.com/@Upper Case",
    "",
  ])("refuses the target %j", (text) => {
    expect(parseTarget(text)).toBeNull();
  });

  it("never parses a reserved name as a sub-tau", () => {
    for (const name of RESERVED_SUB_NAMES) {
      expect(isSubName(name)).toBe(true); // the wire pattern allows them ...
      expect(parseTarget(`tau.example.com/${name}`)).toBeNull(); // ... a target never
      expect(parseTarget(`tau.example.com/@alice/${name}`)).toBeNull();
    }
  });
});
