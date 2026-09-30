/**
 * Directory: the Durable Object that holds the universe (one instance, "universe").
 *
 * It keeps its own SQLite database:
 *
 *   taus     the joined taus (address, card name and sign_key, owner, about, times, the
 *            handle with the GitHub id that claimed it, and the public sub-taus of the last
 *            report as JSON)
 *   reports  the links each tau reported last, towards taus joined at that moment
 *   slugs    the short pages `/<name>`: each name belongs to the first tau that reported a
 *            public sub-tau with it, until that tau leaves or expires
 *   clocks   the last accepted `ts` per address (the replay guard; survives a leave)
 *   nonces   the nonces of accepted claims, for the claim window (their replay guard)
 *   hits     one row per accepted request (the rate limit)
 *
 * The Worker parses and verifies every request (size, shape, universe, clock window, card,
 * signature, and for a claim the GitHub account) before it calls join / report / leave /
 * claim. Those methods judge what needs the stored state, in the reference's order (not a
 * replay, joined, rate limit, and for a claim the handle rules), and apply the effect in the
 * same synchronous transaction, so two requests can never both pass the replay guard.
 *
 * Every time is passed in (`now`), so the object has no clock of its own.
 */

import { DurableObject } from "cloudflare:workers";
import { hostedHandle } from "./address";
import type { UniverseEnv } from "./env";
import { CLAIM_WINDOW_SECONDS, RESERVED_SUB_NAMES, type ReportedSub } from "./protocol";
import { isSlugCandidate } from "./routes";
import {
  buildSnapshot,
  personView,
  type PersonView,
  type PublicSub,
  type ReportRow,
  type Snapshot,
  subView,
  type SubView,
  type TauRow,
  tauView,
  type TauView,
} from "./snapshot";

export const RATE_LIMIT_PER_HOUR = 30;
export const RATE_WINDOW_SECONDS = 3_600;
export const TAU_RETENTION_SECONDS = 30 * 86_400;
/** Clocks older than this can go: the ±300 s window already refuses anything older. */
export const CLOCK_RETENTION_SECONDS = 3_600;

export const SCHEMA_VERSION = 3;

/** Version 1, kept as it shipped: a fresh database runs it, then every later step. */
export const SCHEMA_V1 = [
  `CREATE TABLE taus (
    address TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    sign_key TEXT NOT NULL,
    owner TEXT NOT NULL DEFAULT '',
    about TEXT NOT NULL DEFAULT '',
    joined_at INTEGER NOT NULL,
    last_seen INTEGER NOT NULL
  )`,
  "CREATE INDEX taus_last_seen ON taus (last_seen)",
  `CREATE TABLE reports (
    reporter TEXT NOT NULL,
    peer TEXT NOT NULL,
    messages INTEGER NOT NULL,
    PRIMARY KEY (reporter, peer)
  )`,
  "CREATE INDEX reports_peer ON reports (peer)",
  "CREATE TABLE clocks (address TEXT PRIMARY KEY, ts INTEGER NOT NULL)",
  "CREATE INDEX clocks_ts ON clocks (ts)",
  "CREATE TABLE hits (address TEXT NOT NULL, at INTEGER NOT NULL)",
  "CREATE INDEX hits_address_at ON hits (address, at)",
  "CREATE INDEX hits_at ON hits (at)",
];

/** v2: the public sub-taus of each tau's last report, `[{"name", "about"}]` as JSON. */
export const SCHEMA_V2 = ["ALTER TABLE taus ADD COLUMN subs TEXT NOT NULL DEFAULT '[]'"];

/**
 * v3 (ADR 0013 §6): a handle per tau (unique; the GitHub id that claimed it beside it), the
 * slugs, and the claim nonces. Each stored sub-tau gains `web`, `starters` and `first_seen`
 * (`upgradeSubsToV3`).
 */
export const SCHEMA_V3 = [
  "ALTER TABLE taus ADD COLUMN handle TEXT",
  "ALTER TABLE taus ADD COLUMN github_id TEXT",
  "CREATE UNIQUE INDEX taus_handle ON taus (handle)",
  `CREATE TABLE slugs (
    name TEXT PRIMARY KEY,
    address TEXT NOT NULL,
    claimed_at INTEGER NOT NULL
  )`,
  "CREATE INDEX slugs_address ON slugs (address)",
  `CREATE TABLE nonces (
    address TEXT NOT NULL,
    nonce TEXT NOT NULL,
    ts INTEGER NOT NULL,
    PRIMARY KEY (address, nonce)
  )`,
  "CREATE INDEX nonces_ts ON nonces (ts)",
];

const TAU_COLUMNS = "address, name, owner, about, joined_at, last_seen, handle, subs";

/** A `taus` row as stored: `subs` is JSON text. */
type StoredTau = Omit<TauRow, "subs" | "handle"> & { handle: string | null; subs: string };

/** A sub-tau as stored in the `subs` JSON; the slug lives in its own table. */
type StoredSub = Omit<PublicSub, "slug">;

/**
 * The stored JSON of `subs`, read defensively: anything unexpected counts as none, and a
 * field a v2 row lacks gets its default (`first_seen` falls back to `firstSeen`).
 */
function readSubs(text: string, firstSeen: number): StoredSub[] {
  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch {
    return [];
  }
  if (!Array.isArray(value)) return [];
  return value.flatMap((item: unknown): StoredSub[] => {
    if (typeof item !== "object" || item === null) return [];
    const sub = item as Record<string, unknown>;
    if (typeof sub.name !== "string" || typeof sub.about !== "string") return [];
    const starters = Array.isArray(sub.starters)
      ? sub.starters.filter((starter): starter is string => typeof starter === "string")
      : [];
    return [
      {
        name: sub.name,
        about: sub.about,
        web: sub.web === true,
        starters,
        first_seen: Number.isSafeInteger(sub.first_seen) ? (sub.first_seen as number) : firstSeen,
      },
    ];
  });
}

/** Why the Directory refused a request; the Worker maps it to the reference's status. */
export type Refusal =
  | "stale"
  | "not_joined"
  | "rate_limited"
  | "handle_taken"
  | "handle_mismatch";

export type Outcome<T extends object> = ({ ok: true } & T) | { ok: false; error: Refusal };

interface Signed {
  address: string;
  /** The payload's `ts`. */
  ts: number;
  /** The Worker's clock, Unix seconds. */
  now: number;
}

export interface JoinInput extends Signed {
  /** From the card. */
  name: string;
  sign_key: string;
  /** Already sanitised. */
  owner: string;
  about: string;
  /** The handle of an address hosted on the universe's own host (`hostedHandle`). */
  handle?: string | null;
}

export interface ReportInput extends Signed {
  name: string;
  sign_key: string;
  links: { peer: string; messages: number }[];
  /** Already normalised (`normalizeSubs`); absent means none. Replaces the stored list. */
  subs?: ReportedSub[];
  /** As in JoinInput. */
  handle?: string | null;
}

export type LeaveInput = Signed;

export interface ClaimInput extends Signed {
  /** The universe's own host, to recognise hosted addresses. */
  universe: string;
  nonce: string;
  /** The GitHub login (lower case) and id signed in on the claim page, from tau-host. */
  handle: string;
  github_id: string;
}

export interface Claimed {
  handle: string;
  /** The address the handle was taken from (same GitHub account), or null. */
  moved_from: string | null;
}

/** A sub-tau page: by its slug, or by its tau's handle and its name. */
export type SubRef = { slug: string } | { handle: string; name: string };

export interface Pruned {
  taus: number;
  reports: number;
  hits: number;
  clocks: number;
  nonces: number;
}

export class Directory extends DurableObject<UniverseEnv> {
  private readonly sql: SqlStorage;

  constructor(ctx: DurableObjectState, env: UniverseEnv) {
    super(ctx, env);
    this.sql = ctx.storage.sql;
    // Synchronous, so it finishes before the first request is delivered.
    this.migrate();
  }

  private migrate(): void {
    this.sql.exec("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)");
    const row = this.sql
      .exec<{ version: number }>("SELECT MAX(version) AS version FROM schema_version")
      .one();
    const current = row.version ?? 0;
    if (current >= SCHEMA_VERSION) return;
    this.ctx.storage.transactionSync(() => {
      if (current < 1) for (const statement of SCHEMA_V1) this.sql.exec(statement);
      if (current < 2) for (const statement of SCHEMA_V2) this.sql.exec(statement);
      if (current < 3) {
        for (const statement of SCHEMA_V3) this.sql.exec(statement);
        this.upgradeSubsToV3();
      }
      this.sql.exec("DELETE FROM schema_version");
      this.sql.exec("INSERT INTO schema_version (version) VALUES (?)", SCHEMA_VERSION);
    });
  }

  /**
   * Gives every stored sub-tau its v3 fields (not web, no starters, first seen at the tau's
   * last report), drops reserved names, and hands out slugs first come by `joined_at`, as
   * if every tau had reported in the order it joined.
   */
  private upgradeSubsToV3(): void {
    const rows = this.sql
      .exec<{ address: string; subs: string; last_seen: number }>(
        "SELECT address, subs, last_seen FROM taus ORDER BY joined_at, address",
      )
      .toArray();
    for (const row of rows) {
      const subs = readSubs(row.subs, row.last_seen).filter(
        (sub) => !RESERVED_SUB_NAMES.has(sub.name),
      );
      this.sql.exec(
        "UPDATE taus SET subs = ? WHERE address = ?",
        JSON.stringify(subs),
        row.address,
      );
      this.claimSlugs(row.address, subs, row.last_seen);
    }
  }

  /** The last accepted `ts` of an address, or null (the Worker's early stale check). */
  lastTs(address: string): number | null {
    const rows = this.sql
      .exec<{ ts: number }>("SELECT ts FROM clocks WHERE address = ?", address)
      .toArray();
    return rows[0]?.ts ?? null;
  }

  /** Whether a claim nonce of this address was accepted (the Worker's early stale check). */
  nonceUsed(address: string, nonce: string): boolean {
    return (
      this.sql
        .exec("SELECT 1 FROM nonces WHERE address = ? AND nonce = ?", address, nonce)
        .toArray().length > 0
    );
  }

  join(input: JoinInput): Outcome<object> {
    return this.accept(input, { joined: false }, () => {
      this.sql.exec(
        `INSERT INTO taus (address, name, sign_key, owner, about, joined_at, last_seen)
         VALUES (?, ?, ?, ?, ?, ?, ?)
         ON CONFLICT (address) DO UPDATE SET
           name = excluded.name, sign_key = excluded.sign_key, owner = excluded.owner,
           about = excluded.about, last_seen = excluded.last_seen`,
        input.address,
        input.name,
        input.sign_key,
        input.owner,
        input.about,
        input.ts,
        input.ts,
      );
      if (input.handle) this.bindHosted(input.address, input.handle);
      return { ok: true };
    });
  }

  report(input: ReportInput): Outcome<{ visible_links: number }> {
    return this.accept(input, { joined: true }, () => {
      const wanted = new Map<string, number>();
      for (const link of input.links) {
        if (link.peer !== input.address) wanted.set(link.peer, link.messages);
      }
      // Peers that are not joined are ignored: their names are never stored.
      const joinedPeers = new Set(
        this.sql
          .exec<{ address: string }>(
            "SELECT address FROM taus WHERE address IN (SELECT value FROM json_each(?))",
            JSON.stringify([...wanted.keys()]),
          )
          .toArray()
          .map((row) => row.address),
      );
      const existing = new Map(
        this.sql
          .exec<{ peer: string; messages: number }>(
            "SELECT peer, messages FROM reports WHERE reporter = ?",
            input.address,
          )
          .toArray()
          .map((row) => [row.peer, row.messages] as const),
      );
      // Write only what changed: a report usually repeats the last one with new counts.
      for (const peer of existing.keys()) {
        if (!joinedPeers.has(peer)) {
          this.sql.exec("DELETE FROM reports WHERE reporter = ? AND peer = ?", input.address, peer);
        }
      }
      for (const peer of joinedPeers) {
        const messages = wanted.get(peer) ?? 0;
        if (existing.get(peer) === messages) continue;
        this.sql.exec(
          `INSERT INTO reports (reporter, peer, messages) VALUES (?, ?, ?)
           ON CONFLICT (reporter, peer) DO UPDATE SET messages = excluded.messages`,
          input.address,
          peer,
          messages,
        );
      }
      const subs = this.withFirstSeen(input.address, input.subs ?? [], input.ts);
      this.sql.exec(
        "UPDATE taus SET name = ?, sign_key = ?, last_seen = ?, subs = ? WHERE address = ?",
        input.name,
        input.sign_key,
        input.ts,
        JSON.stringify(subs),
        input.address,
      );
      this.claimSlugs(input.address, subs, input.ts);
      if (input.handle) this.bindHosted(input.address, input.handle);
      return {
        ok: true,
        visible_links: this.view(input.address, input.now)?.links.length ?? 0,
      };
    });
  }

  leave(input: LeaveInput): Outcome<object> {
    return this.accept(input, { joined: true }, () => {
      this.forget([input.address]);
      return { ok: true };
    });
  }

  /**
   * Binds `handle` to the claiming tau (ADR 0013 §6). One handle maps to one address:
   *
   * - a handle held by another tau under the same GitHub id moves here;
   * - a handle held under another GitHub id, or by a tau hosted on this universe (whose
   *   address is the handle), is refused with `handle_taken`;
   * - a hosted tau can only claim its own handle (`handle_mismatch` otherwise);
   * - the claiming tau's earlier handle, if any, is released.
   */
  claim(input: ClaimInput): Outcome<Claimed> {
    return this.accept(input, { joined: true, nonce: input.nonce }, (): Outcome<Claimed> => {
      const own = hostedHandle(input.address, input.universe);
      if (own !== null && own !== input.handle) return { ok: false, error: "handle_mismatch" };
      const holder = this.sql
        .exec<{ address: string; github_id: string | null }>(
          "SELECT address, github_id FROM taus WHERE handle = ?",
          input.handle,
        )
        .toArray()[0];
      let movedFrom: string | null = null;
      if (holder !== undefined) {
        const otherAccount = holder.github_id !== null && holder.github_id !== input.github_id;
        if (otherAccount) return { ok: false, error: "handle_taken" };
        if (holder.address !== input.address) {
          const hosted = hostedHandle(holder.address, input.universe) === input.handle;
          if (hosted || holder.github_id === null) return { ok: false, error: "handle_taken" };
          this.sql.exec(
            "UPDATE taus SET handle = NULL, github_id = NULL WHERE address = ?",
            holder.address,
          );
          movedFrom = holder.address;
        }
      }
      this.sql.exec(
        "UPDATE taus SET handle = ?, github_id = ? WHERE address = ?",
        input.handle,
        input.github_id,
        input.address,
      );
      return { ok: true, handle: input.handle, moved_from: movedFrom };
    });
  }

  /** The public snapshot. */
  snapshot(universe: string, now: number): Snapshot {
    const taus = this.loadTaus("1 = 1");
    const reports = this.sql
      .exec<ReportRow>("SELECT reporter, peer, messages FROM reports")
      .toArray();
    return buildSnapshot(universe, now, taus, reports);
  }

  /** One tau with its visible links, or null when it is not joined. */
  tau(address: string, now: number): TauView | null {
    return this.view(address, now);
  }

  /** The person page of a handle, or null when no joined tau has it. */
  person(handle: string, universe: string, now: number): PersonView | null {
    const address = this.addressOfHandle(handle);
    if (address === null) return null;
    const snapshot = this.neighbourhood(address, now, universe);
    return personView(snapshot, address, hostedHandle(address, universe) !== null);
  }

  /** A sub-tau page, or null when the slug or handle is unknown or the tau lists no such sub. */
  sub(ref: SubRef, universe: string, now: number): SubView | null {
    const found = this.findSub(ref);
    if (found === null) return null;
    const [tau] = buildSnapshot(universe, now, [found.row], []).taus;
    const hosted = hostedHandle(found.row.address, universe) !== null;
    return tau === undefined ? null : subView(universe, tau, found.name, hosted);
  }

  /** Whether a person page (`{handle}`) or a sub-tau page exists, for the page routes. */
  pageExists(ref: { handle: string } | SubRef): boolean {
    if ("slug" in ref || "name" in ref) return this.findSub(ref) !== null;
    return this.addressOfHandle(ref.handle) !== null;
  }

  /** The hourly cron: taus silent for 30 days, old rate-limit rows, clocks and nonces. */
  prune(now: number): Pruned {
    return this.ctx.storage.transactionSync(() => {
      const expired = this.sql
        .exec<{ address: string }>(
          "DELETE FROM taus WHERE last_seen < ? RETURNING address",
          now - TAU_RETENTION_SECONDS,
        )
        .toArray()
        .map((row) => row.address);
      const reports = this.forget(expired);
      const hits = this.sql
        .exec("DELETE FROM hits WHERE at < ? RETURNING at", now - RATE_WINDOW_SECONDS)
        .toArray().length;
      const clocks = this.sql
        .exec("DELETE FROM clocks WHERE ts < ? RETURNING ts", now - CLOCK_RETENTION_SECONDS)
        .toArray().length;
      const nonces = this.sql
        .exec("DELETE FROM nonces WHERE ts < ? RETURNING ts", now - CLAIM_WINDOW_SECONDS)
        .toArray().length;
      return { taus: expired.length, reports, hits, clocks, nonces };
    });
  }

  /**
   * The checks that need stored state, in the reference's order, then the effect; all in
   * one transaction. The replay guard is the address's last `ts`, or for a claim its nonce
   * (a claim may be up to an hour old, older than the tau's last report). The effect may
   * still refuse (the handle rules) before it writes. A refusal writes nothing.
   */
  private accept<T extends object>(
    input: Signed,
    rules: { joined: boolean; nonce?: string },
    effect: () => Outcome<T>,
  ): Outcome<T> {
    return this.ctx.storage.transactionSync((): Outcome<T> => {
      if (rules.nonce === undefined) {
        const last = this.lastTs(input.address);
        if (last !== null && input.ts <= last) return { ok: false, error: "stale" };
      } else if (this.nonceUsed(input.address, rules.nonce)) {
        return { ok: false, error: "stale" };
      }
      if (rules.joined && !this.isJoined(input.address)) return { ok: false, error: "not_joined" };
      const recent = this.sql
        .exec<{ n: number }>(
          "SELECT COUNT(*) AS n FROM hits WHERE address = ? AND at > ?",
          input.address,
          input.now - RATE_WINDOW_SECONDS,
        )
        .one().n;
      if (recent >= RATE_LIMIT_PER_HOUR) return { ok: false, error: "rate_limited" };
      const outcome = effect();
      if (!outcome.ok) return outcome;
      if (rules.nonce === undefined) {
        this.sql.exec(
          `INSERT INTO clocks (address, ts) VALUES (?, ?)
           ON CONFLICT (address) DO UPDATE SET ts = excluded.ts`,
          input.address,
          input.ts,
        );
      } else {
        this.sql.exec(
          "INSERT INTO nonces (address, nonce, ts) VALUES (?, ?, ?)",
          input.address,
          rules.nonce,
          input.ts,
        );
      }
      this.sql.exec("INSERT INTO hits (address, at) VALUES (?, ?)", input.address, input.now);
      return outcome;
    });
  }

  private isJoined(address: string): boolean {
    return this.sql.exec("SELECT 1 FROM taus WHERE address = ?", address).toArray().length > 0;
  }

  private addressOfHandle(handle: string): string | null {
    const rows = this.sql
      .exec<{ address: string }>("SELECT address FROM taus WHERE handle = ?", handle)
      .toArray();
    return rows[0]?.address ?? null;
  }

  /**
   * A tau hosted on the universe's own host has the handle of its address: tau-host proved
   * it with a GitHub sign-in. It takes the handle from any other tau.
   */
  private bindHosted(address: string, handle: string): void {
    this.sql.exec(
      "UPDATE taus SET handle = NULL, github_id = NULL WHERE handle = ? AND address != ?",
      handle,
      address,
    );
    this.sql.exec("UPDATE taus SET handle = ? WHERE address = ?", handle, address);
  }

  /** The reported sub-taus with `first_seen` kept from the stored list, or `ts` when new. */
  private withFirstSeen(address: string, subs: readonly ReportedSub[], ts: number): StoredSub[] {
    const row = this.sql
      .exec<{ subs: string; last_seen: number }>(
        "SELECT subs, last_seen FROM taus WHERE address = ?",
        address,
      )
      .toArray()[0];
    const before = new Map(
      (row === undefined ? [] : readSubs(row.subs, row.last_seen)).map((sub) => [
        sub.name,
        sub.first_seen,
      ]),
    );
    return subs.map((sub) => ({
      name: sub.name,
      about: sub.about,
      web: sub.web,
      starters: sub.starters,
      first_seen: before.get(sub.name) ?? ts,
    }));
  }

  /** First come: each free, unreserved name of `subs` becomes this tau's slug. */
  private claimSlugs(address: string, subs: readonly StoredSub[], at: number): void {
    for (const sub of subs) {
      if (!isSlugCandidate(sub.name)) continue;
      this.sql.exec(
        `INSERT INTO slugs (name, address, claimed_at) VALUES (?, ?, ?)
         ON CONFLICT (name) DO NOTHING`,
        sub.name,
        address,
        at,
      );
    }
  }

  /** Rows of `taus` matching `where`, with their sub-taus' slugs. */
  private loadTaus(where: string, ...params: SqlStorageValue[]): TauRow[] {
    const stored = this.sql
      .exec<StoredTau>(`SELECT ${TAU_COLUMNS} FROM taus WHERE ${where}`, ...params)
      .toArray();
    if (stored.length === 0) return [];
    const slugs = new Set(
      this.sql
        .exec<{ name: string; address: string }>(
          "SELECT name, address FROM slugs WHERE address IN (SELECT value FROM json_each(?))",
          JSON.stringify(stored.map((row) => row.address)),
        )
        .toArray()
        .map((row) => `${row.address}\n${row.name}`),
    );
    return stored.map((row) => ({
      ...row,
      subs: readSubs(row.subs, row.last_seen).map((sub) => ({
        ...sub,
        slug: slugs.has(`${row.address}\n${sub.name}`) ? sub.name : null,
      })),
    }));
  }

  /** The tau of a sub-tau page and the sub-tau's name, when the tau lists it. */
  private findSub(ref: SubRef): { row: TauRow; name: string } | null {
    let rows: TauRow[];
    let name: string;
    if ("slug" in ref) {
      name = ref.slug;
      rows = this.loadTaus("address = (SELECT address FROM slugs WHERE name = ?)", ref.slug);
    } else {
      name = ref.name;
      rows = this.loadTaus("handle = ?", ref.handle);
    }
    const row = rows[0];
    if (row === undefined || !(row.subs ?? []).some((sub) => sub.name === name)) return null;
    return { row, name };
  }

  /**
   * Deletes taus, the links they reported and their slugs; returns the reports deleted.
   * Other taus' reports about them stay: a link needs both ends joined, so it simply stops
   * being mutual, and each reporter's next report drops the peer (only joined peers are
   * kept). A handle goes with its tau's row.
   */
  private forget(addresses: string[]): number {
    if (addresses.length === 0) return 0;
    const list = JSON.stringify(addresses);
    this.sql.exec("DELETE FROM taus WHERE address IN (SELECT value FROM json_each(?))", list);
    this.sql.exec("DELETE FROM slugs WHERE address IN (SELECT value FROM json_each(?))", list);
    return this.sql
      .exec(
        `DELETE FROM reports WHERE reporter IN (SELECT value FROM json_each(?))
         RETURNING reporter`,
        list,
      )
      .toArray().length;
  }

  /**
   * The rows from and about a tau, and the taus on both ends, through the same snapshot
   * rule as the whole universe.
   */
  private neighbourhood(address: string, now: number, universe = ""): Snapshot {
    const reports = this.sql
      .exec<ReportRow>(
        "SELECT reporter, peer, messages FROM reports WHERE reporter = ? OR peer = ?",
        address,
        address,
      )
      .toArray();
    const ends = new Set([address]);
    for (const report of reports) {
      ends.add(report.reporter);
      ends.add(report.peer);
    }
    const taus = this.loadTaus(
      "address IN (SELECT value FROM json_each(?))",
      JSON.stringify([...ends]),
    );
    return buildSnapshot(universe, now, taus, reports);
  }

  /** A tau and its visible links. */
  private view(address: string, now: number): TauView | null {
    return tauView(this.neighbourhood(address, now), address);
  }
}
