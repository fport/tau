/**
 * Fixtures of the network tests: the protocol vectors tau-net wrote (cloud/shared/net/
 * vectors.json), identities, cards, envelopes to post, and envelopes to open.
 */

import { env, runInDurableObject } from "cloudflare:test";
import {
  buildEnvelope,
  type Card,
  Identity,
  makeCard,
  openEnvelope,
  type OpenedEnvelope,
  type WireEnvelope,
} from "../../shared/net/index.ts";
import vectors from "../../shared/net/vectors.json";
import { seal } from "../src/vault";
import { api, HOST, onboardedOwner, type Owner, request, type Seen, tau } from "./helpers";

export { vectors };

/** The time the vectors were made at (they are within the inbox's clock window then). */
export const VECTOR_TS = 1_790_000_000;

export type VectorLabel = keyof typeof vectors.identities;

export function identityOf(label: VectorLabel): Promise<Identity> {
  return Identity.fromJson(vectors.identities[label].identity);
}

/** A tau-net envelope of the `hosted` vectors (a hub and the universe write to bob). */
export function hostedEnvelope(name: string): { envelope: WireEnvelope; payload: { id: string; thread: string; hops: number } } {
  const found = vectors.hosted.envelopes.find((vector) => vector.name === name);
  if (found === undefined) throw new Error(`no hosted vector ${name}`);
  return { envelope: found.envelope, payload: found.payload };
}

/** The card a tau with this identity serves at `address`. */
export function cardFor(identity: Identity, address: string, name = "a tau"): Card {
  return makeCard({ address, name, signKey: identity.signKey, boxKey: identity.boxKey, software: "tau-spine/0.2.0" });
}

/** Gives a hosted tau a known identity (before anything made one), sealed like its own. */
export async function seedIdentity(handle: string, identity: { v: number; sign_seed: string; box_seed: string }): Promise<void> {
  const sealed = await seal(env.VAULT_KEY, handle, "net_key", JSON.stringify(identity));
  await runInDurableObject(tau(handle), (_instance, state) => {
    state.storage.sql.exec(
      "INSERT INTO settings (key, value) VALUES ('net_identity', ?) ON CONFLICT (key) DO UPDATE SET value = excluded.value",
      JSON.stringify(sealed),
    );
  });
}

/**
 * Writes settings of a tau directly, without the side effects of the settings API (the
 * universe choice schedules a join, which a test with a clock in the past would run at once).
 */
export async function setSettings(handle: string, values: Record<string, unknown>): Promise<void> {
  await runInDurableObject(tau(handle), (_instance, state) => {
    for (const [key, value] of Object.entries(values)) {
      state.storage.sql.exec(
        "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT (key) DO UPDATE SET value = excluded.value",
        key,
        JSON.stringify(value),
      );
    }
  });
}

/** An onboarded owner whose app calls go to the public host (so its address is HOST's). */
export async function hostedOwner(login: string, universe = false): Promise<Owner> {
  const owner = await onboardedOwner(login, universe);
  return { ...owner, base: HOST };
}

/** POST an envelope to a hosted tau's inbox. */
export function postEnvelope(handle: string, envelope: unknown, headers: Record<string, string> = {}, base = HOST): Promise<Response> {
  return request(base, `/@${handle}/net/inbox`, {
    method: "POST",
    headers: { "content-type": "application/json", ...headers },
    body: typeof envelope === "string" ? envelope : JSON.stringify(envelope),
  });
}

/** Posts, then waits until the tau handled it. */
export async function deliver(handle: string, envelope: unknown): Promise<Response> {
  const response = await postEnvelope(handle, envelope);
  await tau(handle).settle();
  return response;
}

/** The envelopes a mock inbox received, opened by their recipient. */
export async function opened(seen: Seen[], inbox: string, recipient: Identity, senderSignKey: string): Promise<OpenedEnvelope[]> {
  const out: OpenedEnvelope[] = [];
  for (const entry of seen.filter((s) => s.url === inbox && s.method === "POST")) {
    out.push(await openEnvelope(JSON.parse(entry.body) as WireEnvelope, senderSignKey, recipient));
  }
  return out;
}

/** An envelope from `from` (with `identity`) to a hosted tau, built by the shared TypeScript. */
export async function envelopeTo(
  identity: Identity,
  options: { from: string; to: string; boxKey: string; kind: "contact_request" | "contact_accept" | "message" | "visit"; content: Record<string, unknown>; hops?: number; thread?: string; replyTo?: string; ts?: number; id?: string },
): Promise<WireEnvelope> {
  const built = await buildEnvelope(identity, {
    from: options.from,
    to: options.to,
    recipientBoxKey: options.boxKey,
    kind: options.kind,
    content: options.content,
    hops: options.hops,
    thread: options.thread,
    replyTo: options.replyTo ?? null,
    ts: options.ts,
    id: options.id,
  });
  return built.envelope;
}

/** The hosted tau's own card, as anyone fetches it. */
export async function hostedCard(handle: string, base = HOST): Promise<Card> {
  const response = await request(base, `/@${handle}/.well-known/tau.json`);
  if (response.status !== 200) throw new Error(`card of ${handle}: ${response.status}`);
  return (await response.json()) as Card;
}

/** Decides an approval card in the app; the NDJSON lines of the answer. */
export async function decide(owner: Owner, id: string, decision: "approve" | "deny") {
  const response = await api(owner, "POST", `/api/host/approvals/${id}`, { decision });
  const text = await response.text();
  return text
    .split("\n")
    .filter((line) => line.trim())
    .map((line) => JSON.parse(line) as Record<string, unknown>);
}
