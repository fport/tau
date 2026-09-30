import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FLUSH_MS, OutputCoalescer, concatChunks, timerScheduler, type Scheduler } from "./output";

const TURKISH = "ğüşıöç ĞÜŞİÖÇ ─│┌┐└┘ τ";
const bytes = (text: string) => new TextEncoder().encode(text);

/** A scheduler the test fires by hand. */
function manualScheduler() {
  const queued: Array<() => void> = [];
  const schedule: Scheduler = (flush) => {
    queued.push(flush);
    return () => {
      const i = queued.indexOf(flush);
      if (i >= 0) queued.splice(i, 1);
    };
  };
  return {
    schedule,
    pending: () => queued.length,
    fire: () => queued.splice(0).forEach((f) => f()),
  };
}

/** Cut `data` into pieces of `size` bytes, splitting multi-byte characters. */
function split(data: Uint8Array, size: number): Uint8Array[] {
  const out: Uint8Array[] = [];
  for (let i = 0; i < data.length; i += size) out.push(data.slice(i, i + size));
  return out;
}

describe("OutputCoalescer", () => {
  it("writes chunks gathered in one interval as a single Uint8Array", () => {
    const writes: Uint8Array[] = [];
    const clock = manualScheduler();
    const out = new OutputCoalescer((d) => writes.push(d), clock.schedule);
    out.push(bytes("ab"));
    out.push(bytes("cd"));
    out.push(bytes("e"));
    expect(writes).toEqual([]);
    expect(clock.pending()).toBe(1); // one timer for the whole interval
    clock.fire();
    expect(writes).toHaveLength(1);
    expect(writes[0]).toBeInstanceOf(Uint8Array);
    expect(new TextDecoder().decode(writes[0])).toBe("abcde");
  });

  it("keeps split UTF-8 intact: bytes in, bytes out, never decoded per chunk", () => {
    const data = bytes(TURKISH);
    for (const size of [1, 2, 3, 5, 7]) {
      const writes: Uint8Array[] = [];
      const clock = manualScheduler();
      const out = new OutputCoalescer((d) => writes.push(d), clock.schedule);
      split(data, size).forEach((chunk, i) => {
        out.push(chunk);
        // Flush at awkward moments too: a character may straddle two writes.
        if (i % 3 === 2) clock.fire();
      });
      out.flush();
      expect(writes.every((w) => w instanceof Uint8Array)).toBe(true);
      const joined = concatChunks(writes);
      expect(Array.from(joined)).toEqual(Array.from(data));
      // What xterm.js's streaming decoder sees across the writes:
      const decoder = new TextDecoder("utf-8", { fatal: true });
      const text = writes.map((w) => decoder.decode(w, { stream: true })).join("") + decoder.decode();
      expect(text).toBe(TURKISH);
      expect(text).not.toContain("�");
    }
  });

  it("writes at once when too much is waiting", () => {
    const writes: Uint8Array[] = [];
    const clock = manualScheduler();
    const out = new OutputCoalescer((d) => writes.push(d), clock.schedule, 4);
    out.push(bytes("ab"));
    expect(writes).toHaveLength(0);
    out.push(bytes("cde"));
    expect(writes.map((w) => new TextDecoder().decode(w))).toEqual(["abcde"]);
    expect(clock.pending()).toBe(0); // the timer was cancelled
  });

  it("ignores empty chunks and flushes nothing when idle", () => {
    const write = vi.fn();
    const clock = manualScheduler();
    const out = new OutputCoalescer(write, clock.schedule);
    out.push(new Uint8Array(0));
    out.flush();
    expect(clock.pending()).toBe(0);
    expect(write).not.toHaveBeenCalled();
  });

  it("drops output after dispose", () => {
    const write = vi.fn();
    const clock = manualScheduler();
    const out = new OutputCoalescer(write, clock.schedule);
    out.push(bytes("lost"));
    out.dispose();
    out.push(bytes("later"));
    clock.fire();
    out.flush();
    expect(write).not.toHaveBeenCalled();
  });
});

describe("timerScheduler", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it(`flushes ${FLUSH_MS} ms after the first chunk`, () => {
    const writes: Uint8Array[] = [];
    const out = new OutputCoalescer((d) => writes.push(d), timerScheduler);
    out.push(bytes("a"));
    vi.advanceTimersByTime(FLUSH_MS - 1);
    out.push(bytes("b"));
    expect(writes).toHaveLength(0);
    vi.advanceTimersByTime(1);
    expect(writes.map((w) => new TextDecoder().decode(w))).toEqual(["ab"]);
    expect(FLUSH_MS).toBeGreaterThanOrEqual(8);
    expect(FLUSH_MS).toBeLessThanOrEqual(16);
  });

  it("can be cancelled", () => {
    const flush = vi.fn();
    const cancel = timerScheduler(flush);
    cancel();
    vi.advanceTimersByTime(100);
    expect(flush).not.toHaveBeenCalled();
  });
});

describe("concatChunks", () => {
  it("joins in order and returns a lone chunk as is", () => {
    const one = bytes("x");
    expect(concatChunks([one])).toBe(one);
    expect(Array.from(concatChunks([bytes("ab"), new Uint8Array(0), bytes("c")]))).toEqual(
      Array.from(bytes("abc")),
    );
    expect(concatChunks([]).length).toBe(0);
  });
});
