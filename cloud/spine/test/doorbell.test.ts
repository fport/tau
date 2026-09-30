/** GET /hub/ws: the hub's doorbell on the Mailbox, with the WebSocket Hibernation API. */

import { runInDurableObject } from "cloudflare:test";
import { env } from "cloudflare:workers";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { SpineEnv } from "../src/env";
import worker from "../src/index";
import { MAX_DOORBELLS } from "../src/mailbox";
import {
  envelope,
  hub,
  mailboxStub,
  mockCards,
  PEER,
  peerCard,
  postEnvelope,
  publishCard,
  resetStore,
  SELF,
  spine,
  TOKEN,
} from "./helpers";

beforeEach(resetStore);
afterEach(() => {
  vi.restoreAllMocks();
});

/** The messages of a client socket, in order; `next()` waits for the next one. */
class Inbox {
  private readonly queue: string[] = [];
  private readonly waiting: ((text: string) => void)[] = [];
  closed: { code: number; reason: string } | null = null;

  constructor(readonly ws: WebSocket) {
    ws.addEventListener("message", (event) => {
      const text = typeof event.data === "string" ? event.data : "<binary>";
      const waiter = this.waiting.shift();
      if (waiter) waiter(text);
      else this.queue.push(text);
    });
    ws.addEventListener("close", (event) => {
      this.closed = { code: event.code, reason: event.reason };
    });
    ws.accept();
  }

  next(ms = 3_000): Promise<string> {
    const queued = this.queue.shift();
    if (queued !== undefined) return Promise.resolve(queued);
    return new Promise((resolve, reject) => {
      const waiter = (text: string): void => {
        clearTimeout(timer);
        resolve(text);
      };
      const timer = setTimeout(() => {
        this.waiting.splice(this.waiting.indexOf(waiter), 1);
        reject(new Error(`no message within ${ms} ms`));
      }, ms);
      this.waiting.push(waiter);
    });
  }

  async json(ms?: number): Promise<unknown> {
    return JSON.parse(await this.next(ms)) as unknown;
  }

  /** Nothing arrives within `ms`. */
  async quiet(ms = 300): Promise<boolean> {
    try {
      await this.next(ms);
      return false;
    } catch {
      return true;
    }
  }
}

const UPGRADE = { upgrade: "websocket" };

function upgrade(headers: Record<string, string> = { authorization: `Bearer ${TOKEN}` }) {
  return spine("/hub/ws", { headers: { ...UPGRADE, ...headers } });
}

async function connect(): Promise<Inbox> {
  const res = await upgrade();
  expect(res.status).toBe(101);
  expect(res.webSocket).not.toBeNull();
  return new Inbox(res.webSocket!);
}

describe("GET /hub/ws", () => {
  it("401 without or with a wrong token, before any upgrade", async () => {
    const denied: Record<string, string>[] = [{}, { authorization: "Bearer wrong" }];
    for (const headers of denied) {
      const res = await upgrade(headers);
      expect(res.status).toBe(401);
      expect(res.webSocket).toBeNull();
      expect(await res.json()).toEqual({ error: "unauthorized" });
    }
  });

  it("503 not_configured without a HUB_TOKEN secret", async () => {
    const request = new Request(`https://${SELF}/hub/ws`, {
      headers: { ...UPGRADE, authorization: "Bearer anything" },
    });
    const res = await worker.fetch(request, { ...env, HUB_TOKEN: undefined } as SpineEnv);
    expect(res.status).toBe(503);
    expect(await res.json()).toEqual({ error: "not_configured" });
  });

  it("426 upgrade_required for a plain request", async () => {
    const res = await hub("/hub/ws");
    expect(res.status).toBe(426);
    expect(res.headers.get("upgrade")).toBe("websocket");
    expect(await res.json()).toEqual({ error: "upgrade_required" });
  });

  it("405 for other methods", async () => {
    const res = await hub("/hub/ws", { method: "POST", body: {} });
    expect(res.status).toBe(405);
    expect(res.headers.get("allow")).toBe("GET");
  });

  it("says hello with the mailbox depth on connect", async () => {
    const empty = await connect();
    expect(await empty.json()).toEqual({ type: "hello", depth: 0 });
    empty.ws.close(1000, "done");

    await publishCard();
    mockCards({ [`https://${PEER}`]: peerCard() });
    for (let i = 0; i < 2; i++) expect((await postEnvelope(await envelope())).status).toBe(202);
    const busy = await connect();
    expect(await busy.json()).toEqual({ type: "hello", depth: 2 });
    busy.ws.close(1000, "done");
  });

  it("rings every doorbell when an envelope is queued, and only then", async () => {
    await publishCard();
    mockCards({ [`https://${PEER}`]: peerCard() });
    const a = await connect();
    const b = await connect();
    await a.next();
    await b.next(); // the hellos

    const first = await envelope();
    expect((await postEnvelope(first)).status).toBe(202);
    expect(await a.json()).toEqual({ type: "mail", depth: 1 });
    expect(await b.json()).toEqual({ type: "mail", depth: 1 });

    // A duplicate or a rejected envelope stores nothing and rings nothing.
    expect((await postEnvelope(first)).status).toBe(200);
    expect((await postEnvelope(await envelope({ to: "carol.example" }))).status).toBe(400);
    expect(await a.quiet()).toBe(true);

    // The doorbell never carries envelopes: the hub fetches them over HTTP.
    expect((await postEnvelope(await envelope())).status).toBe(202);
    expect(await a.json()).toEqual({ type: "mail", depth: 2 });
    const updates = (await (await hub("/hub/updates?timeout=0")).json()) as {
      updates: { seq: number }[];
    };
    expect(updates.updates).toHaveLength(2);
    a.ws.close(1000, "done");
    b.ws.close(1000, "done");
  });

  it("answers ping with pong through the auto-response, without the handler", async () => {
    const doorbell = await connect();
    await doorbell.next(); // hello
    doorbell.ws.send("ping");
    expect(await doorbell.next()).toBe("pong");
    const answered = await runInDurableObject(mailboxStub(), (_instance, state) => {
      expect(state.getWebSocketAutoResponse()?.request).toBe("ping");
      expect(state.getWebSocketAutoResponse()?.response).toBe("pong");
      return state.getWebSockets().map((ws) => state.getWebSocketAutoResponseTimestamp(ws));
    });
    expect(answered).toHaveLength(1);
    expect(answered[0]).toBeInstanceOf(Date);
    doorbell.ws.close(1000, "done");
  });

  it("ignores anything else the hub sends", async () => {
    const doorbell = await connect();
    await doorbell.next();
    doorbell.ws.send('{"type":"ack","seqs":[1]}');
    expect(await doorbell.quiet()).toBe(true);
    doorbell.ws.send("ping");
    expect(await doorbell.next()).toBe("pong");
    doorbell.ws.close(1000, "done");
  });

  it(`keeps at most ${MAX_DOORBELLS} doorbells, closing the oldest`, async () => {
    const sockets: Inbox[] = [];
    for (let i = 0; i <= MAX_DOORBELLS; i++) {
      sockets.push(await connect());
      await sockets[i]!.next();
      await new Promise((resolve) => setTimeout(resolve, 5)); // distinct accept times
    }
    await vi.waitFor(() => expect(sockets[0]!.closed?.code).toBe(1008), { timeout: 2_000 });
    expect(sockets.slice(1).every((s) => s.closed === null)).toBe(true);
    const open = await runInDurableObject(mailboxStub(), (_i, state) => state.getWebSockets());
    expect(open.length).toBeLessThanOrEqual(MAX_DOORBELLS + 1);
    for (const s of sockets.slice(1)) s.ws.close(1000, "done");
  });

  it("leaves the long poll working next to a doorbell", async () => {
    await publishCard();
    mockCards({ [`https://${PEER}`]: peerCard() });
    const doorbell = await connect();
    await doorbell.next();
    const poll = hub("/hub/updates?timeout=20");
    await new Promise((resolve) => setTimeout(resolve, 200));
    expect((await postEnvelope(await envelope())).status).toBe(202);
    const { updates } = (await (await poll).json()) as { updates: unknown[] };
    expect(updates).toHaveLength(1);
    expect(await doorbell.json()).toEqual({ type: "mail", depth: 1 });
    doorbell.ws.close(1000, "done");
  });
});
