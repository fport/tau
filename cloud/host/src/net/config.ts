/**
 * Where a hosted tau lives on the tau network, and the limits it keeps (ADR 0013 §3, §4;
 * docs/reference/tau-network.md §4 and §6).
 *
 * **The address** of a hosted tau is `<net host>/@<handle>`. The net host is:
 *
 * 1. `PUBLIC_HOST` when it is set (a deployment: `tau.getporti.com`, or an own host's custom
 *    domain). On tau.getporti.com the universe is the front door and forwards
 *    `/@<handle>/.well-known/tau.json` and `/@<handle>/net/*` unchanged, so the request host
 *    is the public host as well; the variable only makes it independent of the request.
 * 2. Otherwise the host of the request (`tau-host.<subdomain>.workers.dev`, or
 *    `127.0.0.1:8791` under `wrangler dev`). The `Tau` object keeps the last one it saw, for
 *    the work it does without a request (the hourly universe report).
 *
 * A host that is not a valid address host (`[::1]`, upper case in PUBLIC_HOST aside, which is
 * lowered) leaves the tau off the network: its card and inbox answer 503 `not_configured`.
 *
 * **The universe** is `UNIVERSE` when that variable is set, "" switches it off, and a
 * deployment that leaves it out uses the net host itself: on tau.getporti.com the universe
 * and tau-host share the public host.
 */

import { isPlainAddress } from "../../../shared/net/index.ts";
import { type HostEnv, optionalEnv } from "../env";

export const SOFTWARE = "tau-host/0.1.0";

/** The longest a reply may travel: `hops + 1` above this is never sent (tau-net's default). */
export const MAX_HOPS = 6;
/** Auto-replies to one contact per hour (tau-net's `max_auto_replies_per_hour`). */
export const MAX_AUTO_REPLIES_PER_HOUR = 20;
/** Envelopes accepted from one sender in the last hour (the spine's `Mailbox` limit). */
export const INBOX_HOURLY_CAP = 60;
/** Envelopes waiting to be handled (the spine's mailbox cap). */
export const QUEUE_CAP = 1000;
/** How far an envelope's `ts` may be from the host's clock. */
export const CLOCK_SKEW_SECONDS = 300;
/** How long a fetched peer card is trusted without fetching it again (the spine's cache). */
export const CARD_CACHE_SECONDS = 3600;
/** How long `(from, id)` pairs are kept for the duplicate check (the spine's `seen`). */
export const SEEN_SECONDS = 86_400;
/** Network log entries kept (tau-net's log). */
export const LOG_LIMIT = 500;
/** Universe reports while joined (tau-net's default `universe_report_minutes`). */
export const REPORT_SECONDS = 3600;
/** A queued envelope not handled after this is handled again by the alarm. */
export const QUEUE_RETRY_SECONDS = 120;
/** How often one envelope is tried before it is dropped. */
export const QUEUE_TRIES = 3;
/** Sending: the recipient's inbox gets this long. */
export const SEND_TIMEOUT_MS = 15_000;
/** Universe requests get this long. */
export const UNIVERSE_TIMEOUT_MS = 10_000;

/** The host part of every hosted tau's address, or null when there is no valid one. */
export function netHost(env: HostEnv, requestHost?: string | null): string | null {
  const configured = (env.PUBLIC_HOST ?? "").trim().toLowerCase();
  const host = configured || (requestHost ?? "").trim().toLowerCase();
  return isPlainAddress(host) ? host : null;
}

/** Whether PUBLIC_HOST fixes the net host (the request host does not matter then). */
export function fixedNetHost(env: HostEnv): boolean {
  return (env.PUBLIC_HOST ?? "").trim() !== "";
}

/** `<host>/@<handle>` */
export function hostedAddress(host: string, handle: string): string {
  return `${host}/@${handle}`;
}

/**
 * The universe's host: `UNIVERSE`, or `host` when the variable is left out; null when it is
 * "" (off) or not a valid host.
 */
export function universeHost(env: HostEnv, host: string | null): string | null {
  const raw = optionalEnv(env).UNIVERSE;
  if (raw === undefined || raw === null) return host;
  const value = raw.trim().toLowerCase();
  if (value === "") return null;
  return isPlainAddress(value) ? value : null;
}

/** Plain http to localhost and 127.0.0.1 peers (development only). */
export function insecurePeers(env: HostEnv): boolean {
  return env.ALLOW_INSECURE_PEERS === "1";
}
