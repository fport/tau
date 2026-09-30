/** The Directory Durable Object through its RPC methods, and the hourly cron. */

import { createScheduledController, reset, runInDurableObject } from "cloudflare:test";
import { env } from "cloudflare:workers";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { RATE_LIMIT_PER_HOUR } from "../src/directory";
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
    expect(version.version).toBe(1);
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
    expect(await d.prune(T)).toEqual({ taus: 0, reports: 0, hits: 1, clocks: 1 });
    expect(await count("hits")).toBe(1);
    expect(await d.lastTs("b.example")).toBe(T - 100);
    expect(await d.lastTs("a.example")).toBeNull();
  });
});
