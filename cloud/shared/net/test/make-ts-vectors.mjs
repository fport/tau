#!/usr/bin/env node
/**
 * Writes net/ts-vectors.json: envelopes, keys and universe requests made by the TypeScript
 * half from fresh random inputs, for tau-net to check
 * (packages/tau-net/tests/test_ts_vectors.py). Every key in it is test-only.
 *
 * Run `pnpm run vectors` in cloud/shared after a change that alters what the TypeScript
 * writes (ts-vectors.test.ts fails until then), and commit the file. Node runs the TypeScript
 * modules directly (type stripping, Node 22.18 or newer).
 */

import { writeFileSync } from "node:fs";

import { buildTsVectors, freshInputs } from "./ts-vectors.ts";

const vectors = await buildTsVectors(await freshInputs());
const target = new URL("../ts-vectors.json", import.meta.url);
writeFileSync(target, JSON.stringify(vectors, null, 2) + "\n");
console.log("wrote net/ts-vectors.json");
