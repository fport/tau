/** The provider clients by name, and the key check done before a key is stored. */

import { AnthropicProvider, checkAnthropicKey } from "./anthropic";
import { FakeProvider } from "./fake";
import { checkGeminiKey, GeminiProvider } from "./gemini";
import { checkOpenAIKey, OpenAIProvider } from "./openai";
import type { Provider, ProviderName } from "./types";

export * from "./types";

export const PROVIDER_NAMES: readonly ProviderName[] = ["anthropic", "openai", "gemini", "fake"];

export function isProviderName(value: unknown): value is ProviderName {
  return typeof value === "string" && (PROVIDER_NAMES as readonly string[]).includes(value);
}

export function providerFor(name: ProviderName, key: string): Provider {
  switch (name) {
    case "anthropic":
      return new AnthropicProvider(key);
    case "openai":
      return new OpenAIProvider(key);
    case "gemini":
      return new GeminiProvider(key);
    case "fake":
      return new FakeProvider();
  }
}

/** A key's shape before anything is sent: printable ASCII without spaces, 8–512 characters. */
export function plausibleKey(key: string): boolean {
  return /^[\x21-\x7e]{8,512}$/.test(key);
}

export type KeyCheck = { ok: true } | { ok: false; reason: "invalid" | "unreachable" };

/**
 * One small request that proves `key` works with `provider` (ADR 0013 §2): the provider's
 * models list, which costs nothing. 2xx and 429 (throttled, but authenticated) pass; 401
 * and 403 mean the key is wrong; anything else means the check could not be done. The key
 * is never logged and never part of the result.
 */
export async function checkKey(provider: ProviderName, key: string): Promise<KeyCheck> {
  if (provider === "fake") return { ok: true };
  let response: Response;
  try {
    response =
      provider === "anthropic"
        ? await checkAnthropicKey(key)
        : provider === "openai"
          ? await checkOpenAIKey(key)
          : await checkGeminiKey(key);
  } catch {
    return { ok: false, reason: "unreachable" };
  }
  await response.body?.cancel();
  if (response.ok || response.status === 429) return { ok: true };
  // Gemini answers a bad key with 400 API_KEY_INVALID.
  if (response.status === 401 || response.status === 403 || response.status === 400) {
    return { ok: false, reason: "invalid" };
  }
  return { ok: false, reason: "unreachable" };
}
