/**
 * Fetching a tau's card (§2 of docs/reference/tau-network.md), the way the spine fetches a
 * sender's card: `GET <scheme>://<address>/.well-known/tau.json`, 5 s, at most 8 KiB, no
 * redirects, `v == 1`, `address` equal to the requested one, a 32-byte `sign_key`.
 *
 * There is no card cache. A tau sends about one request an hour (its report), so a cache
 * of the spine's one hour would almost never hit, and without one a new key or a new card
 * name counts from the very next request. The replay and clock checks run before the fetch,
 * so a replayed request never triggers one.
 */

import { baseUrl, insecurePeersAllowed } from "./address";
import { b64uKey } from "./crypto";
import type { UniverseEnv } from "./env";
import { isObject, parseJson, readLimited, utf8 } from "./http";
import { MAX_NAME_CHARS, sanitizeText } from "./protocol";
import { SOFTWARE } from "./version";

export const MAX_CARD_BYTES = 8_192;
export const CARD_FETCH_TIMEOUT_MS = 5_000;

export interface TauCard {
  /** Sanitised display name (the card's `name`). */
  name: string;
  /** The card's `sign_key`, b64u, and its 32 raw bytes. */
  signKey: string;
  signKeyBytes: Uint8Array;
}

/** A card is usable when `v == 1`, its address is the tau's and its sign_key is 32 bytes. */
export function usableCard(card: unknown, address: string): TauCard | null {
  if (!isObject(card) || card.v !== 1 || card.address !== address) return null;
  const signKeyBytes = b64uKey(card.sign_key);
  if (signKeyBytes === null || typeof card.sign_key !== "string") return null;
  if (typeof card.name !== "string") return null;
  const name = sanitizeText(card.name, MAX_NAME_CHARS);
  return { name: name === "" ? address : name, signKey: card.sign_key, signKeyBytes };
}

/** The tau's card, or null when it cannot be fetched or is not usable. */
export async function fetchCard(env: UniverseEnv, address: string): Promise<TauCard | null> {
  const url = `${baseUrl(address, insecurePeersAllowed(env))}/.well-known/tau.json`;
  let card: unknown;
  try {
    const response = await fetch(url, {
      headers: { accept: "application/json", "user-agent": SOFTWARE },
      redirect: "manual",
      signal: AbortSignal.timeout(CARD_FETCH_TIMEOUT_MS),
    });
    if (response.status !== 200) {
      await response.body?.cancel();
      return null;
    }
    const bytes = await readLimited(
      response.body,
      MAX_CARD_BYTES,
      response.headers.get("content-length"),
    );
    const text = bytes === null ? null : utf8(bytes);
    card = text === null ? undefined : parseJson(text);
  } catch (err) {
    console.warn(JSON.stringify({ event: "card_fetch_failed", address, error: String(err) }));
    return null;
  }
  return usableCard(card, address);
}
