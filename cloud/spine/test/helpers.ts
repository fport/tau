/** Shared fixtures: the §3 test vector, signing, requests to the spine, store resets. */

import { abortAllDurableObjects, runInDurableObject } from "cloudflare:test";
import { env, exports } from "cloudflare:workers";
import { vi } from "vitest";
import { b64uDecode, b64uEncode } from "../src/crypto";
import type { SpineEnv } from "../src/env";
import { type Mailbox, mailboxOf } from "../src/mailbox";

export const TOKEN = "test-hub-token";

/** The spine under test answers as this address (the host of the request URL). */
export const SELF = "bob.example";
export const PEER = "alice.example";

/** §3 test vector. */
export const VECTOR = {
  signSeed: "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8",
  signKey: "A6EHv_POEL4dcN0Y50vAmWfk1jCbpQ1fHdyGZBJVMbg",
  payload:
    "eyJ2IjoxLCJpZCI6IjAxSjAwMDAwMDAwMDAwMDAwMDAwMDBURVNUIiwia2luZCI6Im1lc3NhZ2UiLCJmcm9tIjoiYWxpY2UuZXhhbXBsZSIsInRvIjoiYm9iLmV4YW1wbGUiLCJ0cyI6MTc5MDAwMDAwMCwidGhyZWFkIjoiMDFKMDAwMDAwMDAwMDAwMDAwMDAwMFRFU1QiLCJyZXBseV90byI6bnVsbCwiaG9wcyI6MCwiYm94Ijp7ImVwayI6IkFBQUEiLCJub25jZSI6IkFBQUFBQUFBQUFBQUFBQUEiLCJjdCI6IkFBQUEifX0",
  sig: "i5FlOZ4PsX_WU1zPYN7jG7nFGns4HZl2Il6w5l6C74AB04RR73X0v3L-TOHYODQwgQ-GrzBAOpavFfVlDx1kBQ",
  boxSeed: "ICEiIyQlJicoKSorLC0uLzAxMjM0NTY3ODk6Ozw9Pj8",
  boxKey: "NYBy1jZYgNGu6jKa35EhODhR7SGijjt16WXQ0s0WYlQ",
  decoded:
    '{"v":1,"id":"01J0000000000000000000TEST","kind":"message","from":"alice.example","to":"bob.example","ts":1790000000,"thread":"01J0000000000000000000TEST","reply_to":null,"hops":0,"box":{"epk":"AAAA","nonce":"AAAAAAAAAAAAAAAA","ct":"AAAA"}}',
} as const;

const PKCS8_ED25519_PREFIX = "302e020100300506032b657004220420";

function hexToBytes(hex: string): Uint8Array {
  const out = new Uint8Array(hex.length / 2);
  for (let i = 0; i < out.length; i++) out[i] = parseInt(hex.slice(i * 2, i * 2 + 2), 16);
  return out;
}

/** An Ed25519 private key from a 32-byte seed (PKCS#8 = fixed prefix + seed). */
export async function signingKey(seed: string, extractable = false): Promise<CryptoKey> {
  const raw = b64uDecode(seed);
  if (raw === null || raw.length !== 32) throw new Error("seed must be b64u of 32 bytes");
  const pkcs8 = new Uint8Array([...hexToBytes(PKCS8_ED25519_PREFIX), ...raw]);
  return crypto.subtle.importKey("pkcs8", pkcs8, { name: "Ed25519" }, extractable, ["sign"]);
}

/** The b64u public key of a seed. */
export async function publicKeyOf(seed: string): Promise<string> {
  const key = await signingKey(seed, true);
  const jwk = (await crypto.subtle.exportKey("jwk", key)) as JsonWebKey;
  if (jwk.x === undefined) throw new Error("no public key in JWK");
  return jwk.x;
}

let counter = 0;

/** A fresh envelope id (16–64 of [A-Za-z0-9_-]). */
export function newId(): string {
  counter += 1;
  return `test-${Date.now()}-${counter}`.padEnd(20, "x");
}

export function nowSeconds(): number {
  return Math.floor(Date.now() / 1000);
}

export interface Envelope {
  payload: string;
  sig: string;
}

/** Signs a payload object (defaults: a fresh message from PEER to SELF, now). */
export async function envelope(
  overrides: Record<string, unknown> = {},
  seed: string = VECTOR.signSeed,
): Promise<Envelope & { id: string }> {
  const id = typeof overrides.id === "string" ? overrides.id : newId();
  const payload = {
    v: 1,
    id,
    kind: "message",
    from: PEER,
    to: SELF,
    ts: nowSeconds(),
    thread: id,
    reply_to: null,
    hops: 0,
    box: { epk: "AAAA", nonce: "AAAAAAAAAAAAAAAA", ct: "AAAA" },
    ...overrides,
  };
  return { ...(await signRaw(new TextEncoder().encode(JSON.stringify(payload)), seed)), id };
}

/** Signs exact payload bytes: `sig = Ed25519(b"tau-net/1\n" + payload)`. */
export async function signRaw(
  payloadBytes: Uint8Array,
  seed: string = VECTOR.signSeed,
): Promise<Envelope> {
  const key = await signingKey(seed);
  const message = new Uint8Array([...new TextEncoder().encode("tau-net/1\n"), ...payloadBytes]);
  const sig = new Uint8Array(await crypto.subtle.sign({ name: "Ed25519" }, key, message));
  return { payload: b64uEncode(payloadBytes), sig: b64uEncode(sig) };
}

/** A request to the spine under test, as https://bob.example. */
export function spine(path: string, init?: RequestInit, host: string = SELF): Promise<Response> {
  return exports.default.fetch(new Request(`https://${host}${path}`, init));
}

/** A hub API request with the bearer token (and a JSON body when given). */
export function hub(
  path: string,
  init: { method?: string; body?: unknown; raw?: BodyInit; token?: string | null } = {},
): Promise<Response> {
  const headers: Record<string, string> = {};
  if (init.token !== null) headers.authorization = `Bearer ${init.token ?? TOKEN}`;
  let body: BodyInit | undefined = init.raw;
  if (init.body !== undefined) {
    headers["content-type"] = "application/json";
    body = JSON.stringify(init.body);
  }
  return spine(path, { method: init.method ?? "GET", headers, body });
}

export function postEnvelope(body: unknown): Promise<Response> {
  return spine("/net/inbox", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: typeof body === "string" ? body : JSON.stringify(body),
  });
}

/** A valid peer card for `address` (defaults to the vector keys). */
export function peerCard(
  address: string = PEER,
  signKey: string = VECTOR.signKey,
): Record<string, unknown> {
  return {
    v: 1,
    address,
    name: "Alice's tau",
    sign_key: signKey,
    box_key: VECTOR.boxKey,
    inbox: `https://${address}/net/inbox`,
    software: "tau-spine/0.2.0",
  };
}

type CardAnswer = Record<string, unknown> | Response | (() => Response | Promise<Response>);

/**
 * Replaces outbound fetch: `https://<address>/.well-known/tau.json` answers with the given
 * card (or Response); every other URL fails. Returns the spy to count calls.
 */
export function mockCards(cards: Record<string, CardAnswer>) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = input instanceof Request ? input.url : String(input);
    for (const [base, answer] of Object.entries(cards)) {
      if (url === `${base}/.well-known/tau.json`) {
        if (typeof answer === "function") return answer();
        if (answer instanceof Response) return answer.clone();
        return Response.json(answer);
      }
    }
    throw new TypeError(`unexpected fetch in test: ${url}`);
  });
}

/** The spine's Mailbox Durable Object. */
export function mailboxStub(): DurableObjectStub<Mailbox> {
  return mailboxOf(env);
}

/** Runs `fn` on the Mailbox's own SQLite storage (to seed or inspect rows). */
export async function inMailbox<T>(fn: (sql: SqlStorage) => T): Promise<T> {
  return runInDurableObject(mailboxStub(), (_instance, state) => fn(state.storage.sql));
}

/**
 * Empties the Mailbox's storage, every D1 table (cloud project only) and every KV key, and
 * resets Durable Object instances (the Mailbox creates its tables again on its next call).
 */
export async function resetStore(): Promise<void> {
  await runInDurableObject(mailboxStub(), (_instance, state) => state.storage.deleteAll());
  const db = (env as SpineEnv).DB;
  if (db !== undefined) {
    await db.batch(
      ["state", "sessions", "agents", "messages", "events"].map((table) =>
        db.prepare(`DELETE FROM ${table}`),
      ),
    );
  }
  let cursor: string | undefined;
  do {
    const page = await env.TAU.list(cursor === undefined ? {} : { cursor });
    await Promise.all(page.keys.map((key) => env.TAU.delete(key.name)));
    cursor = page.list_complete ? undefined : page.cursor;
  } while (cursor !== undefined);
  await abortAllDurableObjects();
}

/** Publishes the vector keys as this spine's card. */
export async function publishCard(name = "Bob's tau"): Promise<Response> {
  return hub("/hub/card", {
    method: "PUT",
    body: { name, sign_key: VECTOR.signKey, box_key: VECTOR.boxKey },
  });
}

export async function mailboxCount(): Promise<number> {
  return mailboxStub().depth();
}
