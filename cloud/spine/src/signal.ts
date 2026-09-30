/**
 * HubSignal wakes the hub's waiting long poll when an envelope arrives.
 *
 * One instance (named "hub") serves the whole spine. It keeps no durable state: the
 * mailbox lives in D1, and this object only resolves the promises of waiting polls.
 */

import { DurableObject } from "cloudflare:workers";
import type { SpineEnv } from "./env";

export const SIGNAL_NAME = "hub";

/** Upper bound for one wait, a little above the longest long poll (25 s). */
const MAX_WAIT_MS = 30_000;

export class HubSignal extends DurableObject<SpineEnv> {
  private readonly waiters = new Set<(woken: boolean) => void>();
  /** The highest mailbox seq announced by notify() since this instance started. */
  private lastSeq = 0;
  /** The highest seq a poll is known to have been told about (woken, or returned early). */
  private deliveredSeq = 0;

  /**
   * Resolves true when notify() is called, false after `ms`.
   *
   * `after` is the poll's cursor. When an envelope newer than `after` was announced while
   * nobody was waiting (it arrived between the poll's empty D1 query and this call), the
   * wait returns true at once so the poll queries again. That early return happens once
   * per announcement, so a poll whose cursor lags behind acknowledged mail cannot spin.
   */
  async wait(ms: number, after?: number): Promise<boolean> {
    if (after !== undefined && this.lastSeq > after && this.lastSeq > this.deliveredSeq) {
      this.deliveredSeq = this.lastSeq;
      return true;
    }
    const timeout = Math.max(0, Math.min(ms, MAX_WAIT_MS));
    return new Promise<boolean>((resolve) => {
      const finish = (woken: boolean): void => {
        clearTimeout(timer);
        this.waiters.delete(finish);
        resolve(woken);
      };
      const timer = setTimeout(() => finish(false), timeout);
      this.waiters.add(finish);
    });
  }

  /** Wakes every waiting poll; returns how many were waiting. */
  async notify(seq?: number): Promise<number> {
    if (seq !== undefined && seq > this.lastSeq) this.lastSeq = seq;
    const waiting = [...this.waiters];
    if (waiting.length > 0) this.deliveredSeq = this.lastSeq;
    for (const finish of waiting) finish(true);
    return waiting.length;
  }
}
