/**
 * src/generated/ is data from tau-core (ADR 0013 §2): each file carries the SHA-256 of the
 * template it was made from, so a template changed without `pnpm run generate` fails here
 * (and in `pnpm run check-generated`, which compares the whole files).
 */

import { describe, expect, it } from "vitest";
import { MODELS, MODELS_SOURCE_SHA256 } from "../src/generated/models";
import { DEFAULT_PERSONA, PERSONA_SOURCE_SHA256 } from "../src/generated/persona";
import { PRICES, PRICES_SOURCE_SHA256 } from "../src/generated/prices";
import { sha256 } from "../src/crypto";
import modelsToml from "../../../packages/tau-core/src/tau_core/templates/models.toml?raw";
import personaMd from "../../../packages/tau-core/src/tau_core/templates/persona.md?raw";
import pricesToml from "../../../packages/tau-core/src/tau_core/templates/prices.toml?raw";

async function hex(text: string): Promise<string> {
  return [...(await sha256(text))].map((b) => b.toString(16).padStart(2, "0")).join("");
}

describe("generated data", () => {
  it("is fresh: generated from the current tau-core templates", async () => {
    expect(await hex(modelsToml)).toBe(MODELS_SOURCE_SHA256);
    expect(await hex(pricesToml)).toBe(PRICES_SOURCE_SHA256);
    expect(await hex(personaMd)).toBe(PERSONA_SOURCE_SHA256);
    expect(DEFAULT_PERSONA).toBe(personaMd);
  });

  it("has brain and fast ids for every hosted provider, each with a price", () => {
    for (const provider of ["anthropic", "openai", "gemini"]) {
      const roles = MODELS[provider];
      expect(roles).toBeDefined();
      for (const id of [roles?.brain, roles?.fast]) {
        expect(id).toMatch(/\S/);
        expect(PRICES[id ?? ""], `price of ${id}`).toBeDefined();
      }
    }
  });
});
