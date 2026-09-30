/** The Mailbox Durable Object through its RPC methods (the Worker's checks are in net.test.ts). */

import { beforeEach, describe, expect, it } from "vitest";
import {
  MAILBOX_LIMIT,
  MAILBOX_RETENTION_SECONDS,
  RATE_LIMIT_PER_HOUR,
  SCHEMA_VERSION,
  SEEN_RETENTION_SECONDS,
} from "../src/mailbox";
import { inMailbox, mailboxStub, nowSeconds, resetStore } from "./helpers";

const FROM = "alice.example";
const ENVELOPE = '{"payload":"AAAA","sig":"AAAA"}';

beforeEach(resetStore);

function id(n: number): string {
  return `mailbox-test-${String(n).padStart(6, "0")}`;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

describe("storage", () => {
  it("creates its tables on first use, with a schema version row", async () => {
    expect(await mailboxStub().depth()).toBe(0);
    const { tables, version } = await inMailbox((sql) => ({
      tables: sql
        .exec<{ name: string }>(
          "SELECT name FROM sqlite_master WHERE type = 'table' AND name IN ('mailbox', 'seen', 'meta') ORDER BY name",
        )
        .toArray()
        .map((row) => row.name),
      version: sql
        .exec<{ value: number }>("SELECT value FROM meta WHERE key = 'schema_version'")
        .one().value,
    }));
    expect(tables).toEqual(["mailbox", "meta", "seen"]);
    expect(version).toBe(SCHEMA_VERSION);
  });

  it("stores the envelope text and the arrival time as given", async () => {
    const box = mailboxStub();
    const now = nowSeconds();
    const delivery = await box.deliver(FROM, id(1), now, ENVELOPE);
    expect(delivery).toMatchObject({ status: "queued" });
    const rows = await box.updates(0, 10, 0);
    expect(rows).toEqual([
      { seq: (delivery as { seq: number }).seq, received_at: now, envelope: ENVELOPE },
    ]);
  });

  it("never reuses a seq, even after the newest envelope was acknowledged", async () => {
    const box = mailboxStub();
    const first = (await box.deliver(FROM, id(1), nowSeconds(), ENVELOPE)) as { seq: number };
    expect(await box.ack([first.seq, first.seq, 999_999])).toBe(1);
    const second = (await box.deliver(FROM, id(2), nowSeconds(), ENVELOPE)) as { seq: number };
    expect(second.seq).toBeGreaterThan(first.seq);
    expect(await box.depth()).toBe(1);
  });
});

describe("deliver", () => {
  it("answers a repeated id as a duplicate and stores it once", async () => {
    const box = mailboxStub();
    const now = nowSeconds();
    expect(await box.deliver(FROM, id(1), now, ENVELOPE)).toMatchObject({ status: "queued" });
    expect(await box.deliver(FROM, id(1), now + 1, ENVELOPE)).toEqual({ status: "duplicate" });
    // The same id from another sender is another envelope.
    expect(await box.deliver("carol.example", id(1), now, ENVELOPE)).toMatchObject({
      status: "queued",
    });
    expect(await box.depth()).toBe(2);
  });

  it("stays a duplicate after the envelope was acknowledged", async () => {
    const box = mailboxStub();
    const queued = (await box.deliver(FROM, id(1), nowSeconds(), ENVELOPE)) as { seq: number };
    expect(await box.ack([queued.seq])).toBe(1);
    expect(await box.deliver(FROM, id(1), nowSeconds(), ENVELOPE)).toEqual({
      status: "duplicate",
    });
    expect(await box.depth()).toBe(0);
  });

  it("rate-limits a sender after 60 arrivals in an hour, after the duplicate check", async () => {
    const box = mailboxStub();
    const now = nowSeconds();
    for (let i = 0; i < RATE_LIMIT_PER_HOUR; i++) {
      // Spread over the last hour: all of them count.
      const at = now - 3_599 + i * 60;
      expect(await box.deliver(FROM, id(i), at, ENVELOPE), `delivery ${i}`).toMatchObject({
        status: "queued",
      });
    }
    expect(await box.deliver(FROM, id(100), now, ENVELOPE)).toEqual({ status: "rate_limited" });
    // A duplicate is judged before the rate limit.
    expect(await box.deliver(FROM, id(0), now, ENVELOPE)).toEqual({ status: "duplicate" });
    // Another sender is not affected.
    expect(await box.deliver("carol.example", id(100), now, ENVELOPE)).toMatchObject({
      status: "queued",
    });
    // A rejected envelope is not remembered: once the hour has passed it is accepted.
    expect(await box.deliver(FROM, id(100), now + 3_600, ENVELOPE)).toMatchObject({
      status: "queued",
    });
  });

  it("is full at 1000 undelivered envelopes, after the duplicate and rate checks", async () => {
    const box = mailboxStub();
    const now = nowSeconds();
    expect(await box.deliver(FROM, id(1), now, ENVELOPE)).toMatchObject({ status: "queued" });
    await inMailbox((sql) =>
      sql.exec(
        "WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM n WHERE x < ?) " +
          "INSERT INTO mailbox (sender, envelope, received_at) SELECT 'other.example', '{}', ? FROM n",
        MAILBOX_LIMIT - 1,
        now,
      ),
    );
    expect(await box.deliver(FROM, id(2), now, ENVELOPE)).toEqual({ status: "mailbox_full" });
    expect(await box.deliver(FROM, id(1), now, ENVELOPE)).toEqual({ status: "duplicate" });
    expect(await box.depth()).toBe(MAILBOX_LIMIT);
    // An ack makes room again.
    const [oldest] = await box.updates(0, 1, 0);
    expect(await box.ack([oldest!.seq])).toBe(1);
    expect(await box.deliver(FROM, id(2), now, ENVELOPE)).toMatchObject({ status: "queued" });
  });
});

describe("updates", () => {
  it("returns queued envelopes after the cursor, in seq order, up to the limit", async () => {
    const box = mailboxStub();
    const seqs: number[] = [];
    for (let i = 0; i < 4; i++) {
      seqs.push(((await box.deliver(FROM, id(i), nowSeconds(), ENVELOPE)) as { seq: number }).seq);
    }
    expect((await box.updates(0, 50, 0)).map((row) => row.seq)).toEqual(seqs);
    expect((await box.updates(seqs[1]!, 50, 0)).map((row) => row.seq)).toEqual(seqs.slice(2));
    expect((await box.updates(0, 3, 0)).map((row) => row.seq)).toEqual(seqs.slice(0, 3));
  });

  it("is woken by a delivery while it waits", async () => {
    const box = mailboxStub();
    const started = Date.now();
    const poll = box.updates(0, 50, 20_000);
    await sleep(200);
    expect(await box.deliver(FROM, id(1), nowSeconds(), ENVELOPE)).toMatchObject({
      status: "queued",
    });
    const rows = await poll;
    expect(Date.now() - started).toBeLessThan(5_000);
    expect(rows.map((row) => row.envelope)).toEqual([ENVELOPE]);
  });

  it("wakes every waiting poll", async () => {
    const box = mailboxStub();
    const polls = [box.updates(0, 50, 20_000), box.updates(0, 50, 20_000)];
    await sleep(200);
    await box.deliver(FROM, id(1), nowSeconds(), ENVELOPE);
    const answers = await Promise.all(polls);
    expect(answers.map((rows) => rows.length)).toEqual([1, 1]);
  });

  it("is not woken by a duplicate or a rejected envelope", async () => {
    const box = mailboxStub();
    const first = (await box.deliver(FROM, id(1), nowSeconds(), ENVELOPE)) as { seq: number };
    const started = Date.now();
    const poll = box.updates(first.seq, 50, 600);
    await sleep(100);
    expect(await box.deliver(FROM, id(1), nowSeconds(), ENVELOPE)).toEqual({
      status: "duplicate",
    });
    expect(await poll).toEqual([]);
    expect(Date.now() - started).toBeGreaterThanOrEqual(550);
  });

  it("waits out its timeout when its cursor is past every queued seq", async () => {
    const box = mailboxStub();
    const queued = (await box.deliver(FROM, id(1), nowSeconds(), ENVELOPE)) as { seq: number };
    const started = Date.now();
    expect(await box.updates(queued.seq, 50, 300)).toEqual([]);
    expect(Date.now() - started).toBeGreaterThanOrEqual(250);
  });
});

describe("prune", () => {
  it("deletes mailbox rows older than 7 days and seen rows older than 1 day", async () => {
    const box = mailboxStub();
    const now = nowSeconds();
    const deliveries: [string, number][] = [
      [id(1), now - MAILBOX_RETENTION_SECONDS - 1], // mailbox: gone; seen: gone
      [id(2), now - MAILBOX_RETENTION_SECONDS], // mailbox: kept (not older); seen: gone
      [id(3), now - SEEN_RETENTION_SECONDS - 1], // mailbox: kept; seen: gone
      [id(4), now - SEEN_RETENTION_SECONDS], // both kept
      [id(5), now], // both kept
    ];
    for (const [envelopeId, at] of deliveries) {
      expect(await box.deliver(FROM, envelopeId, at, ENVELOPE)).toMatchObject({ status: "queued" });
    }
    expect(await box.prune(now)).toEqual({ mailbox: 1, seen: 3 });
    expect(await box.depth()).toBe(4);
    const seen = await inMailbox((sql) =>
      sql.exec<{ id: string }>("SELECT id FROM seen ORDER BY id").toArray(),
    );
    expect(seen.map((row) => row.id)).toEqual([id(4), id(5)]);
    // Nothing left to prune.
    expect(await box.prune(now)).toEqual({ mailbox: 0, seen: 0 });
  });

  it("lets a pruned id through again (the replay guard covers one day)", async () => {
    const box = mailboxStub();
    const now = nowSeconds();
    await box.deliver(FROM, id(1), now - 2 * SEEN_RETENTION_SECONDS, ENVELOPE);
    await box.prune(now);
    expect(await box.deliver(FROM, id(1), now, ENVELOPE)).toMatchObject({ status: "queued" });
  });
});
