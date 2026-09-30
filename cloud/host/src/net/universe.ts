/**
 * A hosted tau in the universe (ADR 0010, docs/reference/tau-universe.md §1 and §3): the
 * signed `join`, `report` and `leave` requests, as tau-net's `UniverseClient` sends them.
 *
 * - Requests are signed with the tau's own identity over `"tau-universe/1\n" + payload`
 *   (cloud/shared/net/universe.ts).
 * - `ts` never repeats and only grows per tau (the universe accepts only a `ts` above the last
 *   one it saw from an address). The last one is kept by the caller, and a `stale` answer is
 *   retried up to three times, each time further ahead (+2, +4, +8 s).
 * - A report lists only accepted contacts the universe lists (its snapshot is read first),
 *   with the messages exchanged, and the tau's public sub-taus.
 */

import {
  baseUrl,
  encodeRequest,
  type Identity,
  isAddress,
  isObject,
  type Link,
  makeRequestPayload,
  MAX_LINKS,
  MAX_REQUEST_BYTES,
  MAX_SUBS,
  type ReportedSub,
  signRequest,
  type UniverseKind,
} from "../../../shared/net/index.ts";
import { SOFTWARE, UNIVERSE_TIMEOUT_MS } from "./config";
import type { Fetcher } from "./transport";

export const STALE_RETRIES = 3;
export const SUB_ABOUT_LIMIT = 200;

/** A universe that answered with an error, or did not answer; `code` is its error code. */
export class UniverseError extends Error {
  constructor(
    readonly host: string,
    readonly status: number,
    readonly code: string,
    readonly detail = "",
  ) {
    super(`universe ${host}: ${status ? `${status} ` : ""}${code}${detail ? ` (${detail})` : ""}`);
    this.name = "UniverseError";
  }
}

export interface UniverseOptions {
  host: string;
  fetcher: Fetcher;
  allowInsecure: boolean;
  now: () => number;
  /** The last `ts` this tau used, and where the next one is kept. */
  lastTs: () => number;
  saveTs: (ts: number) => void;
}

type Answer = Record<string, unknown>;

export class UniverseClient {
  readonly base: string;

  constructor(private readonly options: UniverseOptions) {
    this.base = baseUrl(options.host, options.allowInsecure);
  }

  get host(): string {
    return this.options.host;
  }

  /** The universe page of `address`. */
  urlFor(address: string): string {
    return `${this.base}/universe#${address}`;
  }

  private nextTs(): number {
    const ts = Math.max(this.options.now(), this.options.lastTs() + 1);
    this.options.saveTs(ts);
    return ts;
  }

  private async exchange(method: string, path: string, body?: Uint8Array): Promise<{ status: number; data: Answer | null }> {
    const headers: Record<string, string> = { accept: "application/json", "user-agent": SOFTWARE };
    if (body !== undefined) headers["content-type"] = "application/json";
    let response: Response;
    try {
      response = await this.options.fetcher(`${this.base}${path}`, {
        method,
        headers,
        body,
        redirect: "manual",
        signal: AbortSignal.timeout(UNIVERSE_TIMEOUT_MS),
      });
    } catch (err) {
      throw new UniverseError(this.host, 0, "unreachable", err instanceof Error ? err.name : "");
    }
    let data: unknown = null;
    try {
      data = await response.json();
    } catch {
      data = null;
    }
    return { status: response.status, data: isObject(data) ? data : null };
  }

  private fail(status: number, data: Answer | null): never {
    if (data !== null && typeof data.error === "string") {
      const detail = typeof data.detail === "string" ? data.detail.slice(0, 200) : "";
      throw new UniverseError(this.host, status, data.error, detail);
    }
    throw new UniverseError(this.host, status, `http_${status}`);
  }

  /** Builds, signs and posts one request, with the next `ts` again after `stale`. */
  private async signed(
    identity: Identity,
    kind: UniverseKind,
    address: string,
    fields: { owner?: string; about?: string; links?: Link[]; subs?: ReportedSub[] } = {},
  ): Promise<Answer> {
    for (let attempt = 0; ; attempt++) {
      const payload = makeRequestPayload(kind, { universe: this.host, address, ts: this.nextTs(), ...fields });
      const body = encodeRequest(await signRequest(identity, payload));
      const { status, data } = await this.exchange("POST", `/api/${kind}`, body);
      if (status >= 200 && status < 300) {
        if (data === null) throw new UniverseError(this.host, status, "bad_json", "the answer is not JSON");
        return data;
      }
      if (data?.error !== "stale" || attempt === STALE_RETRIES) this.fail(status, data);
      this.options.saveTs(this.options.lastTs() + 2 ** attempt);
    }
  }

  join(identity: Identity, address: string, owner: string, about: string): Promise<Answer> {
    return this.signed(identity, "join", address, { owner, about });
  }

  /**
   * `POST /api/report`: `links` (at most 500, cut from the end until the body fits) and the
   * public sub-taus (at most 20).
   */
  async report(identity: Identity, address: string, links: Link[], subs: ReportedSub[]): Promise<Answer> {
    let kept = links.slice(0, MAX_LINKS);
    const listed = subs.slice(0, MAX_SUBS);
    while (kept.length > 0) {
      const payload = makeRequestPayload("report", { universe: this.host, address, ts: this.options.now(), links: kept, subs: listed });
      if (encodeRequest(await signRequest(identity, payload)).length <= MAX_REQUEST_BYTES) break;
      kept = kept.slice(0, Math.floor((kept.length * 9) / 10));
    }
    return this.signed(identity, "report", address, { links: kept, subs: listed });
  }

  leave(identity: Identity, address: string): Promise<Answer> {
    return this.signed(identity, "leave", address);
  }

  /** `GET /api/universe`: the public snapshot. */
  async snapshot(): Promise<Answer> {
    const { status, data } = await this.exchange("GET", "/api/universe");
    if (status !== 200 || data === null) this.fail(status, data);
    if (!Array.isArray(data.taus)) throw new UniverseError(this.host, 200, "bad_json", "the snapshot has no taus list");
    return data;
  }
}

/** The addresses of the taus in a snapshot. */
export function listedAddresses(snapshot: Answer): Set<string> {
  const taus = Array.isArray(snapshot.taus) ? snapshot.taus : [];
  const out = new Set<string>();
  for (const entry of taus) {
    if (isObject(entry) && isAddress(entry.address)) out.add(entry.address);
  }
  return out;
}

/**
 * The `links` of a report (tau-net's `select_links`): every accepted contact the universe
 * lists, with `messages` = in + out; ordered by messages (most first), then address.
 */
export function selectLinks(
  contacts: readonly string[],
  counts: ReadonlyMap<string, { in: number; out: number }>,
  listed: ReadonlySet<string>,
  own: string,
): Link[] {
  const links: Link[] = [];
  for (const peer of [...new Set(contacts)].sort()) {
    if (peer === own || !listed.has(peer)) continue;
    const count = counts.get(peer);
    links.push({ peer, messages: Math.max(0, count?.in ?? 0) + Math.max(0, count?.out ?? 0) });
  }
  links.sort((a, b) => b.messages - a.messages || (a.peer < b.peer ? -1 : a.peer > b.peer ? 1 : 0));
  return links.slice(0, MAX_LINKS);
}
