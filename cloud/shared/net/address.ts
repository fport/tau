/**
 * Addresses, the scheme rule and sub-tau targets (§1 of docs/reference/tau-network.md, widened
 * by ADR 0013 §3).
 *
 * - An **address** is `host[:port]`, lower case, **or** `host[:port]/@handle`, where a handle
 *   is a GitHub login in lower case (`^[a-z0-9](?:[a-z0-9-]{0,37}[a-z0-9])?$`). Hosted taus
 *   have addresses like `tau.example.com/@alice`; a hub and a spine keep a plain host.
 * - The **scheme** is `https` for every host. Only while developing, when insecure peers are
 *   allowed, `localhost` and `127.0.0.1` use `http`.
 * - The card is at `<scheme>://<address>/.well-known/tau.json` and the inbox at
 *   `<scheme>://<address>/net/inbox`, for both forms.
 * - A **sub-tau** is reached as `<address>/<name>`. Names never start with `@`, so the target
 *   parses unambiguously with both address forms, and the names of RESERVED_SUB_NAMES are
 *   never sub-tau names.
 */

/** A plain address: `host` or `host:port` (the grammar of protocol v1 before ADR 0013). */
export const HOST_PATTERN =
  /^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*(:[0-9]{1,5})?$/;

/** A handle: a GitHub login in lower case. */
export const HANDLE_PATTERN = /^[a-z0-9](?:[a-z0-9-]{0,37}[a-z0-9])?$/;

/** A sub-tau name (ADR 0012). */
export const SUB_NAME_PATTERN = /^[a-z][a-z0-9-]{1,30}$/;

/** Envelope ids (and claim nonces). */
export const ID_PATTERN = /^[A-Za-z0-9_-]{16,64}$/;

/** Names a sub-tau can never have: they are paths of tau-host and the spine (ADR 0013 §3). */
export const RESERVED_SUB_NAMES: readonly string[] = ["net", "app", "api", "auth", "claim", "hub"];

/** The only hosts that may use `http`, and only when insecure peers are allowed. */
export const INSECURE_HOSTS: readonly string[] = ["localhost", "127.0.0.1"];

/** The longest `host[:port]` part accepted (the spine's limit, far above any real host). */
export const MAX_HOST_CHARS = 260;

export const CARD_PATH = "/.well-known/tau.json";
export const INBOX_PATH = "/net/inbox";

/** Text that is not a tau address, where a function cannot answer with null. */
export class AddressError extends Error {
  override name = "AddressError";
}

/** The pieces of a valid address. */
export interface AddressParts {
  /** The whole address, unchanged. */
  address: string;
  /** `host[:port]`: a hub's or spine's address, or the host a hosted tau lives on. */
  host: string;
  /** The host name without the port. */
  hostname: string;
  /** The port, or null when the address has none. */
  port: number | null;
  /** The handle of a `host/@handle` address, or null for a plain address. */
  handle: string | null;
}

/** The pieces of `value` when it is a valid address of either form, otherwise null. */
export function addressParts(value: unknown): AddressParts | null {
  if (typeof value !== "string") return null;
  const slash = value.indexOf("/");
  const host = slash === -1 ? value : value.slice(0, slash);
  if (host.length > MAX_HOST_CHARS || !HOST_PATTERN.test(host)) return null;
  let handle: string | null = null;
  if (slash !== -1) {
    const rest = value.slice(slash + 1);
    if (!rest.startsWith("@") || !HANDLE_PATTERN.test(rest.slice(1))) return null;
    handle = rest.slice(1);
  }
  const colon = host.lastIndexOf(":");
  return {
    address: value,
    host,
    hostname: colon === -1 ? host : host.slice(0, colon),
    port: colon === -1 ? null : Number(host.slice(colon + 1)),
    handle,
  };
}

/** Whether `value` is an address of either form: `host[:port]` or `host[:port]/@handle`. */
export function isAddress(value: unknown): value is string {
  return addressParts(value) !== null;
}

/** Whether `value` is a plain `host[:port]` address (a hub's, a spine's, the universe's). */
export function isPlainAddress(value: unknown): value is string {
  return typeof value === "string" && value.length <= MAX_HOST_CHARS && HOST_PATTERN.test(value);
}

export function isHandle(value: unknown): value is string {
  return typeof value === "string" && HANDLE_PATTERN.test(value);
}

/** Whether `value` matches the sub-tau name pattern (reserved names included, as on the wire). */
export function isSubName(value: unknown): value is string {
  return typeof value === "string" && SUB_NAME_PATTERN.test(value);
}

export function isReservedSubName(value: string): boolean {
  return RESERVED_SUB_NAMES.includes(value);
}

export function isId(value: unknown): value is string {
  return typeof value === "string" && ID_PATTERN.test(value);
}

/** The host name of an address, without the port and the handle. */
export function hostOf(address: string): string {
  const parts = addressParts(address);
  if (parts === null) throw new AddressError(`not a tau address: ${JSON.stringify(address)}`);
  return parts.hostname;
}

/**
 * `https://<address>`, or `http://<address>` for `localhost` and `127.0.0.1` when insecure
 * peers are allowed. No other host ever gets `http`. AddressError for anything that is not an
 * address, so no URL is ever built from arbitrary text.
 */
export function baseUrl(address: string, allowInsecure = false): string {
  const parts = addressParts(address);
  if (parts === null) throw new AddressError(`not a tau address: ${JSON.stringify(address)}`);
  const insecure = allowInsecure && INSECURE_HOSTS.includes(parts.hostname);
  return `${insecure ? "http" : "https"}://${address}`;
}

/** `<scheme>://<address>/.well-known/tau.json` */
export function cardUrl(address: string, allowInsecure = false): string {
  return baseUrl(address, allowInsecure) + CARD_PATH;
}

/** `<scheme>://<address>/net/inbox` */
export function inboxUrl(address: string, allowInsecure = false): string {
  return baseUrl(address, allowInsecure) + INBOX_PATH;
}

function stripScheme(text: string): string {
  const lower = text.toLowerCase();
  for (const prefix of ["https://", "http://"]) {
    if (lower.startsWith(prefix)) return text.slice(prefix.length);
  }
  return text;
}

/**
 * An address typed by a person: surrounding space, upper case, a leading `https://` or
 * `http://` and trailing slashes are forgiven (like tau-net's `parse_address`). The address,
 * or null when what is left is not one.
 */
export function parseAddress(text: string): string | null {
  const value = stripScheme(text.trim().toLowerCase()).replace(/\/+$/, "");
  return isAddress(value) ? value : null;
}

/** An address and, when the target names one, a sub-tau of the tau at that address. */
export interface Target {
  address: string;
  sub: string | null;
}

/**
 * A target typed by a person: `<address>` or `<address>/<name>`, with either address form
 * (`tau.example.com/coach`, `tau.example.com/@alice`, `tau.example.com/@alice/coach`). The
 * address part is forgiven like parseAddress; the name must be a sub-tau name that is not
 * reserved. Null otherwise.
 */
export function parseTarget(text: string): Target | null {
  const value = stripScheme(text.trim()).replace(/\/+$/, "");
  const parts = value.split("/");
  const host = parts[0] ?? "";
  let addressText = host;
  let sub: string | undefined;
  if (parts.length === 1) {
    sub = undefined;
  } else if ((parts[1] ?? "").startsWith("@")) {
    addressText = `${host}/${parts[1]}`;
    if (parts.length > 3) return null;
    sub = parts[2];
  } else {
    if (parts.length > 2) return null;
    sub = parts[1];
  }
  const address = parseAddress(addressText);
  if (address === null) return null;
  if (sub === undefined) return { address, sub: null };
  const name = sub.trim().toLowerCase();
  if (!isSubName(name) || isReservedSubName(name)) return null;
  return { address, sub: name };
}

/** `<address>` or `<address>/<name>`: how a person writes a target. */
export function formatTarget(target: Target): string {
  return target.sub === null ? target.address : `${target.address}/${target.sub}`;
}
