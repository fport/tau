/**
 * The universe's own network identity (ADR 0013 §5; §5 of docs/reference/tau-universe.md).
 *
 * A visitor of a web sub-tau that runs on a hub has no key and no card, so the universe
 * relays the visitor's messages under its own identity: the secret `UNIVERSE_IDENTITY`, in
 * tau-net's `TAU_NET_IDENTITY` form (the identity JSON, base64url-encoded; `pnpm run
 * identity` makes one). Its card is served at `/.well-known/tau.json` with the universe's
 * host as the address, and hubs pin its keys at the first visit.
 *
 * Without the secret, or with one that cannot be read, the universe has no card (404), its
 * inbox answers 503 and visitors reach only hosted sub-taus. The secret never appears in a
 * log line or a response.
 */

import { Identity, isPlainAddress, makeCard } from "../../shared/net/index.ts";
import { insecurePeersAllowed, universeHost } from "./address";
import type { UniverseEnv } from "./env";
import { json, methodNotAllowed } from "./http";
import { warnOnce } from "./limits";
import { SOFTWARE } from "./version";

/** The name on the universe's card. */
export const UNIVERSE_NAME = "tau universe";

const CARD_HEADERS = {
  "access-control-allow-origin": "*",
  "cache-control": "public, max-age=300",
};

/**
 * The parsed identity of the current secret, per isolate: parsing imports two WebCrypto
 * keys, which every relayed visit and every inbox delivery would otherwise repeat. Only the
 * settled result is kept (never a promise shared between requests); a new secret value
 * replaces it.
 */
let cached: { value: string; identity: Identity | null } | null = null;

/** The universe's identity, or null when `UNIVERSE_IDENTITY` is not set or not readable. */
export async function universeIdentity(env: UniverseEnv): Promise<Identity | null> {
  const value = (env.UNIVERSE_IDENTITY ?? "").trim();
  if (value === "") return null;
  if (cached?.value === value) return cached.identity;
  let identity: Identity | null;
  try {
    identity = await Identity.fromEnvValue(value);
  } catch (err) {
    // IdentityError messages never contain a seed.
    warnOnce("identity_invalid", {
      detail: err instanceof Error ? err.message : "UNIVERSE_IDENTITY cannot be read",
    });
    identity = null;
  }
  cached = { value, identity };
  return identity;
}

/** GET /.well-known/tau.json: the universe's card, or 404 `no_card` without an identity. */
export async function serveCard(request: Request, env: UniverseEnv, url: URL): Promise<Response> {
  if (request.method !== "GET" && request.method !== "HEAD") {
    return methodNotAllowed(["GET", "HEAD"]);
  }
  const identity = await universeIdentity(env);
  const self = universeHost(env, url);
  if (identity === null || !isPlainAddress(self)) {
    return json({ error: "no_card" }, 404, { "access-control-allow-origin": "*" });
  }
  const card = makeCard({
    address: self,
    name: UNIVERSE_NAME,
    signKey: identity.signKey,
    boxKey: identity.boxKey,
    software: SOFTWARE,
    allowInsecure: insecurePeersAllowed(env),
  });
  return json(card, 200, CARD_HEADERS);
}
