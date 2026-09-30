// Keys, pastes and mouse reports on their way to the PTY. Each write is an IPC call that the
// Rust side runs off the main thread, so two calls in flight could land out of order. The queue
// keeps one call in flight and sends whatever was typed meanwhile as the next one: the order
// holds, and fast typing costs one round trip, not one per key.

import { concatChunks } from "./output";

export class InputQueue {
  private pending: Uint8Array[] = [];
  private inFlight = false;

  constructor(private readonly send: (data: Uint8Array) => Promise<unknown>) {}

  push(data: Uint8Array): void {
    if (data.length === 0) return;
    this.pending.push(data);
    if (!this.inFlight) this.pump();
  }

  /** Forget what has not been sent (the TUI is gone). */
  clear(): void {
    this.pending = [];
  }

  private pump(): void {
    if (this.pending.length === 0) {
      this.inFlight = false;
      return;
    }
    const data = concatChunks(this.pending);
    this.pending = [];
    this.inFlight = true;
    this.send(data)
      .catch(() => undefined)
      .finally(() => this.pump());
  }
}
