/**
 * Addresses (§1 of docs/reference/tau-network.md).
 *
 * Copied from cloud/spine/src/address.ts; keep the shared functions identical. The
 * universe names its own host with UNIVERSE where the spine uses ADDRESS.
 */

import type { UniverseEnv } from "./env";

export const ADDRESS_PATTERN =
  /^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*(:[0-9]{1,5})?$/;

export function isAddress(value: unknown): value is string {
  return typeof value === "string" && value.length <= 260 && ADDRESS_PATTERN.test(value);
}

/** The host of an address, without the port. */
export function hostOf(address: string): string {
  const colon = address.lastIndexOf(":");
  return colon === -1 ? address : address.slice(0, colon);
}

/** Whether the universe may talk plain http to localhost / 127.0.0.1 taus (development). */
export function insecurePeersAllowed(env: UniverseEnv): boolean {
  return env.ALLOW_INSECURE_PEERS === "1";
}

/**
 * `https://<address>`, or `http://<address>` for localhost and 127.0.0.1 when insecure
 * peers are allowed. No other host ever gets http.
 */
export function baseUrl(address: string, allowInsecure: boolean): string {
  const host = hostOf(address);
  const loopback = host === "localhost" || host === "127.0.0.1";
  return `${loopback && allowInsecure ? "http" : "https"}://${address}`;
}

/** The universe's own host: the UNIVERSE variable when set, else the request's host. */
export function universeHost(env: UniverseEnv, url: URL): string {
  const configured = (env.UNIVERSE ?? "").trim().toLowerCase();
  return configured !== "" ? configured : url.host.toLowerCase();
}
