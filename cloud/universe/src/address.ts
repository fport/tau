/**
 * Addresses (§1 of docs/reference/tau-network.md, widened by ADR 0013 §3).
 *
 * An address is `host[:port]`, or `host[:port]/@handle` for a tau hosted by tau-host. The
 * card is at `<scheme>://<address>/.well-known/tau.json`, so the longer form needs nothing
 * but the longer URL. The host rule is copied from cloud/spine/src/address.ts; keep the
 * shared functions identical. The universe names its own host with UNIVERSE where the spine
 * uses ADDRESS.
 */

import type { UniverseEnv } from "./env";

/** A handle: a GitHub login in lower case (ADR 0013 §3). */
export const HANDLE_PATTERN = /^[a-z0-9](?:[a-z0-9-]{0,37}[a-z0-9])?$/;

const HOST_PART =
  "[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*(:[0-9]{1,5})?";
const HANDLE_PART = "[a-z0-9](?:[a-z0-9-]{0,37}[a-z0-9])?";

export const ADDRESS_PATTERN = new RegExp(`^${HOST_PART}(/@${HANDLE_PART})?$`);

/** 260 for `host[:port]`, plus `/@` and a handle of at most 39 characters. */
export const MAX_ADDRESS_CHARS = 301;

export function isAddress(value: unknown): value is string {
  return (
    typeof value === "string" && value.length <= MAX_ADDRESS_CHARS && ADDRESS_PATTERN.test(value)
  );
}

export function isHandle(value: unknown): value is string {
  return typeof value === "string" && HANDLE_PATTERN.test(value);
}

/** `host[:port]` of an address: everything before `/@handle`. */
export function authorityOf(address: string): string {
  const slash = address.indexOf("/");
  return slash === -1 ? address : address.slice(0, slash);
}

/** The handle of a `host[:port]/@handle` address, or null for a plain one. */
export function handleOfAddress(address: string): string | null {
  const at = address.indexOf("/@");
  return at === -1 ? null : address.slice(at + 2);
}

/** The host of an address, without the port and the handle. */
export function hostOf(address: string): string {
  const authority = authorityOf(address);
  const colon = authority.lastIndexOf(":");
  return colon === -1 ? authority : authority.slice(0, colon);
}

/**
 * The handle of a tau hosted on this universe's own host (`<universe>/@<handle>`), or null.
 * Such a tau lives in tau-host behind the `HOST` binding, which proved the handle with a
 * GitHub sign-in, so it gets the handle without a claim.
 */
export function hostedHandle(address: string, universe: string): string | null {
  const handle = handleOfAddress(address);
  return handle !== null && authorityOf(address) === universe ? handle : null;
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
