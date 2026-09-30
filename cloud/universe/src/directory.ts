/**
 * Directory: the Durable Object that holds the universe (one instance, "universe").
 *
 * It keeps its own SQLite database:
 *
 *   taus     the joined taus (address, card name and sign_key, owner, about, times)
 *   reports  the links each tau reported last, towards taus joined at that moment
 *   clocks   the last accepted `ts` per address (the replay guard; survives a leave)
 *   hits     one row per accepted request (the rate limit)
 *
 * The Worker parses and verifies every request (size, shape, universe, clock window, card,
 * signature) before it calls join / report / leave. Those methods judge what needs the
 * stored state, in the reference's order (`ts` still newer than the last accepted one,
 * joined, rate limit), and apply the effect in the same synchronous transaction, so two
 * requests can never both pass the replay guard.
 *
 * Every time is passed in (`now`), so the object has no clock of its own.
 */

import { DurableObject } from "cloudflare:workers";
import type { UniverseEnv } from "./env";
import {
  buildSnapshot,
  type ReportRow,
  type Snapshot,
  type TauRow,
  tauView,
  type TauView,
} from "./snapshot";

export const RATE_LIMIT_PER_HOUR = 30;
export const RATE_WINDOW_SECONDS = 3_600;
export const TAU_RETENTION_SECONDS = 30 * 86_400;
/** Clocks older than this can go: the ±300 s window already refuses anything older. */
export const CLOCK_RETENTION_SECONDS = 3_600;

const SCHEMA_VERSION = 1;

const SCHEMA_V1 = [
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

/** Why the Directory refused a request; the Worker maps it to the reference's status. */
export type Refusal = "stale" | "not_joined" | "rate_limited";

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
}

export interface ReportInput extends Signed {
  name: string;
  sign_key: string;
  links: { peer: string; messages: number }[];
}

export type LeaveInput = Signed;

export interface Pruned {
  taus: number;
  reports: number;
  hits: number;
  clocks: number;
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
      this.sql.exec("DELETE FROM schema_version");
      this.sql.exec("INSERT INTO schema_version (version) VALUES (?)", SCHEMA_VERSION);
    });
  }

  /** The last accepted `ts` of an address, or null (the Worker's early stale check). */
  lastTs(address: string): number | null {
    const rows = this.sql
      .exec<{ ts: number }>("SELECT ts FROM clocks WHERE address = ?", address)
      .toArray();
    return rows[0]?.ts ?? null;
  }

  join(input: JoinInput): Outcome<object> {
    return this.accept(input, false, () => {
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
      return {};
    });
  }

  report(input: ReportInput): Outcome<{ visible_links: number }> {
    return this.accept(input, true, () => {
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
      this.sql.exec(
        "UPDATE taus SET name = ?, sign_key = ?, last_seen = ? WHERE address = ?",
        input.name,
        input.sign_key,
        input.ts,
        input.address,
      );
      return { visible_links: this.view(input.address, input.now)?.links.length ?? 0 };
    });
  }

  leave(input: LeaveInput): Outcome<object> {
    return this.accept(input, true, () => {
      this.forget([input.address]);
      return {};
    });
  }

  /** The public snapshot. */
  snapshot(universe: string, now: number): Snapshot {
    const taus = this.sql
      .exec<TauRow>("SELECT address, name, owner, about, joined_at, last_seen FROM taus")
      .toArray();
    const reports = this.sql
      .exec<ReportRow>("SELECT reporter, peer, messages FROM reports")
      .toArray();
    return buildSnapshot(universe, now, taus, reports);
  }

  /** One tau with its visible links, or null when it is not joined. */
  tau(address: string, now: number): TauView | null {
    return this.view(address, now);
  }

  /** The hourly cron: taus silent for 30 days, old rate-limit rows and old clocks. */
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
      return { taus: expired.length, reports, hits, clocks };
    });
  }

  /**
   * The checks that need stored state, in the reference's order, then the effect; all in
   * one transaction. A refusal writes nothing.
   */
  private accept<T extends object>(
    input: Signed,
    mustBeJoined: boolean,
    effect: () => T,
  ): Outcome<T> {
    return this.ctx.storage.transactionSync((): Outcome<T> => {
      const last = this.lastTs(input.address);
      if (last !== null && input.ts <= last) return { ok: false, error: "stale" };
      if (mustBeJoined && !this.isJoined(input.address)) return { ok: false, error: "not_joined" };
      const recent = this.sql
        .exec<{ n: number }>(
          "SELECT COUNT(*) AS n FROM hits WHERE address = ? AND at > ?",
          input.address,
          input.now - RATE_WINDOW_SECONDS,
        )
        .one().n;
      if (recent >= RATE_LIMIT_PER_HOUR) return { ok: false, error: "rate_limited" };
      this.sql.exec(
        `INSERT INTO clocks (address, ts) VALUES (?, ?)
         ON CONFLICT (address) DO UPDATE SET ts = excluded.ts`,
        input.address,
        input.ts,
      );
      this.sql.exec("INSERT INTO hits (address, at) VALUES (?, ?)", input.address, input.now);
      return { ok: true, ...effect() };
    });
  }

  private isJoined(address: string): boolean {
    return this.sql.exec("SELECT 1 FROM taus WHERE address = ?", address).toArray().length > 0;
  }

  /**
   * Deletes taus and the links they reported; returns the reports deleted. Other taus'
   * reports about them stay: a link needs both ends joined, so it simply stops being
   * mutual, and each reporter's next report drops the peer (only joined peers are kept).
   */
  private forget(addresses: string[]): number {
    if (addresses.length === 0) return 0;
    const list = JSON.stringify(addresses);
    this.sql.exec("DELETE FROM taus WHERE address IN (SELECT value FROM json_each(?))", list);
    return this.sql
      .exec(
        `DELETE FROM reports WHERE reporter IN (SELECT value FROM json_each(?))
         RETURNING reporter`,
        list,
      )
      .toArray().length;
  }

  /**
   * A tau and its links, through the same snapshot rule as the whole universe: the rows
   * from and about the tau, and the taus on both ends.
   */
  private view(address: string, now: number): TauView | null {
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
    const taus = this.sql
      .exec<TauRow>(
        `SELECT address, name, owner, about, joined_at, last_seen FROM taus
         WHERE address IN (SELECT value FROM json_each(?))`,
        JSON.stringify([...ends]),
      )
      .toArray();
    return tauView(buildSnapshot("", now, taus, reports), address);
  }
}
