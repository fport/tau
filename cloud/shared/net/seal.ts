/**
 * The sealed box of an envelope (§3 of docs/reference/tau-network.md):
 *
 * 1. `esk, epk` = a fresh X25519 key pair; `shared = X25519(esk, recipient.box_key)`.
 * 2. `key = HKDF-SHA256(ikm=shared, salt=epk || recipient.box_key, info="tau-net/1 box", 32)`.
 * 3. `nonce` = 12 random bytes; `aad = "tau-net/1|{id}|{kind}|{from}|{to}"` (aadFor).
 * 4. `ct = ChaCha20-Poly1305(key).encrypt(nonce, plaintext, aad)`, plaintext compact UTF-8 JSON.
 * 5. `box = {"epk": b64u(epk), "nonce": b64u(nonce), "ct": b64u(ct)}`.
 *
 * The aad binds a box to its header, so a box moved to another envelope does not open. Every
 * failure is a BoxError.
 */

import {
  b64uDecode,
  b64uEncode,
  b64uKey,
  compactJson,
  concatBytes,
  isObject,
  parseJsonBytes,
  randomBytes,
  utf8Encode,
} from "./b64u.ts";
import {
  chachaOpen,
  chachaSeal,
  hkdfSha256,
  KEY_BYTES,
  NONCE_BYTES,
  x25519,
  x25519FromSeed,
} from "./crypto.ts";
import { BoxError } from "./errors.ts";
import type { Identity } from "./identity.ts";

export const BOX_INFO = utf8Encode("tau-net/1 box");

/** The sealed content of an envelope, as it travels. */
export interface Box {
  epk: string;
  nonce: string;
  ct: string;
}

/**
 * Fixed randomness for a seal: only test vectors use it (a real seal draws both from the
 * platform's random source, through the same code path).
 */
export interface SealOptions {
  /** The ephemeral X25519 private key (32 bytes). */
  ephemeralSecret?: Uint8Array;
  /** The ChaCha20-Poly1305 nonce (12 bytes). */
  nonce?: Uint8Array;
}

/** The associated data that binds a box to its header. */
export function aadFor(id: string, kind: string, from: string, to: string): Uint8Array {
  return utf8Encode(`tau-net/1|${id}|${kind}|${from}|${to}`);
}

function boxKey(shared: Uint8Array, epk: Uint8Array, recipient: Uint8Array): Promise<Uint8Array> {
  return hkdfSha256(shared, concatBytes(epk, recipient), BOX_INFO, KEY_BYTES);
}

/** Seals `plaintext` bytes to a recipient's box key (raw 32 bytes or b64u). */
export async function sealBytes(
  plaintext: Uint8Array,
  recipientBoxKey: Uint8Array | string,
  aad: Uint8Array,
  options: SealOptions = {},
): Promise<Box> {
  const recipient =
    typeof recipientBoxKey === "string" ? b64uKey(recipientBoxKey) : recipientBoxKey;
  if (recipient === null || recipient.length !== KEY_BYTES) {
    throw new BoxError("recipient box key is invalid");
  }
  const secret = options.ephemeralSecret ?? randomBytes(KEY_BYTES);
  const nonce = options.nonce ?? randomBytes(NONCE_BYTES);
  if (secret.length !== KEY_BYTES || nonce.length !== NONCE_BYTES) {
    throw new BoxError("ephemeral key or nonce has the wrong length");
  }
  let epk: Uint8Array;
  let shared: Uint8Array;
  try {
    const ephemeral = await x25519FromSeed(secret);
    epk = ephemeral.publicKey;
    shared = await x25519(ephemeral.privateKey, recipient);
  } catch {
    throw new BoxError("recipient box key is invalid");
  }
  const key = await boxKey(shared, epk, recipient);
  const ct = chachaSeal(key, nonce, plaintext, aad);
  return { epk: b64uEncode(epk), nonce: b64uEncode(nonce), ct: b64uEncode(ct) };
}

/** Seals `content` as compact UTF-8 JSON (what tau-net's `seal` does). */
export function seal(
  content: Record<string, unknown>,
  recipientBoxKey: Uint8Array | string,
  aad: Uint8Array,
  options: SealOptions = {},
): Promise<Box> {
  return sealBytes(compactJson(content), recipientBoxKey, aad, options);
}

/** Opens `box` with this identity's box key to its plaintext bytes; BoxError on any failure. */
export async function openBoxBytes(
  box: Box,
  identity: Identity,
  aad: Uint8Array,
): Promise<Uint8Array> {
  const epk = b64uDecode(box.epk);
  const nonce = b64uDecode(box.nonce);
  const ct = b64uDecode(box.ct);
  if (epk === null || nonce === null || ct === null) throw new BoxError("box does not open");
  if (epk.length !== KEY_BYTES || nonce.length !== NONCE_BYTES) {
    throw new BoxError("box does not open");
  }
  let shared: Uint8Array;
  try {
    shared = await identity.sharedSecret(epk);
  } catch {
    throw new BoxError("box does not open");
  }
  const key = await boxKey(shared, epk, identity.boxKeyBytes);
  const plaintext = chachaOpen(key, nonce, ct, aad);
  if (plaintext === null) throw new BoxError("box does not open");
  return plaintext;
}

/** Opens `box` to its JSON object; BoxError on any failure (like tau-net's `open_box`). */
export async function openBox(
  box: Box,
  identity: Identity,
  aad: Uint8Array,
): Promise<Record<string, unknown>> {
  const content = parseJsonBytes(await openBoxBytes(box, identity, aad));
  if (content === undefined) throw new BoxError("box content is not UTF-8 JSON");
  if (!isObject(content)) throw new BoxError("box content is not an object");
  return content;
}
