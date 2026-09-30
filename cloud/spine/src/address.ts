/**
 * Addresses (§1 of docs/reference/tau-network.md).
 *
 * An address is `host[:port]`, or `host[:port]/@handle` for a tau hosted under a path of its
 * host (ADR 0013, e.g. `tau.example.com/@alice`). A spine's own address is always a plain
 * host; senders may use either form, and a sender's card is at
 * `<scheme>://<address>/.well-known/tau.json` for both.
 */

import type { SpineEnv } from "./env";

const HOST =
  "[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*(:[0-9]{1,5})?";
const HANDLE = "[a-z0-9]([a-z0-9-]{0,37}[a-z0-9])?";

/** `host` or `host:port`. */
export const HOST_PATTERN = new RegExp(`^${HOST}$`);
/** A handle: the GitHub login rules in lower case. */
export const HANDLE_PATTERN = new RegExp(`^${HANDLE}$`);
/** `host[:port]` or `host[:port]/@handle`. */
export const ADDRESS_PATTERN = new RegExp(`^${HOST}(/@${HANDLE})?$`);

/** The longest address checked at all (a DNS name, a port and a handle fit well within). */
export const MAX_ADDRESS_CHARS = 320;

export function isAddress(value: unknown): value is string {
  return (
    typeof value === "string" && value.length <= MAX_ADDRESS_CHARS && ADDRESS_PATTERN.test(value)
  );
}

/** A plain host (`host[:port]`), never one with a handle. */
export function isHost(value: unknown): value is string {
  return typeof value === "string" && value.length <= MAX_ADDRESS_CHARS && HOST_PATTERN.test(value);
}

/** The host name of an address, without the port and without `/@handle`. */
export function hostOf(address: string): string {
  const slash = address.indexOf("/");
  const host = slash === -1 ? address : address.slice(0, slash);
  const colon = host.lastIndexOf(":");
  return colon === -1 ? host : host.slice(0, colon);
}

/** Whether this spine may talk plain http to localhost / 127.0.0.1 peers (development). */
export function insecurePeersAllowed(env: SpineEnv): boolean {
  return env.ALLOW_INSECURE_PEERS === "1";
}

/**
 * `https://<address>`, or `http://<address>` for localhost and 127.0.0.1 when insecure
 * peers are allowed. No other host ever gets http. A handle address keeps its path:
 * `https://tau.example.com/@alice`.
 */
export function baseUrl(address: string, allowInsecure: boolean): string {
  const host = hostOf(address);
  const loopback = host === "localhost" || host === "127.0.0.1";
  return `${loopback && allowInsecure ? "http" : "https"}://${address}`;
}

/** The spine's own address: the ADDRESS variable when set, else the request's host. */
export function ownAddress(env: SpineEnv, url: URL): string {
  const configured = (env.ADDRESS ?? "").trim().toLowerCase();
  return configured !== "" ? configured : url.host.toLowerCase();
}
