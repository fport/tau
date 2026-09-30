/**
 * The Mailbox: the spine's store of envelopes in transit, a SQLite-backed Durable Object.
 *
 * One instance (named "hub") serves the whole spine. It owns everything the inbox and the
 * hub's long poll share:
 *
 * - `mailbox`: envelopes that passed every inbox check, until the hub acknowledges them;
 * - `seen`: envelope ids per sender, the replay guard, whose rows of the last hour are the
 *   sender's arrival count for the rate limit;
 * - the mailbox cap;
 * - the waiting long polls, which a delivery wakes.
 *
 * Data and wake-up live in the same object, and every storage call here is synchronous, so a
 * poll that finds nothing and starts to wait cannot miss an envelope stored in between.
 *
 * The Worker parses the envelope, fetches the sender's card and verifies the signature; only
 * then does it call deliver(), which judges duplicate → rate limit → mailbox cap in that order
 * (§4 of docs/reference/tau-network.md). SQLite-backed Durable Objects are on the Workers Free
 * plan, so local mode needs no D1 database at all.
 */

import { DurableObject } from "cloudflare:workers";
import type { SpineEnv } from "./env";

/** The single instance of the spine (`idFromName("hub")`). */
export const MAILBOX_NAME = "hub";

export const RATE_LIMIT_PER_HOUR = 60;
export const MAILBOX_LIMIT = 1_000;
export const MAILBOX_RETENTION_SECONDS = 7 * 86_400;
export const SEEN_RETENTION_SECONDS = 86_400;

const RATE_WINDOW_SECONDS = 3_600;
/** Upper bound for one wait, a little above the longest long poll (25 s). */
const MAX_WAIT_MS = 30_000;
/** Durable Object SQLite allows 100 bound parameters per statement. */
const MAX_BOUND_PARAMETERS = 100;

/** Bump with a new step in migrate(). */
export const SCHEMA_VERSION = 1;

const SCHEMA_V1 = `
-- Envelopes that passed every inbox check, kept until the hub acknowledges them.
-- AUTOINCREMENT: a seq is never reused, even after the newest envelope was acknowledged.
CREATE TABLE mailbox (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  sender TEXT NOT NULL,
  -- {"payload": b64u, "sig": b64u}, exactly as the sender posted it (other keys dropped).
  envelope TEXT NOT NULL,
  -- Unix seconds.
  received_at INTEGER NOT NULL
);
CREATE INDEX mailbox_received_at ON mailbox (received_at);

-- Envelope ids seen per sender: duplicates are answered without storing them again, and
-- the rows of the last hour count against the sender's rate limit.
CREATE TABLE seen (
  sender TEXT NOT NULL,
  id TEXT NOT NULL,
  -- Unix seconds of arrival.
  ts INTEGER NOT NULL,
  PRIMARY KEY (sender, id)
);
CREATE INDEX seen_sender_ts ON seen (sender, ts);
CREATE INDEX seen_ts ON seen (ts);
`;

/** What deliver() did with an envelope. */
export type Delivery =
  | { status: "queued"; seq: number }
  | { status: "duplicate" }
  | { status: "rate_limited" }
  | { status: "mailbox_full" };

/** A queued envelope; `envelope` is the stored JSON text. */
export type MailboxRow = { seq: number; received_at: number; envelope: string };

/** Rows deleted by prune(). */
export type Pruned = { mailbox: number; seen: number };

/** Creates the tables on first use; `meta` holds the schema version. */
function migrate(sql: SqlStorage): void {
  sql.exec("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value INTEGER NOT NULL)");
  const [row] = sql
    .exec<{ value: number }>("SELECT value FROM meta WHERE key = 'schema_version'")
    .toArray();
  const version = row?.value ?? 0;
  if (version >= SCHEMA_VERSION) return;
  if (version < 1) sql.exec(SCHEMA_V1);
  sql.exec(
    "INSERT INTO meta (key, value) VALUES ('schema_version', ?) " +
      "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
    SCHEMA_VERSION,
  );
}

export class Mailbox extends DurableObject<SpineEnv> {
  private readonly sql: SqlStorage;
  private readonly waiters = new Set<(woken: boolean) => void>();

  constructor(ctx: DurableObjectState, env: SpineEnv) {
    super(ctx, env);
    this.sql = ctx.storage.sql;
    // Synchronous, so it completes before the object takes its first call.
    ctx.storage.transactionSync(() => migrate(this.sql));
  }

  /**
   * Stores an envelope that passed the Worker's checks (§4 steps 1–6), unless it is a
   * duplicate, its sender is over the rate limit or the mailbox is full, judged in that
   * order. `receivedAt` is the arrival time in Unix seconds. A queued envelope wakes every
   * waiting long poll.
   */
  deliver(from: string, id: string, receivedAt: number, envelope: string): Delivery {
    const delivery = this.ctx.storage.transactionSync((): Delivery => {
      if (this.count("SELECT COUNT(*) AS n FROM seen WHERE sender = ? AND id = ?", from, id) > 0) {
        return { status: "duplicate" };
      }
      const recent = this.count(
        "SELECT COUNT(*) AS n FROM seen WHERE sender = ? AND ts > ?",
        from,
        receivedAt - RATE_WINDOW_SECONDS,
      );
      if (recent >= RATE_LIMIT_PER_HOUR) return { status: "rate_limited" };
      if (this.depth() >= MAILBOX_LIMIT) return { status: "mailbox_full" };
      this.sql.exec("INSERT INTO seen (sender, id, ts) VALUES (?, ?, ?)", from, id, receivedAt);
      const { seq } = this.sql
        .exec<{ seq: number }>(
          "INSERT INTO mailbox (sender, envelope, received_at) VALUES (?, ?, ?) RETURNING seq",
          from,
          envelope,
          receivedAt,
        )
        .one();
      return { status: "queued", seq };
    });
    if (delivery.status === "queued") this.wake();
    return delivery;
  }

  /**
   * Up to `limit` envelopes with `seq > after`, in seq order. With none queued and
   * `timeoutMs > 0`, waits until a delivery or the timeout, then looks once more (the
   * answer may still be empty).
   */
  async updates(after: number, limit: number, timeoutMs: number): Promise<MailboxRow[]> {
    const rows = this.queued(after, limit);
    if (rows.length > 0 || timeoutMs <= 0) return rows;
    await this.wait(timeoutMs);
    return this.queued(after, limit);
  }

  /** Deletes the envelopes with these seqs; returns how many existed. */
  ack(seqs: number[]): number {
    return this.ctx.storage.transactionSync(() => {
      let deleted = 0;
      for (let i = 0; i < seqs.length; i += MAX_BOUND_PARAMETERS) {
        const chunk = seqs.slice(i, i + MAX_BOUND_PARAMETERS);
        deleted += this.deleted(
          `DELETE FROM mailbox WHERE seq IN (${chunk.map(() => "?").join(",")}) RETURNING seq`,
          ...chunk,
        );
      }
      return deleted;
    });
  }

  /** The number of undelivered envelopes. */
  depth(): number {
    return this.count("SELECT COUNT(*) AS n FROM mailbox");
  }

  /** Deletes mailbox rows older than 7 days and seen rows older than 1 day. */
  prune(now: number): Pruned {
    return this.ctx.storage.transactionSync(() => ({
      mailbox: this.deleted(
        "DELETE FROM mailbox WHERE received_at < ? RETURNING seq",
        now - MAILBOX_RETENTION_SECONDS,
      ),
      seen: this.deleted(
        "DELETE FROM seen WHERE ts < ? RETURNING id",
        now - SEEN_RETENTION_SECONDS,
      ),
    }));
  }

  private queued(after: number, limit: number): MailboxRow[] {
    return this.sql
      .exec<MailboxRow>(
        "SELECT seq, received_at, envelope FROM mailbox WHERE seq > ? ORDER BY seq LIMIT ?",
        after,
        limit,
      )
      .toArray();
  }

  private count(query: string, ...bindings: SqlStorageValue[]): number {
    return this.sql.exec<{ n: number }>(query, ...bindings).one().n;
  }

  private deleted(query: string, ...bindings: SqlStorageValue[]): number {
    return this.sql.exec(query, ...bindings).toArray().length;
  }

  /** Resolves true when a delivery wakes it, false after `ms`. */
  private wait(ms: number): Promise<boolean> {
    const timeout = Math.max(0, Math.min(ms, MAX_WAIT_MS));
    return new Promise<boolean>((resolve) => {
      const finish = (woken: boolean): void => {
        clearTimeout(timer);
        this.waiters.delete(finish);
        resolve(woken);
      };
      const timer = setTimeout(() => finish(false), timeout);
      this.waiters.add(finish);
    });
  }

  private wake(): void {
    for (const finish of [...this.waiters]) finish(true);
  }
}

/** The spine's Mailbox: the one instance named "hub". */
export function mailboxOf(env: SpineEnv): DurableObjectStub<Mailbox> {
  return env.MAILBOX.getByName(MAILBOX_NAME);
}
