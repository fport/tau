import { describe, expect, it } from "vitest";
import { b64uEncode } from "../src/crypto";
import { masterKey, open, seal, VaultError } from "../src/vault";

const KEY = b64uEncode(new Uint8Array(32).map((_, i) => i));
const OTHER = b64uEncode(new Uint8Array(32).map((_, i) => 255 - i));

describe("vault", () => {
  it("round-trips a value for one tau and one purpose", async () => {
    const sealed = await seal(KEY, "alice", "provider_key", "sk-test-1234567890");
    expect(sealed.startsWith("v1.")).toBe(true);
    expect(sealed).not.toContain("sk-test");
    expect(await open(KEY, "alice", "provider_key", sealed)).toBe("sk-test-1234567890");
  });

  it("uses a fresh IV every time", async () => {
    const a = await seal(KEY, "alice", "provider_key", "same");
    const b = await seal(KEY, "alice", "provider_key", "same");
    expect(a).not.toBe(b);
  });

  it("cannot be opened by another tau, for another purpose or with another VAULT_KEY", async () => {
    const sealed = await seal(KEY, "alice", "provider_key", "secret");
    await expect(open(KEY, "bob", "provider_key", sealed)).rejects.toBeInstanceOf(VaultError);
    await expect(open(KEY, "alice", "net_key", sealed)).rejects.toBeInstanceOf(VaultError);
    await expect(open(OTHER, "alice", "provider_key", sealed)).rejects.toBeInstanceOf(VaultError);
  });

  it("rejects tampered and malformed values", async () => {
    const sealed = await seal(KEY, "alice", "provider_key", "secret");
    const last = sealed.at(-1) === "A" ? "B" : "A";
    await expect(open(KEY, "alice", "provider_key", sealed.slice(0, -1) + last)).rejects.toBeInstanceOf(VaultError);
    await expect(open(KEY, "alice", "provider_key", "v2.abc")).rejects.toBeInstanceOf(VaultError);
    await expect(open(KEY, "alice", "provider_key", "v1.!!")).rejects.toBeInstanceOf(VaultError);
  });

  it("needs VAULT_KEY to be 32 bytes of base64url", () => {
    expect(() => masterKey(undefined)).toThrow("VAULT_KEY is not set");
    expect(() => masterKey("")).toThrow("VAULT_KEY is not set");
    expect(() => masterKey("c2hvcnQ")).toThrow("32 bytes");
    expect(masterKey(KEY)).toHaveLength(32);
  });
});
