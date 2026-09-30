/**
 * The vault: provider keys (and, from issue 162, network private keys) sealed at rest.
 *
 * ADR 0013 §2: AES-256-GCM under a key derived by HKDF-SHA256 from the Worker secret
 * `VAULT_KEY` (32 bytes, base64url) with `info = "tau-host/1 vault|<handle>"` and an empty
 * salt. Every tau has its own key, so a sealed value copied into another tau cannot be
 * opened there. The purpose of the value (`provider_key`, ...) is the additional data, so a
 * value cannot be moved to another slot of the same tau either.
 *
 * A sealed value is `v1.<base64url(iv || ciphertext || tag)>` with a random 12-byte IV.
 * Nothing here logs: the caller decides what may be said about a failure.
 */

import { b64uDecode, b64uEncode, randomBytes } from "./crypto";

export const VAULT_INFO_PREFIX = "tau-host/1 vault|";
const VERSION = "v1.";
const IV_BYTES = 12;

export class VaultError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "VaultError";
  }
}

/** The 32-byte master key from the secret, or a VaultError that says what is wrong. */
export function masterKey(secret: string | undefined): Uint8Array {
  if (!secret) throw new VaultError("VAULT_KEY is not set");
  const bytes = b64uDecode(secret.trim());
  if (bytes === null || bytes.length !== 32) {
    throw new VaultError("VAULT_KEY must be 32 bytes, base64url without padding");
  }
  return bytes;
}

/** The AES-256-GCM key of one tau. */
export async function tauKey(secret: string | undefined, handle: string): Promise<CryptoKey> {
  const ikm = await crypto.subtle.importKey("raw", masterKey(secret), "HKDF", false, [
    "deriveKey",
  ]);
  return crypto.subtle.deriveKey(
    {
      name: "HKDF",
      hash: "SHA-256",
      salt: new Uint8Array(0),
      info: new TextEncoder().encode(VAULT_INFO_PREFIX + handle),
    },
    ikm,
    { name: "AES-GCM", length: 256 },
    false,
    ["encrypt", "decrypt"],
  );
}

export async function seal(
  secret: string | undefined,
  handle: string,
  purpose: string,
  plaintext: string,
): Promise<string> {
  const key = await tauKey(secret, handle);
  const iv = randomBytes(IV_BYTES);
  const sealed = new Uint8Array(
    await crypto.subtle.encrypt(
      { name: "AES-GCM", iv, additionalData: new TextEncoder().encode(purpose) },
      key,
      new TextEncoder().encode(plaintext),
    ),
  );
  const out = new Uint8Array(IV_BYTES + sealed.length);
  out.set(iv, 0);
  out.set(sealed, IV_BYTES);
  return VERSION + b64uEncode(out);
}

export async function open(
  secret: string | undefined,
  handle: string,
  purpose: string,
  value: string,
): Promise<string> {
  if (!value.startsWith(VERSION)) throw new VaultError("not a sealed value");
  const bytes = b64uDecode(value.slice(VERSION.length));
  if (bytes === null || bytes.length < IV_BYTES + 16) throw new VaultError("not a sealed value");
  const key = await tauKey(secret, handle);
  try {
    const plain = await crypto.subtle.decrypt(
      {
        name: "AES-GCM",
        iv: bytes.slice(0, IV_BYTES),
        additionalData: new TextEncoder().encode(purpose),
      },
      key,
      bytes.slice(IV_BYTES),
    );
    return new TextDecoder().decode(plain);
  } catch {
    throw new VaultError("the sealed value cannot be opened with this VAULT_KEY");
  }
}
