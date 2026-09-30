/**
 * The primitives of the tau network protocol: Ed25519, X25519 and HKDF-SHA256 on WebCrypto,
 * and ChaCha20-Poly1305 from `@noble/ciphers` (WebCrypto has no ChaCha20).
 *
 * WebCrypto cannot import a raw private key, so a 32-byte seed (Ed25519) or scalar (X25519) is
 * wrapped in its fixed PKCS#8 header (RFC 8410). The public key comes from exporting the
 * private key as a JWK once (`x`); the CryptoKey kept for use is not extractable.
 */

import { chacha20poly1305 } from "@noble/ciphers/chacha.js";

import { b64uKey, concatBytes } from "./b64u.ts";

export const KEY_BYTES = 32;
export const SIGNATURE_BYTES = 64;
export const NONCE_BYTES = 12;

// SEQUENCE { INTEGER 0, SEQUENCE { OID 1.3.101.112 | 1.3.101.110 }, OCTET STRING { OCTET STRING (32) } }
const ED25519_PKCS8 = new Uint8Array([
  0x30, 0x2e, 0x02, 0x01, 0x00, 0x30, 0x05, 0x06, 0x03, 0x2b, 0x65, 0x70, 0x04, 0x22, 0x04, 0x20,
]);
const X25519_PKCS8 = new Uint8Array([
  0x30, 0x2e, 0x02, 0x01, 0x00, 0x30, 0x05, 0x06, 0x03, 0x2b, 0x65, 0x6e, 0x04, 0x22, 0x04, 0x20,
]);

/** A private key for use and its raw 32-byte public key. */
export interface KeyPair {
  privateKey: CryptoKey;
  publicKey: Uint8Array;
}

function jwkPublic(jwk: JsonWebKey): Uint8Array {
  const x = b64uKey(jwk.x);
  if (x === null) throw new Error("the runtime exported a key without a 32-byte x");
  return x;
}

async function importPrivate(
  header: Uint8Array,
  seed: Uint8Array,
  algorithm: "Ed25519" | "X25519",
  usages: ("sign" | "deriveBits")[],
): Promise<KeyPair> {
  if (seed.length !== KEY_BYTES) throw new Error(`${algorithm} seed must be ${KEY_BYTES} bytes`);
  const pkcs8 = concatBytes(header, seed);
  const exportable = await crypto.subtle.importKey(
    "pkcs8",
    pkcs8,
    { name: algorithm },
    true,
    usages,
  );
  const publicKey = jwkPublic((await crypto.subtle.exportKey("jwk", exportable)) as JsonWebKey);
  const privateKey = await crypto.subtle.importKey(
    "pkcs8",
    pkcs8,
    { name: algorithm },
    false,
    usages,
  );
  return { privateKey, publicKey };
}

/** The Ed25519 key pair of a 32-byte seed. */
export function ed25519FromSeed(seed: Uint8Array): Promise<KeyPair> {
  return importPrivate(ED25519_PKCS8, seed, "Ed25519", ["sign"]);
}

/** The X25519 key pair of a 32-byte private key. */
export function x25519FromSeed(seed: Uint8Array): Promise<KeyPair> {
  return importPrivate(X25519_PKCS8, seed, "X25519", ["deriveBits"]);
}

/** An Ed25519 signature (64 bytes) of `message`. */
export async function ed25519Sign(privateKey: CryptoKey, message: Uint8Array): Promise<Uint8Array> {
  return new Uint8Array(await crypto.subtle.sign({ name: "Ed25519" }, privateKey, message));
}

/** Verifies an Ed25519 signature; any malformed input is simply "does not verify". */
export async function ed25519Verify(
  publicKey: Uint8Array,
  signature: Uint8Array,
  message: Uint8Array,
): Promise<boolean> {
  if (publicKey.length !== KEY_BYTES || signature.length !== SIGNATURE_BYTES) return false;
  try {
    const key = await crypto.subtle.importKey("raw", publicKey, { name: "Ed25519" }, false, [
      "verify",
    ]);
    return await crypto.subtle.verify({ name: "Ed25519" }, key, signature, message);
  } catch {
    return false;
  }
}

/**
 * The X25519 shared secret of `privateKey` and a peer's raw public key. Throws for a key of
 * the wrong length and for an all-zero result (a low-order peer key), as tau-net does.
 */
export async function x25519(
  privateKey: CryptoKey,
  peerPublicKey: Uint8Array,
): Promise<Uint8Array> {
  if (peerPublicKey.length !== KEY_BYTES) throw new Error("X25519 public key must be 32 bytes");
  const peer = await crypto.subtle.importKey("raw", peerPublicKey, { name: "X25519" }, false, []);
  // `public` is the WebCrypto name everywhere; @cloudflare/workers-types spells it `$public`.
  const algorithm = { name: "X25519", public: peer } as Parameters<SubtleCrypto["deriveBits"]>[0];
  const shared = new Uint8Array(await crypto.subtle.deriveBits(algorithm, privateKey, 256));
  if (shared.every((byte) => byte === 0)) throw new Error("X25519 shared secret is all zero");
  return shared;
}

/** HKDF-SHA256 (RFC 5869) of `ikm` with `salt` and `info`, `length` bytes. */
export async function hkdfSha256(
  ikm: Uint8Array,
  salt: Uint8Array,
  info: Uint8Array,
  length: number,
): Promise<Uint8Array> {
  const key = await crypto.subtle.importKey("raw", ikm, "HKDF", false, ["deriveBits"]);
  return new Uint8Array(
    await crypto.subtle.deriveBits({ name: "HKDF", hash: "SHA-256", salt, info }, key, length * 8),
  );
}

/** ChaCha20-Poly1305 (RFC 8439): the ciphertext with its 16-byte tag appended. */
export function chachaSeal(
  key: Uint8Array,
  nonce: Uint8Array,
  plaintext: Uint8Array,
  aad: Uint8Array,
): Uint8Array {
  return chacha20poly1305(key, nonce, aad).encrypt(plaintext);
}

/** Opens a ChaCha20-Poly1305 ciphertext; null when the tag does not verify or input is bad. */
export function chachaOpen(
  key: Uint8Array,
  nonce: Uint8Array,
  ciphertext: Uint8Array,
  aad: Uint8Array,
): Uint8Array | null {
  try {
    return chacha20poly1305(key, nonce, aad).decrypt(ciphertext);
  } catch {
    return null;
  }
}
