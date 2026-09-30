/**
 * Accounts: the Durable Object that knows who is who (one instance, "accounts").
 *
 * Its SQLite database:
 *
 *   accounts   GitHub id <-> handle (the lower-cased login at sign-up), login, created_at
 *   sessions   SHA-256 of each session token (never the token), handle, expiry
 *   logins     sign-ins in flight: OAuth state -> PKCE verifier and where to go after, 10 min
 *
 * A handle never changes once given: an account keeps its handle when its GitHub login
 * changes, so its address stays. A new account whose login is the handle of another GitHub
 * account is refused. Every time is passed in, so the object has no clock of its own except
 * for its hourly clean-up alarm.
 */

import { DurableObject } from "cloudflare:workers";
import type { HostEnv } from "./env";

export const SESSION_SECONDS = 30 * 86_400;
export const LOGIN_SECONDS = 600;
const PRUNE_EVERY_MS = 3_600_000;

const SCHEMA = [
  `CREATE TABLE IF NOT EXISTS accounts (
    github_id INTEGER PRIMARY KEY,
    handle TEXT NOT NULL UNIQUE,
    login TEXT NOT NULL,
    created_at INTEGER NOT NULL
  )`,
  `CREATE TABLE IF NOT EXISTS sessions (
    hash TEXT PRIMARY KEY,
    github_id INTEGER NOT NULL,
    handle TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL
  )`,
  "CREATE INDEX IF NOT EXISTS sessions_handle ON sessions (handle)",
  "CREATE INDEX IF NOT EXISTS sessions_expires ON sessions (expires_at)",
  `CREATE TABLE IF NOT EXISTS logins (
    state TEXT PRIMARY KEY,
    verifier TEXT NOT NULL,
    next TEXT NOT NULL,
    created_at INTEGER NOT NULL
  )`,
];

export type Who = {
  handle: string;
  github_id: number;
};

export type SignIn =
  | { ok: true; handle: string; created: boolean }
  | { ok: false; error: "signup_closed" | "handle_taken" | "bad_login" };

/** A GitHub login as a handle (ADR 0013 §3): lower case, the GitHub login rules. */
export const HANDLE_RE = /^[a-z0-9](?:[a-z0-9-]{0,37}[a-z0-9])?$/;

export class Accounts extends DurableObject<HostEnv> {
  private readonly sql: SqlStorage;

  constructor(ctx: DurableObjectState, env: HostEnv) {
    super(ctx, env);
    this.sql = ctx.storage.sql;
    ctx.blockConcurrencyWhile(async () => {
      for (const statement of SCHEMA) this.sql.exec(statement);
      if ((await ctx.storage.getAlarm()) === null) await ctx.storage.setAlarm(Date.now() + PRUNE_EVERY_MS);
    });
  }

  /** Starts a sign-in: remembers the PKCE verifier and the page to return to under `state`. */
  startLogin(state: string, verifier: string, next: string, now: number): void {
    this.sql.exec(
      "INSERT INTO logins (state, verifier, next, created_at) VALUES (?, ?, ?, ?)",
      state,
      verifier,
      next,
      now,
    );
  }

  /** Takes a sign-in back once (single use); null when unknown or older than 10 minutes. */
  takeLogin(state: string, now: number): { verifier: string; next: string } | null {
    const row = this.sql
      .exec<{ verifier: string; next: string; created_at: number }>(
        "SELECT verifier, next, created_at FROM logins WHERE state = ?",
        state,
      )
      .toArray()[0];
    if (row === undefined) return null;
    this.sql.exec("DELETE FROM logins WHERE state = ?", state);
    if (now - row.created_at > LOGIN_SECONDS) return null;
    return { verifier: row.verifier, next: row.next };
  }

  /**
   * Signs a GitHub account in: its existing handle, or a new account when sign-up allows it
   * (`allowed`, decided by the Worker from SIGNUP) and the handle is free.
   */
  signIn(githubId: number, login: string, allowed: boolean, now: number): SignIn {
    const existing = this.sql
      .exec<{ handle: string }>("SELECT handle FROM accounts WHERE github_id = ?", githubId)
      .toArray()[0];
    if (existing !== undefined) {
      this.sql.exec("UPDATE accounts SET login = ? WHERE github_id = ?", login, githubId);
      return { ok: true, handle: existing.handle, created: false };
    }
    const handle = login.toLowerCase();
    if (!HANDLE_RE.test(handle)) return { ok: false, error: "bad_login" };
    if (!allowed) return { ok: false, error: "signup_closed" };
    const taken = this.sql.exec("SELECT 1 FROM accounts WHERE handle = ?", handle).toArray().length > 0;
    if (taken) return { ok: false, error: "handle_taken" };
    this.sql.exec(
      "INSERT INTO accounts (github_id, handle, login, created_at) VALUES (?, ?, ?, ?)",
      githubId,
      handle,
      login,
      now,
    );
    return { ok: true, handle, created: true };
  }

  createSession(hash: string, who: Who, now: number): void {
    this.sql.exec(
      "INSERT INTO sessions (hash, github_id, handle, created_at, expires_at) VALUES (?, ?, ?, ?, ?)",
      hash,
      who.github_id,
      who.handle,
      now,
      now + SESSION_SECONDS,
    );
  }

  /** Who a session belongs to, or null when it is unknown, expired or its account is gone. */
  session(hash: string, now: number): Who | null {
    const row = this.sql
      .exec<{ handle: string; github_id: number; expires_at: number }>(
        `SELECT s.handle, s.github_id, s.expires_at FROM sessions s
           JOIN accounts a ON a.github_id = s.github_id AND a.handle = s.handle
          WHERE s.hash = ?`,
        hash,
      )
      .toArray()[0];
    if (row === undefined) return null;
    if (row.expires_at <= now) {
      this.sql.exec("DELETE FROM sessions WHERE hash = ?", hash);
      return null;
    }
    return { handle: row.handle, github_id: row.github_id };
  }

  endSession(hash: string): void {
    this.sql.exec("DELETE FROM sessions WHERE hash = ?", hash);
  }

  account(handle: string): (Who & { login: string; created_at: number }) | null {
    return (
      this.sql
        .exec<Who & { login: string; created_at: number }>(
          "SELECT handle, github_id, login, created_at FROM accounts WHERE handle = ?",
          handle,
        )
        .toArray()[0] ?? null
    );
  }

  /** Removes the account and every session of it; the handle is free again. */
  deleteAccount(handle: string): void {
    this.sql.exec("DELETE FROM sessions WHERE handle = ?", handle);
    this.sql.exec("DELETE FROM accounts WHERE handle = ?", handle);
  }

  prune(now: number): { sessions: number; logins: number } {
    const sessions = this.sql.exec("DELETE FROM sessions WHERE expires_at <= ?", now).rowsWritten;
    const logins = this.sql.exec("DELETE FROM logins WHERE created_at < ?", now - LOGIN_SECONDS).rowsWritten;
    return { sessions, logins };
  }

  override async alarm(): Promise<void> {
    this.prune(Math.floor(Date.now() / 1000));
    await this.ctx.storage.setAlarm(Date.now() + PRUNE_EVERY_MS);
  }
}
