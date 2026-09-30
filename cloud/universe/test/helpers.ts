/** Shared fixtures: two test taus, signing, requests to the universe, mocked cards. */

import { env, exports } from "cloudflare:workers";
import { vi } from "vitest";
import { b64uDecode, b64uEncode } from "../src/crypto";
import { directoryOf } from "../src/env";

/** The universe under test answers as this host (UNIVERSE is empty in the tests). */
export const UNIVERSE = "universe.example";

/**
 * Two taus. Alice signs with the seed of the network reference's test vector (bytes
 * 0x00..0x1f), Bob with bytes 0x20..0x3f, Carol with 0x40..0x5f.
 */
export const ALICE = {
  address: "alice.example",
  name: "Alice's tau",
  seed: "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8",
  signKey: "A6EHv_POEL4dcN0Y50vAmWfk1jCbpQ1fHdyGZBJVMbg",
};
export const BOB = {
  address: "bob.example",
  name: "Bob's tau",
  seed: "ICEiIyQlJicoKSorLC0uLzAxMjM0NTY3ODk6Ozw9Pj8",
  signKey: "",
};
export const CAROL = {
  address: "carol.example",
  name: "Carol's tau",
  seed: "QEFCQ0RFRkdISUpLTE1OT1BRUlNUVVZXWFlaW1xdXl8",
  signKey: "",
};
export type Tau = typeof ALICE;

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

/** Fills in the public keys of the test taus. */
export async function prepareTaus(): Promise<void> {
  BOB.signKey = await publicKeyOf(BOB.seed);
  CAROL.signKey = await publicKeyOf(CAROL.seed);
}

export function nowSeconds(): number {
  return Math.floor(Date.now() / 1000);
}

// Each address gets strictly increasing timestamps, as a real hub would send.
const lastTs = new Map<string, number>();

export function nextTs(address: string): number {
  const ts = Math.max(nowSeconds(), (lastTs.get(address) ?? 0) + 1);
  lastTs.set(address, ts);
  return ts;
}

export function resetClocks(): void {
  lastTs.clear();
}

export interface Wire {
  payload: string;
  sig: string;
}

/** Signs exact payload bytes: `sig = Ed25519(context + payload)`. */
export async function signRaw(
  payloadBytes: Uint8Array,
  seed: string,
  context = "tau-universe/1\n",
): Promise<Wire> {
  const key = await signingKey(seed);
  const message = new Uint8Array([...new TextEncoder().encode(context), ...payloadBytes]);
  const sig = new Uint8Array(await crypto.subtle.sign({ name: "Ed25519" }, key, message));
  return { payload: b64uEncode(payloadBytes), sig: b64uEncode(sig) };
}

/** The payload of a request (defaults: v 1, this universe, the tau's address, a fresh ts). */
export function payloadOf(
  kind: string,
  tau: Tau,
  overrides: Record<string, unknown> = {},
): Record<string, unknown> {
  const base: Record<string, unknown> = {
    v: 1,
    kind,
    universe: UNIVERSE,
    address: tau.address,
    ts: "ts" in overrides ? overrides.ts : nextTs(tau.address),
  };
  if (kind === "join") Object.assign(base, { owner: "", about: "" });
  if (kind === "report") base.links = [];
  return { ...base, ...overrides };
}

/** A signed request body. */
export async function signed(
  kind: string,
  tau: Tau,
  overrides: Record<string, unknown> = {},
  seed: string = tau.seed,
): Promise<Wire> {
  const payload = payloadOf(kind, tau, overrides);
  return signRaw(new TextEncoder().encode(JSON.stringify(payload)), seed);
}

/** A request to the universe under test, as https://universe.example. */
export function universe(path: string, init?: RequestInit): Promise<Response> {
  return exports.default.fetch(new Request(`https://${UNIVERSE}${path}`, init));
}

export function post(path: string, body: unknown): Promise<Response> {
  return universe(path, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: typeof body === "string" ? body : JSON.stringify(body),
  });
}

/** Signs and posts a request to `/api/<kind>`. */
export async function send(
  kind: "join" | "report" | "leave",
  tau: Tau,
  overrides: Record<string, unknown> = {},
): Promise<Response> {
  return post(`/api/${kind}`, await signed(kind, tau, overrides));
}

export function card(tau: Tau, extra: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    v: 1,
    address: tau.address,
    name: tau.name,
    sign_key: tau.signKey,
    box_key: "NYBy1jZYgNGu6jKa35EhODhR7SGijjt16WXQ0s0WYlQ",
    inbox: `https://${tau.address}/net/inbox`,
    software: "tau-spine/0.1.0",
    ...extra,
  };
}

type CardAnswer = Record<string, unknown> | Response | (() => Response | Promise<Response>);

/**
 * Replaces outbound fetch: `<base>/.well-known/tau.json` answers with the given card (or
 * Response); every other URL fails. Returns the spy to inspect calls.
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

/** Cards for the given taus at https://<address>. */
export function mockTaus(...taus: Tau[]) {
  return mockCards(Object.fromEntries(taus.map((tau) => [`https://${tau.address}`, card(tau)])));
}

export function directory() {
  return directoryOf(env);
}

export interface SnapshotBody {
  universe: string;
  generated_at: number;
  stats: { taus: number; online: number; messages: number };
  taus: {
    address: string;
    name: string;
    owner: string;
    about: string;
    joined_at: number;
    last_seen: number;
    online: boolean;
  }[];
  links: { a: string; b: string; messages: number }[];
}

export async function snapshot(): Promise<SnapshotBody> {
  const res = await universe("/api/universe");
  if (res.status !== 200) throw new Error(`snapshot: ${res.status}`);
  return (await res.json()) as SnapshotBody;
}
