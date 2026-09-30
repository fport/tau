import { createScheduledController } from "cloudflare:test";
import { env } from "cloudflare:workers";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { SpineEnv } from "../src/env";
import * as mainModule from "../src/index";
import worker from "../src/index";
import { SIGNAL_NAME } from "../src/signal";
import {
  envelope,
  hub,
  mailboxCount,
  mockCards,
  nowSeconds,
  PEER,
  peerCard,
  postEnvelope,
  publishCard,
  resetStore,
  SELF,
  VECTOR,
} from "./helpers";

interface Update {
  seq: number;
  received_at: number;
  envelope: { payload: string; sig: string };
}

beforeEach(resetStore);
afterEach(() => {
  vi.restoreAllMocks();
});

/** Calls the Worker directly with a modified environment. */
function fetchWith(overrides: Partial<SpineEnv>, path: string, init?: RequestInit) {
  const request = new Request(`https://${SELF}${path}`, init);
  return worker.fetch(request, { ...env, ...overrides });
}

async function queue(count: number): Promise<Update[]> {
  mockCards({ [`https://${PEER}`]: peerCard() });
  for (let i = 0; i < count; i++) {
    expect((await postEnvelope(await envelope())).status).toBe(202);
  }
  const res = await hub("/hub/updates?limit=100");
  return ((await res.json()) as { updates: Update[] }).updates;
}

it("exports only entrypoints from the main module (workerd rejects anything else)", () => {
  expect(Object.keys(mainModule).sort()).toEqual(["HubSignal", "TauBrain", "default"]);
});

describe("auth", () => {
  it("401 without or with a wrong token", async () => {
    for (const token of [null, "wrong", ""]) {
      const res = await hub("/hub/health", { token });
      expect(res.status).toBe(401);
      expect(await res.json()).toEqual({ error: "unauthorized" });
    }
  });

  it("accepts the scheme case-insensitively", async () => {
    const res = await hub("/hub/health", { token: undefined });
    expect(res.status).toBe(200);
    const lower = await fetchWith({}, "/hub/health", {
      headers: { authorization: `bearer ${env.HUB_TOKEN}` },
    });
    expect(lower.status).toBe(200);
  });

  it("503 not_configured without a HUB_TOKEN secret", async () => {
    for (const HUB_TOKEN of [undefined, ""]) {
      const res = await fetchWith({ HUB_TOKEN }, "/hub/health", {
        headers: { authorization: "Bearer anything" },
      });
      expect(res.status).toBe(503);
      expect(await res.json()).toEqual({ error: "not_configured" });
    }
  });

  it("404 not_found for unknown hub routes", async () => {
    expect(await (await hub("/hub/nothing")).json()).toEqual({ error: "not_found" });
  });
});

describe("GET /hub/health", () => {
  it("reports address, mode, card and mailbox", async () => {
    let res = await hub("/hub/health");
    expect(await res.json()).toEqual({
      ok: true,
      address: SELF,
      mode: "local",
      card: false,
      mailbox: 0,
      version: "0.1.0",
    });
    await publishCard();
    await queue(2);
    res = await hub("/hub/health");
    expect(await res.json()).toMatchObject({ card: true, mailbox: 2 });
  });

  it("uses the ADDRESS variable when set", async () => {
    const res = await fetchWith({ ADDRESS: "tau.example.com" }, "/hub/health", {
      headers: { authorization: `Bearer ${env.HUB_TOKEN}` },
    });
    expect(await res.json()).toMatchObject({ address: "tau.example.com" });
  });
});

describe("PUT /hub/card", () => {
  const card = { name: "Bob's tau", sign_key: VECTOR.signKey, box_key: VECTOR.boxKey };
  const bad: [string, unknown][] = [
    ["empty name", { ...card, name: "" }],
    ["81 characters", { ...card, name: "x".repeat(81) }],
    ["name not a string", { ...card, name: 7 }],
    ["short sign_key", { ...card, sign_key: "AAAA" }],
    ["missing box_key", { name: card.name, sign_key: card.sign_key }],
    ["not an object", [card]],
  ];
  for (const [name, body] of bad) {
    it(`400 for ${name}`, async () => {
      const res = await hub("/hub/card", { method: "PUT", body });
      expect(res.status).toBe(400);
      expect(((await res.json()) as { error: string }).error).toBe("bad_request");
    });
  }

  it("counts code points, like Python", async () => {
    const res = await hub("/hub/card", { method: "PUT", body: { ...card, name: "🦊".repeat(80) } });
    expect(res.status).toBe(200);
  });

  it("uses http in the inbox URL only for a loopback address with insecure peers", async () => {
    const res = await fetchWith(
      { ADDRESS: "127.0.0.1:8787", ALLOW_INSECURE_PEERS: "1" },
      "/hub/card",
      {
        method: "PUT",
        headers: { authorization: `Bearer ${env.HUB_TOKEN}` },
        body: JSON.stringify(card),
      },
    );
    expect(await res.json()).toMatchObject({
      address: "127.0.0.1:8787",
      inbox: "http://127.0.0.1:8787/net/inbox",
    });
  });
});

describe("GET /hub/updates", () => {
  it("answers at once with timeout 0", async () => {
    const res = await hub("/hub/updates");
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ updates: [] });
  });

  it("returns updates in seq order with after and limit", async () => {
    const all = await queue(5);
    expect(all).toHaveLength(5);
    const seqs = all.map((u) => u.seq);
    expect([...seqs].sort((a, b) => a - b)).toEqual(seqs);
    expect(all[0]!.received_at).toBeGreaterThanOrEqual(nowSeconds() - 5);
    expect(Object.keys(all[0]!.envelope).sort()).toEqual(["payload", "sig"]);

    const after = await (await hub(`/hub/updates?after=${seqs[1]}`)).json();
    expect((after as { updates: Update[] }).updates.map((u) => u.seq)).toEqual(seqs.slice(2));

    const limited = await (await hub("/hub/updates?limit=2")).json();
    expect((limited as { updates: Update[] }).updates.map((u) => u.seq)).toEqual(seqs.slice(0, 2));
  });

  it("rejects out-of-range parameters", async () => {
    for (const query of [
      "timeout=26",
      "timeout=-1",
      "limit=0",
      "limit=101",
      "after=x",
      "after=-1",
    ]) {
      const res = await hub(`/hub/updates?${query}`);
      expect(res.status, query).toBe(400);
    }
  });

  it("waits for the timeout when nothing arrives", async () => {
    const started = Date.now();
    const res = await hub("/hub/updates?timeout=1");
    expect(await res.json()).toEqual({ updates: [] });
    expect(Date.now() - started).toBeGreaterThanOrEqual(950);
  });

  it("is woken by an inbox arrival", async () => {
    mockCards({ [`https://${PEER}`]: peerCard() });
    const started = Date.now();
    const poll = hub("/hub/updates?timeout=20");
    await new Promise((resolve) => setTimeout(resolve, 300));
    const sent = await envelope();
    expect((await postEnvelope(sent)).status).toBe(202);
    const res = await poll;
    const { updates } = (await res.json()) as { updates: Update[] };
    expect(Date.now() - started).toBeLessThan(5_000);
    expect(updates).toHaveLength(1);
    expect(updates[0]!.envelope).toEqual({ payload: sent.payload, sig: sent.sig });
  });

  it("does not wait while mail is queued", async () => {
    await queue(1);
    const started = Date.now();
    const res = await hub("/hub/updates?timeout=20");
    expect(((await res.json()) as { updates: Update[] }).updates).toHaveLength(1);
    expect(Date.now() - started).toBeLessThan(2_000);
  });
});

describe("HubSignal", () => {
  it("returns early once for mail announced before the wait, then waits", async () => {
    const signal = env.SIGNAL.getByName(SIGNAL_NAME);
    expect(await signal.notify(7)).toBe(0);
    // Mail 7 arrived after a poll with cursor 6 queried: the next wait returns at once.
    expect(await signal.wait(10_000, 6)).toBe(true);
    // A poll whose cursor lags behind acknowledged mail does not spin.
    const started = Date.now();
    expect(await signal.wait(200, 6)).toBe(false);
    expect(Date.now() - started).toBeGreaterThanOrEqual(150);
    expect(await signal.wait(100, 7)).toBe(false);
  });

  it("wakes every waiter", async () => {
    const signal = env.SIGNAL.getByName(SIGNAL_NAME);
    const waits = [signal.wait(10_000, 0), signal.wait(10_000, 0)];
    await new Promise((resolve) => setTimeout(resolve, 100));
    expect(await signal.notify(1)).toBe(2);
    expect(await Promise.all(waits)).toEqual([true, true]);
  });
});

describe("POST /hub/ack", () => {
  it("deletes acknowledged envelopes and counts only real deletions", async () => {
    const [a, b, c] = await queue(3);
    const res = await hub("/hub/ack", {
      method: "POST",
      body: { seqs: [a!.seq, c!.seq, 999_999, a!.seq] },
    });
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ deleted: 2 });
    const left = (await (await hub("/hub/updates")).json()) as { updates: Update[] };
    expect(left.updates.map((u) => u.seq)).toEqual([b!.seq]);
    expect(await (await hub("/hub/ack", { method: "POST", body: { seqs: [] } })).json()).toEqual({
      deleted: 0,
    });
  });

  it("handles more than 100 seqs in one call", async () => {
    await env.DB.prepare(
      "WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM n WHERE x < 250) " +
        "INSERT INTO mailbox (sender, envelope, received_at) SELECT 'x.example', '{}', 0 FROM n",
    ).run();
    const { results } = await env.DB.prepare("SELECT seq FROM mailbox").all<{ seq: number }>();
    const res = await hub("/hub/ack", {
      method: "POST",
      body: { seqs: results.map((r) => r.seq) },
    });
    expect(await res.json()).toEqual({ deleted: 250 });
    expect(await mailboxCount()).toBe(0);
  });

  it("400 for a bad body", async () => {
    for (const body of [{}, { seqs: "1" }, { seqs: [1.5] }, { seqs: [-1] }, { seqs: ["1"] }]) {
      expect((await hub("/hub/ack", { method: "POST", body })).status).toBe(400);
    }
  });
});

describe("local mode", () => {
  const routes: [string, string][] = [
    ["GET", "/hub/state/net.cursor"],
    ["PUT", "/hub/state/net.cursor"],
    ["GET", "/hub/files"],
    ["PUT", "/hub/files/tau.toml"],
    ["GET", "/hub/sessions"],
    ["POST", "/hub/sessions"],
    ["PATCH", "/hub/sessions/s1/meta"],
    ["GET", "/hub/brain"],
  ];
  for (const [method, path] of routes) {
    it(`${method} ${path} is 404 cloud_mode_off`, async () => {
      const res = await hub(path, { method, body: method === "GET" ? undefined : { value: 1 } });
      expect(res.status).toBe(404);
      expect(await res.json()).toEqual({ error: "cloud_mode_off" });
    });
  }

  it("still requires the token for cloud routes", async () => {
    expect((await hub("/hub/sessions", { token: null })).status).toBe(401);
  });
});

describe("cron", () => {
  it("prunes mailbox rows older than 7 days and seen rows older than 1 day", async () => {
    const now = nowSeconds();
    await env.DB.batch([
      env.DB.prepare(
        "INSERT INTO mailbox (sender, envelope, received_at) VALUES ('a.example', '{}', ?1), ('a.example', '{}', ?2)",
      ).bind(now - 8 * 86_400, now - 6 * 86_400),
      env.DB.prepare(
        "INSERT INTO seen (sender, id, ts) VALUES ('a.example', 'old-id-0000000000', ?1), ('a.example', 'new-id-0000000000', ?2)",
      ).bind(now - 2 * 86_400, now - 3_600),
    ]);
    await worker.scheduled(createScheduledController({ cron: "* * * * *" }), env);
    expect(await mailboxCount()).toBe(1);
    const seen = await env.DB.prepare("SELECT id FROM seen").all<{ id: string }>();
    expect(seen.results.map((r) => r.id)).toEqual(["new-id-0000000000"]);
  });

  it("never touches the brain in local mode", async () => {
    const health = vi.fn(async () => ({ status: 200, body: "{}" }));
    const BRAIN = { getByName: () => ({ health }) } as unknown as SpineEnv["BRAIN"];
    await worker.scheduled(createScheduledController({ cron: "* * * * *" }), {
      ...env,
      BRAIN,
      KEEP_AWAKE: "1",
    });
    expect(health).not.toHaveBeenCalled();
  });
});
