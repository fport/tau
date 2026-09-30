/** base64url, random tokens and SHA-256 (WebCrypto only). */

export function b64uEncode(bytes: Uint8Array): string {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replaceAll("+", "-").replaceAll("/", "_").replace(/=+$/, "");
}

/** Strict base64url without padding, or null. */
export function b64uDecode(text: string): Uint8Array | null {
  if (!/^[A-Za-z0-9_-]*$/.test(text) || text.length % 4 === 1) return null;
  const padded = text.replaceAll("-", "+").replaceAll("_", "/") + "=".repeat((4 - (text.length % 4)) % 4);
  let binary: string;
  try {
    binary = atob(padded);
  } catch {
    return null;
  }
  const out = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) out[i] = binary.charCodeAt(i);
  // Canonical only: re-encoding gives the same text (no stray bits in the last character).
  return b64uEncode(out) === text ? out : null;
}

export function randomBytes(length: number): Uint8Array {
  const out = new Uint8Array(length);
  crypto.getRandomValues(out);
  return out;
}

/** A random token of `length` bytes, base64url. */
export function randomToken(length = 32): string {
  return b64uEncode(randomBytes(length));
}

export async function sha256(data: string | Uint8Array): Promise<Uint8Array> {
  const bytes = typeof data === "string" ? new TextEncoder().encode(data) : data;
  return new Uint8Array(await crypto.subtle.digest("SHA-256", bytes));
}

/** SHA-256 as base64url: how session tokens and visitor IPs are stored. */
export async function sha256b64u(data: string | Uint8Array): Promise<string> {
  return b64uEncode(await sha256(data));
}
