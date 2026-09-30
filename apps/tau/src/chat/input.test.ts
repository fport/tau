import { describe, expect, it } from "vitest";
import { InputQueue } from "./input";

const bytes = (text: string) => new TextEncoder().encode(text);
const text = (data: Uint8Array) => new TextDecoder().decode(data);

/** A send whose calls the test completes by hand. */
function manualSend() {
  const calls: Array<{ data: Uint8Array; done: (ok: boolean) => void }> = [];
  const send = (data: Uint8Array) =>
    new Promise<void>((resolve, reject) => {
      calls.push({ data, done: (ok) => (ok ? resolve() : reject(new Error("closed"))) });
    });
  return { calls, send };
}

const settle = () => new Promise((r) => setTimeout(r, 0));

describe("InputQueue", () => {
  it("keeps one write in flight and sends what was typed meanwhile in order", async () => {
    const { calls, send } = manualSend();
    const queue = new InputQueue(send);
    queue.push(bytes("h"));
    queue.push(bytes("e"));
    queue.push(bytes("l"));
    expect(calls.map((c) => text(c.data))).toEqual(["h"]);
    calls[0].done(true);
    await settle();
    expect(calls.map((c) => text(c.data))).toEqual(["h", "el"]);
    queue.push(bytes("ğ"));
    calls[1].done(true);
    await settle();
    expect(calls.map((c) => text(c.data))).toEqual(["h", "el", "ğ"]);
    calls[2].done(true);
    await settle();
    expect(calls).toHaveLength(3);
  });

  it("goes on after a failed write", async () => {
    const { calls, send } = manualSend();
    const queue = new InputQueue(send);
    queue.push(bytes("a"));
    queue.push(bytes("b"));
    calls[0].done(false);
    await settle();
    expect(calls.map((c) => text(c.data))).toEqual(["a", "b"]);
  });

  it("drops unsent input on clear and ignores empty input", async () => {
    const { calls, send } = manualSend();
    const queue = new InputQueue(send);
    queue.push(new Uint8Array(0));
    expect(calls).toHaveLength(0);
    queue.push(bytes("a"));
    queue.push(bytes("lost"));
    queue.clear();
    calls[0].done(true);
    await settle();
    expect(calls.map((c) => text(c.data))).toEqual(["a"]);
  });
});
