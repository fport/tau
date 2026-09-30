/**
 * Flood hardening of POST /net/inbox: the media type, the Rate Limiting bindings (per client
 * IP and per claimed sender, failing open) and a KV card cache whose failures are ignored.
 */

import { env } from "cloudflare:workers";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { SpineEnv } from "../src/env";
import worker from "../src/index";
import { clientKey } from "../src/limits";
import {
  envelope,
  mailboxCount,
  mockCards,
  nowSeconds,
  PEER,
  peerCard,
  publishCard,
  resetStore,
  SELF,
  spine,
} from "./helpers";

const PEER_URL = `https://${PEER}`;

beforeEach(async () => {
  await resetStore();
  await publishCard();
});
afterEach(() => {
  vi.restoreAllMocks();
});

/** A Rate Limiting binding that answers `success` and records the keys it was asked. */
function limiter(success: boolean | (() => never)) {
  const keys: string[] = [];
  const binding = {
    async limit({ key }: { key: string }) {
      keys.push(key);
      if (typeof success === "function") success();
      return { success };
    },
  };
  return { binding: binding as unknown as RateLimit, keys };
}

const open = () => limiter(true);

/** POST /net/inbox straight to the Worker with a modified environment. */
function post(
  body: unknown,
  overrides: Partial<SpineEnv> = {},
  headers: Record<string, string> = { "content-type": "application/json" },
): Promise<Response> {
  const request = new Request(`https://${SELF}/net/inbox`, {
    method: "POST",
    headers,
    body: typeof body === "string" ? body : JSON.stringify(body),
  });
  return worker.fetch(request, { ...env, ...overrides } as SpineEnv);
}

/** A KV namespace whose `method` throws like a namespace over its daily quota. */
function failingKv(method: "get" | "put"): KVNamespace {
  return new Proxy(env.TAU, {
    get(target, property) {
      if (property === method) {
        return async () => {
          throw new Error(`KV ${method}() limit exceeded for the day.`);
        };
      }
      const value = Reflect.get(target, property) as unknown;
      return typeof value === "function" ? value.bind(target) : value;
    },
  });
}

describe("415 unsupported_media_type", () => {
  it("refuses a body that is not declared as JSON, before reading it", async () => {
    const spy = mockCards({ [PEER_URL]: peerCard() });
    const valid = await envelope();
    const refused: Record<string, string>[] = [
      {},
      { "content-type": "text/plain" },
      { "content-type": "json" },
    ];
    for (const headers of refused) {
      const res = await post(valid, {}, headers);
      expect(res.status, JSON.stringify(headers)).toBe(415);
      expect(await res.json()).toEqual({ error: "unsupported_media_type" });
    }
    // Before the size check, too.
    expect((await post("x".repeat(70_000), {}, {})).status).toBe(415);
    expect(spy).not.toHaveBeenCalled();
    expect(await mailboxCount()).toBe(0);
  });

  it("accepts application/json with parameters, in any case", async () => {
    mockCards({ [PEER_URL]: peerCard() });
    for (const type of ["application/json; charset=utf-8", "Application/JSON"]) {
      const res = await post(await envelope(), {}, { "content-type": type });
      expect(res.status, type).toBe(202);
    }
  });
});

describe("rate limiting bindings", () => {
  it("429 per client IP before the card fetch, KV and the Mailbox", async () => {
    const spy = mockCards({ [PEER_URL]: peerCard() });
    const ip = limiter(false);
    const sender = open();
    const res = await post(
      await envelope(),
      { INBOX_IP_LIMIT: ip.binding, INBOX_SENDER_LIMIT: sender.binding },
      { "content-type": "application/json", "cf-connecting-ip": "203.0.113.7" },
    );
    expect(res.status).toBe(429);
    expect(await res.json()).toEqual({ error: "rate_limited" });
    expect(ip.keys).toEqual(["203.0.113.7"]);
    expect(sender.keys).toEqual([]);
    expect(spy).not.toHaveBeenCalled();
    expect(await env.TAU.get(`peer:${PEER}`)).toBeNull();
    expect(await mailboxCount()).toBe(0);
  });

  it("429 per claimed sender, after the IP check", async () => {
    const spy = mockCards({ [PEER_URL]: peerCard() });
    const ip = open();
    const sender = limiter(false);
    const res = await post(
      await envelope(),
      { INBOX_IP_LIMIT: ip.binding, INBOX_SENDER_LIMIT: sender.binding },
      { "content-type": "application/json", "cf-connecting-ip": "2001:db8:aa:bb:1:2:3:4" },
    );
    expect(res.status).toBe(429);
    expect(ip.keys).toEqual(["2001:db8:aa:bb::/64"]);
    expect(sender.keys).toEqual([PEER]);
    expect(spy).not.toHaveBeenCalled();
    expect(await mailboxCount()).toBe(0);
  });

  it("runs after the cheap checks: bad shape, wrong recipient and stale never count", async () => {
    const ip = limiter(false);
    const sender = limiter(false);
    const limits = { INBOX_IP_LIMIT: ip.binding, INBOX_SENDER_LIMIT: sender.binding };
    const headers = { "content-type": "application/json", "cf-connecting-ip": "203.0.113.7" };
    expect((await post("{nope", limits, headers)).status).toBe(400);
    expect((await post(await envelope({ to: "carol.example" }), limits, headers)).status).toBe(
      400,
    );
    expect((await post(await envelope({ ts: nowSeconds() - 400 }), limits, headers)).status).toBe(
      400,
    );
    expect(ip.keys).toEqual([]);
    expect(sender.keys).toEqual([]);
  });

  it("queues within both limits", async () => {
    mockCards({ [PEER_URL]: peerCard() });
    const ip = open();
    const sender = open();
    const res = await post(
      await envelope(),
      { INBOX_IP_LIMIT: ip.binding, INBOX_SENDER_LIMIT: sender.binding },
      { "content-type": "application/json", "cf-connecting-ip": "::ffff:198.51.100.9" },
    );
    expect(res.status).toBe(202);
    expect(ip.keys).toEqual(["198.51.100.9"]);
    expect(sender.keys).toEqual([PEER]);
  });

  it("skips the IP check without a client IP", async () => {
    mockCards({ [PEER_URL]: peerCard() });
    const ip = limiter(false);
    const res = await post(await envelope(), { INBOX_IP_LIMIT: ip.binding });
    expect(res.status).toBe(202);
    expect(ip.keys).toEqual([]);
  });

  it("fails open without the bindings, and logs it once", async () => {
    mockCards({ [PEER_URL]: peerCard() });
    const warn = vi.spyOn(console, "warn");
    const unbound = { INBOX_IP_LIMIT: undefined, INBOX_SENDER_LIMIT: undefined };
    const headers = { "content-type": "application/json", "cf-connecting-ip": "203.0.113.7" };
    for (let i = 0; i < 3; i++) {
      expect((await post(await envelope(), unbound, headers)).status).toBe(202);
    }
    const unboundLines = warn.mock.calls.filter((call) =>
      String(call[0]).includes("rate_limit_unbound"),
    );
    expect(unboundLines.length).toBeLessThanOrEqual(1);
    expect(await mailboxCount()).toBe(3);
  });

  it("fails open when a binding throws", async () => {
    mockCards({ [PEER_URL]: peerCard() });
    const broken = limiter(() => {
      throw new Error("rate limiter unavailable");
    });
    const res = await post(
      await envelope(),
      { INBOX_IP_LIMIT: broken.binding, INBOX_SENDER_LIMIT: broken.binding },
      { "content-type": "application/json", "cf-connecting-ip": "203.0.113.7" },
    );
    expect(res.status).toBe(202);
    expect(broken.keys).toHaveLength(2);
  });

  it("is bound in the shipped configuration", () => {
    const spineEnv = env as SpineEnv;
    expect(typeof spineEnv.INBOX_IP_LIMIT?.limit).toBe("function");
    expect(typeof spineEnv.INBOX_SENDER_LIMIT?.limit).toBe("function");
  });
});

describe("the KV card cache", () => {
  it("tolerates a failing write (the daily quota): the envelope is still queued", async () => {
    const spy = mockCards({ [PEER_URL]: peerCard() });
    const res = await post(await envelope(), { TAU: failingKv("put") });
    expect(res.status).toBe(202);
    expect(spy).toHaveBeenCalledTimes(1);
    expect(await env.TAU.get(`peer:${PEER}`)).toBeNull();
    // Nothing was cached, so the next envelope fetches the card again, and is queued too.
    expect((await post(await envelope(), { TAU: failingKv("put") })).status).toBe(202);
    expect(spy).toHaveBeenCalledTimes(2);
    expect(await mailboxCount()).toBe(2);
  });

  it("treats a failing read as a miss", async () => {
    const spy = mockCards({ [PEER_URL]: peerCard() });
    expect((await spine("/net/inbox", { method: "GET" })).status).toBe(405);
    const res = await post(await envelope(), { TAU: failingKv("get") });
    expect(res.status).toBe(202);
    expect(spy).toHaveBeenCalledTimes(1);
  });
});

describe("clientKey", () => {
  const cases: [string | null, string | null][] = [
    ["203.0.113.7", "203.0.113.7"],
    [" 203.0.113.7 ", "203.0.113.7"],
    ["2001:db8:aa:bb:1:2:3:4", "2001:db8:aa:bb::/64"],
    ["2001:DB8:00aa:0bb::1", "2001:db8:aa:bb::/64"],
    ["2001:db8::1", "2001:db8:0:0::/64"],
    ["::1", "0:0:0:0::/64"],
    ["fe80::1%eth0", "fe80:0:0:0::/64"],
    ["::ffff:198.51.100.9", "198.51.100.9"],
    ["", null],
    [null, null],
    ["not an ip", null],
    ["1:2:3:4:5:6:7:8:9", null],
    ["1::2::3", null],
  ];
  for (const [input, key] of cases) {
    it(`${JSON.stringify(input)} → ${JSON.stringify(key)}`, () => {
      expect(clientKey(input)).toBe(key);
    });
  }
});
