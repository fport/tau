/**
 * Relay: the Durable Object of one visitor thread (ADR 0013 §5; §5 of
 * docs/reference/tau-universe.md). One instance per thread, named by the thread id.
 *
 * A thread is an anonymous visitor's conversation with one web sub-tau. Its SQLite database
 * holds:
 *
 *   thread    one row: the visitor (the SHA-256 of their cookie, never the cookie), the
 *             sub-tau (its tau's address and its name, with the slug and handle its page had
 *             when the thread began), whether tau-host answers it, tau-host's own thread id,
 *             the thread's state, and when it began and ends
 *   messages  `{n, sender, text, ts}`: the visitor's messages and the sub-tau's answers, at
 *             most MAX_THREAD_MESSAGES
 *   visits    one row per visitor message relayed: its id (for a hub-run sub-tau the `visit`
 *             envelope's id, which the hub's answer names in `reply_to`), whether it awaits
 *             an answer (until `pending_until`), and the id of the answer that came
 *
 * The tables exist only once a thread began: reading an unknown thread id writes nothing, so
 * probing ids leaves no storage behind. An alarm deletes everything 24 hours after the
 * thread began (THREAD_TTL_SECONDS); every method also treats an expired thread as gone.
 *
 * Every time is passed in (`now`, Unix seconds). The Worker holds no request inside this
 * object: a long poll reads it again every few seconds (src/chat.ts), so the object is
 * billed for milliseconds, not for the wait.
 */

import { DurableObject } from "cloudflare:workers";
import type { UniverseEnv } from "./env";

/** A thread is deleted this long after it began. */
export const THREAD_TTL_SECONDS = 86_400;
/** A thread holds at most this many messages, the visitor's and the sub-tau's together. */
export const MAX_THREAD_MESSAGES = 50;
/** How long a visit to a hosted sub-tau counts as pending (tau-host answers within ~30 s). */
export const HOSTED_PENDING_SECONDS = 60;
/** How long a visit to a hub-run sub-tau counts as pending; a later answer still lands. */
export const HUB_PENDING_SECONDS = 120;

export type Sender = "visitor" | "sub";

/** A message of a thread as the chat API returns it. */
export interface ChatMessage {
  n: number;
  from: Sender;
  text: string;
  ts: number;
}

/**
 * - `open`: the sub-tau takes messages;
 * - `resting`: a hosted sub-tau reached its daily cap (`web_daily`) or its owner's budget;
 * - `full`: the thread has no room for another exchange; start a new one;
 * - `unavailable`: the last message could not be delivered or answered; try again later.
 */
export type ThreadState = "open" | "resting" | "full" | "unavailable";

export interface ThreadView {
  messages: ChatMessage[];
  /** A visitor message still awaits its answer. */
  pending: boolean;
  state: ThreadState;
}

/** The sub-tau a thread talks to, as the directory named it. */
export interface ThreadTarget {
  /** The address of the tau that runs the sub-tau. */
  address: string;
  /** The sub-tau's name. */
  name: string;
  /** Its short page `/<slug>`, or null. */
  slug: string | null;
  /** Its tau's handle, or null. */
  handle: string | null;
  /** tau-host answers it through the HOST binding (else a hub, through `visit` envelopes). */
  hosted: boolean;
}

/** How a request path names the target: its slug, or its tau's handle and its name. */
export type TargetRef = { slug: string } | { handle: string; name: string };

export interface SendInput {
  /** Start the thread (a new id the Worker picked) rather than continue it. */
  create: boolean;
  /** SHA-256 of the visitor's cookie. */
  visitor: string;
  target: ThreadTarget;
  text: string;
  /** The id of this visit. */
  visit: string;
  now: number;
}

export type SendOutcome =
  | { ok: true; n: number; hostThread: string | null }
  | { ok: false; error: "not_found" | "busy" | "thread_full" };

export interface AnswerInput {
  visit: string;
  /** The sub-tau's answer, or null when it chose not to answer. */
  text: string | null;
  /** tau-host's id of the answer. */
  replyId: string;
  /** tau-host's thread id, used for the thread's next visits. */
  hostThread: string | null;
  now: number;
}

export interface FailInput {
  visit: string;
  state: Exclude<ThreadState, "open">;
  now: number;
}

export interface ReadInput {
  visitor: string;
  ref: TargetRef;
  after: number;
  now: number;
}

export interface ExpectInput {
  /** The answer's `reply_to`. */
  visit: string;
  /** The answer's `from`. */
  from: string;
  now: number;
}

export type ExpectOutcome =
  | { ok: true; sub: string }
  | { ok: false; error: "unknown" | "wrong_sender" };

export interface ReplyInput extends ExpectInput {
  /** The answer envelope's id. */
  id: string;
  text: string;
}

export type ReplyOutcome = "delivered" | "duplicate" | "answered" | "unknown" | "wrong_sender";

type ThreadRow = {
  id: string;
  visitor: string;
  address: string;
  name: string;
  slug: string | null;
  handle: string | null;
  hosted: number;
  host_thread: string | null;
  state: ThreadState;
  created_at: number;
  expires_at: number;
};

type VisitRow = {
  id: string;
  status: "pending" | "answered" | "failed";
  reply_id: string | null;
};

const SCHEMA = [
  `CREATE TABLE thread (
    id TEXT PRIMARY KEY,
    visitor TEXT NOT NULL,
    address TEXT NOT NULL,
    name TEXT NOT NULL,
    slug TEXT,
    handle TEXT,
    hosted INTEGER NOT NULL,
    host_thread TEXT,
    state TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL
  )`,
  `CREATE TABLE messages (
    n INTEGER PRIMARY KEY,
    sender TEXT NOT NULL,
    text TEXT NOT NULL,
    ts INTEGER NOT NULL
  )`,
  `CREATE TABLE visits (
    id TEXT PRIMARY KEY,
    n INTEGER NOT NULL,
    status TEXT NOT NULL,
    pending_until INTEGER NOT NULL,
    reply_id TEXT
  )`,
];

function matches(row: ThreadRow, ref: TargetRef): boolean {
  if ("slug" in ref) return row.slug === ref.slug;
  return row.handle === ref.handle && row.name === ref.name;
}

export class Relay extends DurableObject<UniverseEnv> {
  private readonly sql: SqlStorage;

  constructor(ctx: DurableObjectState, env: UniverseEnv) {
    super(ctx, env);
    this.sql = ctx.storage.sql;
  }

  /** Whether a thread began here (read-only: an unknown id stays without storage). */
  private began(): boolean {
    return (
      this.sql
        .exec("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'thread'")
        .toArray().length > 0
    );
  }

  /** The thread, or null when none began here or it expired (the alarm deletes it). */
  private thread(now: number): ThreadRow | null {
    if (!this.began()) return null;
    const row = this.sql.exec<ThreadRow>("SELECT * FROM thread").toArray()[0];
    return row === undefined || row.expires_at <= now ? null : row;
  }

  private count(): number {
    return this.sql.exec<{ n: number }>("SELECT COUNT(*) AS n FROM messages").one().n;
  }

  private pending(now: number): boolean {
    return (
      this.sql
        .exec("SELECT 1 FROM visits WHERE status = 'pending' AND pending_until > ?", now)
        .toArray().length > 0
    );
  }

  private visit(id: string): VisitRow | null {
    return (
      this.sql
        .exec<VisitRow>("SELECT id, status, reply_id FROM visits WHERE id = ?", id)
        .toArray()[0] ?? null
    );
  }

  /** Appends a message when the thread has room; the new `n`, or null. */
  private append(sender: Sender, text: string, ts: number): number | null {
    if (this.count() >= MAX_THREAD_MESSAGES) return null;
    return this.sql
      .exec<{ n: number }>(
        "INSERT INTO messages (sender, text, ts) VALUES (?, ?, ?) RETURNING n",
        sender,
        text,
        ts,
      )
      .one().n;
  }

  /**
   * A visitor message: starts the thread when `create`, else continues it. Refused when the
   * thread is unknown, expired, another visitor's or another sub-tau's (`not_found`), when
   * the last message still awaits its answer (`busy`), or when there is no room for this
   * message and its answer (`thread_full`). Records the message and the pending visit.
   */
  async send(input: SendInput): Promise<SendOutcome> {
    const { now, target } = input;
    if (input.create) {
      if (this.began()) return { ok: false, error: "not_found" };
      this.ctx.storage.transactionSync(() => {
        for (const statement of SCHEMA) this.sql.exec(statement);
        this.sql.exec(
          `INSERT INTO thread (id, visitor, address, name, slug, handle, hosted, host_thread,
             state, created_at, expires_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, NULL, 'open', ?, ?)`,
          this.ctx.id.name ?? this.ctx.id.toString(),
          input.visitor,
          target.address,
          target.name,
          target.slug,
          target.handle,
          target.hosted ? 1 : 0,
          now,
          now + THREAD_TTL_SECONDS,
        );
      });
      await this.ctx.storage.setAlarm((now + THREAD_TTL_SECONDS) * 1000);
    }
    const row = this.thread(now);
    if (
      row === null ||
      row.visitor !== input.visitor ||
      row.address !== target.address ||
      row.name !== target.name
    ) {
      return { ok: false, error: "not_found" };
    }
    return this.ctx.storage.transactionSync((): SendOutcome => {
      if (this.count() + 2 > MAX_THREAD_MESSAGES) return { ok: false, error: "thread_full" };
      if (this.pending(now)) return { ok: false, error: "busy" };
      const n = this.append("visitor", input.text, now)!;
      const window = target.hosted ? HOSTED_PENDING_SECONDS : HUB_PENDING_SECONDS;
      this.sql.exec(
        `INSERT INTO visits (id, n, status, pending_until, reply_id)
         VALUES (?, ?, 'pending', ?, NULL)`,
        input.visit,
        n,
        now + window,
      );
      this.sql.exec(
        "UPDATE thread SET state = 'open', slug = ?, handle = ?, hosted = ?",
        target.slug,
        target.handle,
        target.hosted ? 1 : 0,
      );
      return { ok: true, n, hostThread: row.host_thread };
    });
  }

  /** tau-host answered a visit: the answer joins the thread. False when nothing changed. */
  answer(input: AnswerInput): boolean {
    const row = this.thread(input.now);
    if (row === null) return false;
    return this.ctx.storage.transactionSync(() => {
      const visit = this.visit(input.visit);
      if (visit === null || visit.status === "answered") return false;
      if (input.text !== null && input.text !== "") this.append("sub", input.text, input.now);
      this.sql.exec(
        "UPDATE visits SET status = 'answered', reply_id = ? WHERE id = ?",
        input.replyId,
        input.visit,
      );
      this.sql.exec(
        "UPDATE thread SET state = 'open', host_thread = COALESCE(?, host_thread)",
        input.hostThread,
      );
      return true;
    });
  }

  /** A visit that could not be delivered or answered; the thread takes `state`. */
  fail(input: FailInput): boolean {
    const row = this.thread(input.now);
    if (row === null) return false;
    return this.ctx.storage.transactionSync(() => {
      const visit = this.visit(input.visit);
      if (visit === null || visit.status !== "pending") return false;
      this.sql.exec("UPDATE visits SET status = 'failed' WHERE id = ?", input.visit);
      this.sql.exec("UPDATE thread SET state = ?", input.state);
      return true;
    });
  }

  /**
   * The messages after `after` (at most MAX_THREAD_MESSAGES), whether a visit is pending and
   * the thread's state; null when the thread is unknown, expired, another visitor's, or
   * named by a target that is not its sub-tau.
   */
  read(input: ReadInput): ThreadView | null {
    const row = this.thread(input.now);
    if (row === null || row.visitor !== input.visitor || !matches(row, input.ref)) return null;
    const messages = this.sql
      .exec<{ n: number; sender: Sender; text: string; ts: number }>(
        "SELECT n, sender, text, ts FROM messages WHERE n > ? ORDER BY n LIMIT ?",
        input.after,
        MAX_THREAD_MESSAGES,
      )
      .toArray()
      .map((message) => ({
        n: message.n,
        from: message.sender,
        text: message.text,
        ts: message.ts,
      }));
    const full = this.count() + 2 > MAX_THREAD_MESSAGES;
    return {
      messages,
      pending: this.pending(input.now),
      state: full ? "full" : row.state,
    };
  }

  /**
   * Whether an envelope that answers `visit` from `from` can be taken: the visit is one of
   * this thread's, and went to `from`. Asked by the inbox before it fetches a card.
   */
  expect(input: ExpectInput): ExpectOutcome {
    const row = this.thread(input.now);
    if (row === null || row.hosted === 1 || this.visit(input.visit) === null) {
      return { ok: false, error: "unknown" };
    }
    if (row.address !== input.from) return { ok: false, error: "wrong_sender" };
    return { ok: true, sub: row.name };
  }

  /**
   * A hub's verified answer to a visit: it joins the thread, also after the pending window
   * or a failed delivery. The same answer again is a `duplicate`; another answer to an
   * answered visit is refused (`answered`).
   */
  reply(input: ReplyInput): ReplyOutcome {
    const expected = this.expect(input);
    if (!expected.ok) return expected.error;
    return this.ctx.storage.transactionSync((): ReplyOutcome => {
      const visit = this.visit(input.visit)!;
      if (visit.reply_id === input.id) return "duplicate";
      if (visit.reply_id !== null) return "answered";
      this.append("sub", input.text, input.now);
      this.sql.exec(
        "UPDATE visits SET status = 'answered', reply_id = ? WHERE id = ?",
        input.id,
        input.visit,
      );
      this.sql.exec("UPDATE thread SET state = 'open'");
      return "delivered";
    });
  }

  /** 24 hours after the thread began: everything goes. */
  override async alarm(): Promise<void> {
    await this.ctx.storage.deleteAll();
  }
}
