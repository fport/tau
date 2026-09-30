/**
 * The inbox's flood guards: two Workers Rate Limiting bindings, as in the spine
 * (docs/reference/tau-network.md §4): one keyed by the client IP, one by the claimed sender
 * and the hosted tau it writes to. Both fail open: a configuration without the binding, or a
 * binding that throws, skips the check and says so once per isolate. The `Tau` object's own
 * hourly per-sender cap and its queue cap still hold.
 */

import { type HostEnv, optionalEnv } from "../env";

export type LimiterName = "INBOX_IP_LIMIT" | "INBOX_SENDER_LIMIT";

/** Log lines already written by this isolate (not request state: only "said it once"). */
const warned = new Set<string>();

export function warnOnce(event: string, fields: Record<string, unknown> = {}): void {
  if (warned.has(event)) return;
  warned.add(event);
  console.warn(JSON.stringify({ event, ...fields }));
}

/** Whether `key` is within the binding's limit; true when the binding is missing or fails. */
export async function withinLimit(env: HostEnv, name: LimiterName, key: string): Promise<boolean> {
  const limiter = optionalEnv(env)[name];
  if (limiter === undefined) {
    warnOnce("rate_limit_unbound", { binding: name, detail: "no binding; the check is skipped" });
    return true;
  }
  try {
    const { success } = await limiter.limit({ key });
    return success;
  } catch (err) {
    warnOnce("rate_limit_failed", { binding: name, error: err instanceof Error ? err.name : "error" });
    return true;
  }
}

/**
 * The rate-limit key of a client address: an IPv4 address as it is, an IPv6 address by its
 * /64 prefix, an IPv4-mapped IPv6 address as the IPv4 address. Null for an empty or
 * unparsable value (the spine's `clientKey`).
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

function expandIpv6(address: string): string[] | null {
  const bare = address.split("%", 1)[0] ?? "";
  const halves = bare.split("::");
  if (halves.length > 2) return null;
  const part = (text: string | undefined): string[] => (text === undefined || text === "" ? [] : text.split(":"));
  const head = part(halves[0]);
  const tail = part(halves[1]);
  const missing = 8 - head.length - tail.length;
  if (halves.length === 1 ? missing !== 0 : missing < 1) return null;
  const groups = [...head, ...Array<string>(halves.length === 1 ? 0 : missing).fill("0"), ...tail];
  if (!groups.every((g) => /^[0-9a-f]{1,4}$/.test(g))) return null;
  return groups.map((g) => g.replace(/^0+(?=.)/, ""));
}
