// PTY output on its way into xterm.js: raw bytes, gathered for a few milliseconds and written
// as one Uint8Array. Nothing here decodes text. A multi-byte character (ğ, ş, a box-drawing
// line) split across two chunks, or across two flushes, is joined by xterm.js's own streaming
// UTF-8 decoder; decoding chunk by chunk would turn each half into U+FFFD.

/** Runs `flush` later and returns a function that cancels it. */
export type Scheduler = (flush: () => void) => () => void;

/** How long output is gathered before it is written (the Rust side batches too). */
export const FLUSH_MS = 8;

/** Write at once when this much is waiting, even before the timer fires. */
export const MAX_PENDING = 1 << 20;

export const timerScheduler: Scheduler = (flush) => {
  const id = setTimeout(flush, FLUSH_MS);
  return () => clearTimeout(id);
};

/** One Uint8Array holding `chunks` back to back. */
export function concatChunks(chunks: readonly Uint8Array[]): Uint8Array {
  if (chunks.length === 1) return chunks[0];
  let total = 0;
  for (const chunk of chunks) total += chunk.length;
  const out = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    out.set(chunk, offset);
    offset += chunk.length;
  }
  return out;
}

export class OutputCoalescer {
  private pending: Uint8Array[] = [];
  private size = 0;
  private cancel: (() => void) | null = null;
  private disposed = false;

  constructor(
    private readonly write: (data: Uint8Array) => void,
    private readonly schedule: Scheduler = timerScheduler,
    private readonly maxPending: number = MAX_PENDING,
  ) {}

  /** Queue a chunk; it is written within one flush interval. */
  push(chunk: Uint8Array): void {
    if (this.disposed || chunk.length === 0) return;
    this.pending.push(chunk);
    this.size += chunk.length;
    if (this.size >= this.maxPending) {
      this.flush();
    } else if (!this.cancel) {
      this.cancel = this.schedule(() => {
        this.cancel = null;
        this.flush();
      });
    }
  }

  /** Write everything queued now. */
  flush(): void {
    if (this.cancel) {
      this.cancel();
      this.cancel = null;
    }
    if (this.pending.length === 0) return;
    const data = concatChunks(this.pending);
    this.pending = [];
    this.size = 0;
    this.write(data);
  }

  /** Drop anything queued and ignore later chunks. */
  dispose(): void {
    this.cancel?.();
    this.cancel = null;
    this.pending = [];
    this.size = 0;
    this.disposed = true;
  }
}
