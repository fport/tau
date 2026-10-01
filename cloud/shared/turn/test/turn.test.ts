/**
 * Python → TypeScript: the turn protocol as tau-core produces it (turn/vectors.json, written by
 * packages/tau-core/scripts/make_turn_vectors.py). Every event and history block must parse,
 * the constants must match tau-core's, the invalid examples must not parse, and the NDJSON
 * reader must survive chunks cut anywhere.
 */

import { describe, expect, it } from "vitest";

import {
  BLOCK_TYPES,
  EVENT_TYPES,
  INPUT_LIMIT,
  LineSplitter,
  parseBlock,
  parseEvent,
  PROTOCOL_VERSION,
  ProtocolError,
  readEvents,
  STOP_REASONS,
  encodeEvent,
  type TurnEvent,
} from "../index.ts";
import vectors from "../vectors.json";

function bodyOf(chunks: Uint8Array[]): ReadableStream<Uint8Array> {
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(chunk);
      controller.close();
    },
  });
}

async function collect(body: ReadableStream<Uint8Array>): Promise<TurnEvent[]> {
  const out: TurnEvent[] = [];
  for await (const event of readEvents(body)) out.push(event);
  return out;
}

describe("the constants match tau-core's", () => {
  it("version, input limit, event and block types, stop reasons", () => {
    expect(PROTOCOL_VERSION).toBe(vectors.version);
    expect(INPUT_LIMIT).toBe(vectors.input_limit);
    expect([...EVENT_TYPES]).toEqual(vectors.event_types);
    expect([...BLOCK_TYPES]).toEqual(vectors.block_types);
    expect([...STOP_REASONS]).toEqual(vectors.stop_reasons);
  });
});

describe("the vectors", () => {
  it("every stream event parses, in order, and covers every type", () => {
    const parsed = vectors.stream.map((event) => parseEvent(event));
    expect(parsed).toEqual(vectors.stream);
    expect(parsed.map((event) => event?.seq)).toEqual(vectors.stream.map((_, index) => index));
    expect(new Set(parsed.map((event) => event?.type))).toEqual(new Set(EVENT_TYPES));
  });

  it("every history block parses and covers every type", () => {
    const parsed = vectors.history.map((block) => parseBlock(block));
    expect(parsed).toEqual(vectors.history);
    expect(new Set(parsed.map((block) => block?.type))).toEqual(new Set(BLOCK_TYPES));
  });

  it("a large input arrives as a preview", () => {
    const [truncated] = vectors.stream.filter((event) => "truncated" in event && event.truncated);
    expect(truncated).toMatchObject({ type: "tool_input", input: null, truncated: true });
    expect((truncated as { preview: string }).preview).toHaveLength(INPUT_LIMIT);
  });

  it.each(vectors.invalid.map((event, index) => [index, event] as const))(
    "invalid example %i does not parse",
    (_, event) => {
      expect(parseEvent(event)).toBeNull();
    },
  );
});

describe("validation", () => {
  it("refuses what is not an object, unknown block types and bad blocks", () => {
    for (const value of [null, 3, "text", [], { v: 1, seq: 0, type: "toString", delta: "x" }]) {
      expect(parseEvent(value)).toBeNull();
    }
    expect(parseBlock({ type: "toString", text: "x", at: null })).toBeNull();
    expect(parseBlock({ type: "user", text: "x", at: "yesterday" })).toBeNull();
    expect(parseBlock({ type: "user", text: "x" })).toBeNull();
    expect(parseBlock({ type: "user", text: "x", at: null })).toEqual({ type: "user", text: "x", at: null });
  });

  it("keeps extra fields for later versions of a backend", () => {
    const event = { v: 1, seq: 0, type: "text", delta: "x", later: true };
    expect(parseEvent(event)).toEqual(event);
  });
});

describe("NDJSON", () => {
  const events: TurnEvent[] = [
    { v: 1, seq: 0, type: "turn", turn: "t", session: "s" },
    { v: 1, seq: 1, type: "text", delta: "çay ☕ şeker" },
    { v: 1, seq: 2, type: "end", stop_reason: "end_turn" },
  ];
  const bytes = new TextEncoder().encode(events.map(encodeEvent).join(""));

  it("reads events from chunks cut anywhere, even inside a character", async () => {
    for (let cut = 1; cut < bytes.length; cut += 7) {
      const chunks = [bytes.slice(0, cut), bytes.slice(cut)];
      expect(await collect(bodyOf(chunks))).toEqual(events);
    }
    const oneByteChunks = Array.from(bytes, (byte) => Uint8Array.of(byte));
    expect(await collect(bodyOf(oneByteChunks))).toEqual(events);
  });

  it("reads a last line without a newline", async () => {
    const text = events.map(encodeEvent).join("").trimEnd();
    expect(await collect(bodyOf([new TextEncoder().encode(text)]))).toEqual(events);
  });

  it("throws on a line that is not a turn event", async () => {
    const bad = new TextEncoder().encode('{"v":1,"seq":0,"type":"text"}\n');
    await expect(collect(bodyOf([bad]))).rejects.toBeInstanceOf(ProtocolError);
    const notJson = new TextEncoder().encode("hello\n");
    await expect(collect(bodyOf([notJson]))).rejects.toThrow("not JSON");
  });

  it("splits lines and skips blank ones", () => {
    const lines = new LineSplitter();
    expect(lines.push('{"a":1}\n\n{"b"')).toEqual(['{"a":1}']);
    expect(lines.push(":2}\n")).toEqual(['{"b":2}']);
    expect(lines.flush()).toEqual([]);
  });
});
