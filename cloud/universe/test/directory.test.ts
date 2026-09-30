/** The Directory Durable Object through its RPC methods, and the hourly cron. */

import { createScheduledController, reset, runInDurableObject } from "cloudflare:test";
import { env } from "cloudflare:workers";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { RATE_LIMIT_PER_HOUR, SCHEMA_V1, SCHEMA_V2, SCHEMA_VERSION } from "../src/directory";
import worker from "../src/index";
import {
  ALICE,
  BOB,
  directory,
  mockTaus,
  prepareTaus,
  resetClocks,
  send,
  snapshot,
} from "./helpers";

const T = 1_800_000_000;
const DAY = 86_400;

beforeAll(prepareTaus);
beforeEach(async () => {
  await reset();
  resetClocks();
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

function joinInput(address: string, ts: number, now = ts) {
  return { address, ts, now, name: `${address} tau`, sign_key: "k", owner: "", about: "" };
}

/** A sub-tau as a report lists it, after normalizeSubs. */
function reported(name: string, about = "", extra: { web?: boolean; starters?: string[] } = {}) {
  return { name, about, web: false, starters: [] as string[], ...extra };
}

/** Drops every table and rebuilds the schema as version `version` left it. */
function rebuild(sql: SqlStorage, version: 1 | 2): void {
  for (const table of ["taus", "reports", "clocks", "hits", "slugs", "nonces", "schema_version"]) {
    sql.exec(`DROP TABLE IF EXISTS ${table}`);
  }
  for (const statement of SCHEMA_V1) sql.exec(statement);
  if (version >= 2) for (const statement of SCHEMA_V2) sql.exec(statement);
  sql.exec("CREATE TABLE schema_version (version INTEGER NOT NULL)");
  sql.exec("INSERT INTO schema_version (version) VALUES (?)", version);
}

async function count(table: string): Promise<number> {
  return runInDurableObject(directory(), (_instance, state) => {
    const row = state.storage.sql.exec<{ n: number }>(`SELECT COUNT(*) AS n FROM ${table}`).one();
    return row.n;
  });
}

describe("Directory RPC", () => {
  it("creates its schema on first use and records the version", async () => {
    const version = await runInDurableObject(directory(), (_instance, state) =>
      state.storage.sql.exec<{ version: number }>("SELECT version FROM schema_version").one(),
    );
    expect(version.version).toBe(SCHEMA_VERSION);
    expect(SCHEMA_VERSION).toBe(3);
  });

  it("upgrades a version 1 database: taus keep their rows and get no sub-taus", async () => {
    const d = directory();
    await runInDurableObject(d, (instance, state) => {
      const sql = state.storage.sql;
      // Rebuild the database exactly as version 1 left it, with one tau in it.
      rebuild(sql, 1);
      sql.exec(
        `INSERT INTO taus (address, name, sign_key, owner, about, joined_at, last_seen)
         VALUES ('old.example', 'Old tau', 'k', 'O', 'from v1', ?, ?)`,
        T,
        T,
      );
      (instance as unknown as { migrate(): void }).migrate();
      const version = sql
        .exec<{ version: number }>("SELECT MAX(version) AS version FROM schema_version")
        .one();
      expect(version.version).toBe(SCHEMA_VERSION);
    });
    const snap = await d.snapshot("u.example", T + 1);
    expect(snap.taus).toEqual([
      {
        address: "old.example",
        name: "Old tau",
        owner: "O",
        about: "from v1",
        joined_at: T,
        last_seen: T,
        online: true,
        handle: null,
        subs: [],
      },
    ]);
    // The upgraded table takes sub-taus from the next report.
    expect(
      await d.report({
        address: "old.example",
        ts: T + 2,
        now: T + 2,
        name: "Old tau",
        sign_key: "k",
        links: [],
        subs: [reported("coach", "Coach.")],
      }),
    ).toEqual({ ok: true, visible_links: 0 });
    expect((await d.tau("old.example", T + 2))?.subs).toEqual([
      { ...reported("coach", "Coach."), first_seen: T + 2, slug: "coach" },
    ]);
  });

  it("upgrades a version 2 database: taus and sub-taus stay, slugs go first come", async () => {
    const d = directory();
    await runInDurableObject(d, (instance, state) => {
      const sql = state.storage.sql;
      rebuild(sql, 2);
      const insert = (address: string, joined: number, subs: unknown) =>
        sql.exec(
          `INSERT INTO taus (address, name, sign_key, owner, about, joined_at, last_seen, subs)
           VALUES (?, ?, 'k', 'O', '', ?, ?, ?)`,
          address,
          `${address} tau`,
          joined,
          T + 50,
          JSON.stringify(subs),
        );
      // Bob joined later but sorts first by address: the slug still goes to Alice.
      insert("bob.example", T + 10, [{ name: "coach", about: "Bob's coach." }]);
      insert("alice.example", T, [
        { name: "coach", about: "Alice's coach." },
        { name: "universe", about: "A reserved name." },
        { name: "app", about: "A reserved sub-tau name." },
      ]);
      sql.exec("INSERT INTO reports (reporter, peer, messages) VALUES ('alice.example', 'bob.example', 3)");
      sql.exec("INSERT INTO reports (reporter, peer, messages) VALUES ('bob.example', 'alice.example', 4)");
      (instance as unknown as { migrate(): void }).migrate();
    });
    const snap = await d.snapshot("u.example", T + 60);
    expect(snap.taus.map((tau) => [tau.address, tau.handle, tau.subs])).toEqual([
      [
        "alice.example",
        null,
        [
          { ...reported("coach", "Alice's coach."), first_seen: T + 50, slug: "coach" },
          { ...reported("universe", "A reserved name."), first_seen: T + 50, slug: null },
        ],
      ],
      [
        "bob.example",
        null,
        [{ ...reported("coach", "Bob's coach."), first_seen: T + 50, slug: null }],
      ],
    ]);
    expect(snap.links).toEqual([{ a: "alice.example", b: "bob.example", messages: 3 }]);
    expect(await d.sub({ slug: "coach" }, "u.example", T + 60)).toMatchObject({
      owner: { address: "alice.example" },
    });
  });

  it("reads stored sub-taus defensively", async () => {
    const d = directory();
    await d.join(joinInput("a.example", T));
    await runInDurableObject(d, (_instance, state) => {
      state.storage.sql.exec(
        `UPDATE taus SET subs = '[{"name":"ok","about":"fine","web":"yes","starters":["a",1]},{"name":1},"x"]'`,
      );
    });
    expect((await d.tau("a.example", T))?.subs).toEqual([
      { name: "ok", about: "fine", web: false, starters: ["a"], first_seen: T, slug: null },
    ]);
    await runInDurableObject(d, (_instance, state) => {
      state.storage.sql.exec("UPDATE taus SET subs = 'not json'");
    });
    expect((await d.tau("a.example", T))?.subs).toEqual([]);
  });

  it("joins, reports and leaves", async () => {
    const d = directory();
    expect(await d.join(joinInput("a.example", T))).toEqual({ ok: true });
    expect(await d.join(joinInput("b.example", T))).toEqual({ ok: true });
    const report = (address: string, peer: string, ts: number, messages: number) =>
      d.report({
        address,
        ts,
        now: ts,
        name: `${address} tau`,
        sign_key: "k",
        links: [{ peer, messages }],
      });
    expect(await report("a.example", "b.example", T + 1, 4)).toEqual({
      ok: true,
      visible_links: 0,
    });
    expect(await report("b.example", "a.example", T + 1, 6)).toEqual({
      ok: true,
      visible_links: 1,
    });

    const snap = await d.snapshot("u.example", T + 2);
    expect(snap.links).toEqual([{ a: "a.example", b: "b.example", messages: 4 }]);
    expect((await d.tau("a.example", T + 2))?.links).toEqual([{ peer: "b.example", messages: 4 }]);

    expect(await d.leave({ address: "a.example", ts: T + 3, now: T + 3 })).toEqual({ ok: true });
    expect(await d.tau("a.example", T + 3)).toBeNull();
    expect((await d.tau("b.example", T + 3))?.links).toEqual([]);
    // Only b's own report is left.
    expect(await count("reports")).toBe(1);
  });

  it("judges replay, joined and rate limit in that order, and writes nothing on a refusal", async () => {
    const d = directory();
    expect(await d.leave({ address: "a.example", ts: T, now: T })).toEqual({
      ok: false,
      error: "not_joined",
    });
    expect(await d.lastTs("a.example")).toBeNull();
    expect(await d.join(joinInput("a.example", T))).toEqual({ ok: true });
    expect(await d.lastTs("a.example")).toBe(T);
    expect(await d.join(joinInput("a.example", T))).toEqual({ ok: false, error: "stale" });
    for (let i = 1; i < RATE_LIMIT_PER_HOUR; i++) {
      expect((await d.join(joinInput("a.example", T + i))).ok).toBe(true);
    }
    expect(await d.join(joinInput("a.example", T + 100))).toEqual({
      ok: false,
      error: "rate_limited",
    });
    expect(await d.lastTs("a.example")).toBe(T + RATE_LIMIT_PER_HOUR - 1);
    expect(await count("hits")).toBe(RATE_LIMIT_PER_HOUR);
  });

  it("stores reports only towards joined peers and rewrites only what changed", async () => {
    const d = directory();
    await d.join(joinInput("a.example", T));
    await d.join(joinInput("b.example", T));
    const links = [
      { peer: "b.example", messages: 1 },
      { peer: "ghost.example", messages: 1 },
    ];
    await d.report({
      address: "a.example",
      ts: T + 1,
      now: T + 1,
      name: "a",
      sign_key: "k",
      links,
    });
    const stored = await runInDurableObject(directory(), (_instance, state) =>
      state.storage.sql.exec("SELECT reporter, peer, messages FROM reports").toArray(),
    );
    expect(stored).toEqual([{ reporter: "a.example", peer: "b.example", messages: 1 }]);
  });
});

describe("hourly cron", () => {
  it("drops taus silent for 30 days with their links, and prunes old hits and clocks", async () => {
    mockTaus(ALICE, BOB);
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(T * 1000);
    await send("join", ALICE, { ts: T });
    await send("join", BOB, { ts: T });
    await send("report", ALICE, { ts: T + 1, links: [{ peer: BOB.address, messages: 3 }] });
    await send("report", BOB, { ts: T + 1, links: [{ peer: ALICE.address, messages: 3 }] });
    expect((await snapshot()).links).toHaveLength(1);

    // Bob keeps reporting; Alice goes quiet.
    vi.setSystemTime((T + 29 * DAY) * 1000);
    await send("report", BOB, { ts: T + 29 * DAY, links: [{ peer: ALICE.address, messages: 3 }] });

    // One second short of 30 days, Alice stays.
    vi.setSystemTime((T + 1 + 30 * DAY) * 1000);
    await worker.scheduled(createScheduledController({ cron: "0 * * * *" }), env);
    expect((await snapshot()).taus).toHaveLength(2);

    vi.setSystemTime((T + 2 + 30 * DAY) * 1000);
    await worker.scheduled(createScheduledController({ cron: "0 * * * *" }), env);
    const snap = await snapshot();
    expect(snap.taus.map((t) => t.address)).toEqual([BOB.address]);
    expect(snap.links).toEqual([]);
    // Alice's own report is gone; Bob's claim waits for his next report to drop her.
    expect(await count("reports")).toBe(1);
    // Every hit and clock is older than an hour by now.
    expect(await count("hits")).toBe(0);
    expect(await count("clocks")).toBe(0);
  });

  it("keeps hits and clocks of the last hour", async () => {
    const d = directory();
    await d.join(joinInput("a.example", T - 3_700, T - 3_700));
    await d.join(joinInput("b.example", T - 100, T - 100));
    expect(await d.prune(T)).toEqual({ taus: 0, reports: 0, hits: 1, clocks: 1, nonces: 0 });
    expect(await count("hits")).toBe(1);
    expect(await d.lastTs("b.example")).toBe(T - 100);
    expect(await d.lastTs("a.example")).toBeNull();
  });
});
