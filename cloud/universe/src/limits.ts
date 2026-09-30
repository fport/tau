/**
 * Flood guards: Workers Rate Limiting bindings (`ratelimits` in the Wrangler configuration),
 * adapted from cloud/spine/src/limits.ts (keep `clientKey` identical):
 *
 * - `CHAT_IP_LIMIT`: 10 visitor messages a minute per client IP (ADR 0013 §5);
 * - `INBOX_IP_LIMIT` and `INBOX_SENDER_LIMIT`: envelopes to the universe's inbox per client IP
 *   and per claimed sender, the spine's two limits.
 *
 * All fail open. A universe deployed from an older configuration has no binding, and a
 * binding that throws must not stop the site. Either case is logged once per isolate.
 */

import type { LimiterName, UniverseEnv } from "./env";

/** Log lines already written by this isolate (not request state: only "said it once"). */
const warned = new Set<string>();

/** Writes a structured warning once per isolate and event. */
export function warnOnce(event: string, fields: Record<string, unknown> = {}): void {
  if (warned.has(event)) return;
  warned.add(event);
  console.warn(JSON.stringify({ event, ...fields }));
}

/**
 * Whether `key` is still within the limit of the binding `name`; true when the binding is
 * missing or fails.
 */
export async function withinLimit(
  env: UniverseEnv,
  name: LimiterName,
  key: string,
): Promise<boolean> {
  const limiter = env[name];
  if (limiter === undefined) {
    warnOnce(`rate_limit_unbound:${name}`, {
      binding: name,
      detail: "no binding; the check is skipped",
    });
    return true;
  }
  try {
    const { success } = await limiter.limit({ key });
    return success;
  } catch (err) {
    warnOnce(`rate_limit_failed:${name}`, { binding: name, error: String(err) });
    return true;
  }
}

/**
 * The rate-limit key of a client address: an IPv4 address as it is, an IPv6 address by its
 * /64 prefix (one subscriber usually holds a whole /64), an IPv4-mapped IPv6 address as the
 * IPv4 address. Null for an empty or unparsable value.
 */
export function clientKey(ip: string | null): string | null {
  const address = (ip ?? "").trim().toLowerCase();
  if (address === "") return null;
  if (!address.includes(":")) return /^[0-9.]{7,15}$/.test(address) ? address : null;
  const mapped = /^::ffff:([0-9]{1,3}(?:\.[0-9]{1,3}){3})$/.exec(address);
  if (mapped?.[1] !== undefined) return mapped[1];
  const groups = expandIpv6(address);
  return groups === null ? null : `${groups.slice(0, 4).join(":")}::/64`;
}

/** The eight hextets of an IPv6 address without a zone, or null. */
function expandIpv6(address: string): string[] | null {
  const bare = address.split("%", 1)[0] ?? "";
  const halves = bare.split("::");
  if (halves.length > 2) return null;
  const part = (text: string | undefined): string[] =>
    text === undefined || text === "" ? [] : text.split(":");
  const head = part(halves[0]);
  const tail = part(halves[1]);
  const missing = 8 - head.length - tail.length;
  if (halves.length === 1 ? missing !== 0 : missing < 1) return null;
  const groups = [...head, ...Array<string>(halves.length === 1 ? 0 : missing).fill("0"), ...tail];
  if (!groups.every((g) => /^[0-9a-f]{1,4}$/.test(g))) return null;
  return groups.map((g) => g.replace(/^0+(?=.)/, ""));
}
