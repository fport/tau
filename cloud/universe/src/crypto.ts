/**
 * Base64url and Ed25519 verification, all on WebCrypto.
 *
 * Copied from cloud/spine/src/crypto.ts (the two Workers deploy independently); keep the
 * shared functions identical. Only the signature context differs: universe requests are
 * signed over `b"tau-universe/1\n" + payload_bytes`, so no signature is valid both as an
 * envelope and as a universe request.
 */

const B64U = /^[A-Za-z0-9_-]*={0,2}$/;

/** RFC 4648 §5 without padding. */
export function b64uEncode(bytes: Uint8Array): string {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

/** Decodes base64url with or without padding; null when the input is not valid base64url. */
export function b64uDecode(text: string): Uint8Array | null {
  if (!B64U.test(text)) return null;
  const bare = text.replace(/=+$/, "");
  if (bare.length % 4 === 1) return null;
  if (bare.length !== text.length && text.length % 4 !== 0) return null;
  const b64 = bare.replace(/-/g, "+").replace(/_/g, "/");
  let binary: string;
  try {
    binary = atob(b64 + "=".repeat((4 - (b64.length % 4)) % 4));
  } catch {
    return null;
  }
  const out = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) out[i] = binary.charCodeAt(i);
  return out;
}

/** A b64u string that decodes to exactly `length` bytes, or null. */
export function b64uKey(value: unknown, length = 32): Uint8Array | null {
  if (typeof value !== "string") return null;
  const bytes = b64uDecode(value);
  return bytes !== null && bytes.length === length ? bytes : null;
}

const encoder = new TextEncoder();

/** The domain separator every universe request signature starts with. */
export const SIGNATURE_CONTEXT = encoder.encode("tau-universe/1\n");

/** `b"tau-universe/1\n" + payload_bytes`: the exact bytes the tau signed. */
export function signedMessage(payload: Uint8Array): Uint8Array {
  const message = new Uint8Array(SIGNATURE_CONTEXT.length + payload.length);
  message.set(SIGNATURE_CONTEXT, 0);
  message.set(payload, SIGNATURE_CONTEXT.length);
  return message;
}

/** Verifies an Ed25519 signature; any malformed input is simply "does not verify". */
export async function verifyEd25519(
  publicKey: Uint8Array,
  signature: Uint8Array,
  message: Uint8Array,
): Promise<boolean> {
  if (publicKey.length !== 32 || signature.length !== 64) return false;
  try {
    const key = await crypto.subtle.importKey("raw", publicKey, { name: "Ed25519" }, false, [
      "verify",
    ]);
    return await crypto.subtle.verify({ name: "Ed25519" }, key, signature, message);
  } catch {
    return false;
  }
}
