/**
 * net/ts-vectors.json is what the TypeScript half writes today: rebuilt from its recorded
 * inputs, it must come out the same, byte for byte. tau-net checks the same file from the
 * Python side (packages/tau-net/tests/test_ts_vectors.py).
 */

import { describe, expect, it } from "vitest";

import {
  encodeRequest,
  Identity,
  openEnvelope,
  parseClaimFragment,
  parseRequest,
  verifyRequest,
} from "../index.ts";
import recorded from "../ts-vectors.json";
import { buildTsVectors, type TsVectorInputs } from "./ts-vectors.ts";

describe("ts-vectors.json", () => {
  it("is what the TypeScript builds from its inputs (else: bun run vectors)", async () => {
    const rebuilt = await buildTsVectors(recorded.inputs as TsVectorInputs);
    expect(JSON.parse(JSON.stringify(rebuilt))).toEqual(recorded);
  });

  it("opens and verifies its own envelopes and requests", async () => {
    const identities = recorded.identities as Record<
      string,
      { sign_key: string; identity: unknown }
    >;
    for (const vector of recorded.envelopes) {
      const recipient = await Identity.fromJson(identities[vector.recipient]!.identity);
      const opened = await openEnvelope(
        vector.envelope,
        identities[vector.sender]!.sign_key,
        recipient,
      );
      expect(opened.raw).toEqual(vector.input.content);
    }
    for (const vector of recorded.universe) {
      const parsed = parseRequest(encodeRequest(vector.request));
      const key = identities[vector.signer]!.sign_key;
      expect(await verifyRequest(key, parsed.payloadBytes, parsed.sig)).toBe(true);
    }
  });

  it("carries a claim link whose fragment is the signed request", () => {
    const link = recorded.claim_link!;
    const fragment = link.link.split("#")[1]!;
    expect(link.link.startsWith("https://universe.example.com/claim#")).toBe(true);
    expect(parseClaimFragment(fragment)).toEqual(link.request);
  });
});
