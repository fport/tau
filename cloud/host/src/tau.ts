/**
 * Tau: the Durable Object that is one hosted tau (one instance per handle, addressed with
 * `idFromName(handle)`; ADR 0013 §2).
 *
 * Its SQLite database holds everything of that tau:
 *
 *   settings        key → JSON value: handle, provider, the sealed provider key and its last
 *                   four characters, model ids per role, budget, language, persona, profile,
 *                   the universe choice (read by issue 162), onboarding time
 *   sessions        the owner's conversations, with the main tau (sub = '') or a sub-tau
 *   messages        each session's messages as provider-neutral blocks (JSON)
 *   subs            the sub-tau definitions (JSON)
 *   approvals       tier-2 calls waiting for the owner (and decided ones), with the paused
 *                   turn to resume
 *   spend           one row per model call: tokens and dollars, never text
 *   visit_threads   visitor conversations with public web sub-taus (24 h), and
 *   visit_messages  their messages
 *   visit_days      visitor turns per sub-tau and UTC day (the web_daily cap)
 *   visit_hits      visitor messages per hashed IP (10 a minute)
 *
 * The owner's turns stream NDJSON to the app. A tier-2 call pauses the turn: an approval
 * card is stored and streamed, the stream ends, and the owner's decision (`decide`) resumes
 * the turn with a new stream. Nothing here ever approves by itself; an approval that nobody
 * answers expires after 10 minutes (the alarm) and the call is refused.
 *
 * Network work (issue 162) plugs in here: the network identity and contacts become more
 * tables, `net_send` a tier-2 tool in `tools()` that goes through the same approvals, and
 * delivered envelopes a method that runs `networkTurn` like `visit` runs a visitor turn.
 */

import { DurableObject } from "cloudflare:workers";
import {
  budgetLine,
  budgetState,
  type BudgetState,
  cost,
  DEFAULT_BUDGET_USD,
  MAX_BUDGET_USD,
  monthOf,
  priceFor,
} from "./agent/budget";
import { DraftError, DRAFT_PERSONA, draftPrompt, parseDraft } from "./agent/draft";
import {
  type Approver,
  MAX_TOKENS,
  normalizeHistory,
  type PausedTurn,
  type Resolution,
  runTurn,
  type TurnEvent,
} from "./agent/loop";
import {
  type HistoryLine,
  isNoReply,
  personaText,
  profileSection,
  publicNoteSection,
  stripNoReply,
  subPersona,
  systemPrompt,
  visitFrame,
} from "./agent/prompt";
import { isWebSub, type SubTau, SubTauError, TEMPLATES, validateName, validateSub } from "./agent/subs";
import { ASK_SUB_SPEC, CREATE_EFFECT, CREATE_SUB_SPEC, type HostTool, refusal, TOOL_LIMIT_NOTE } from "./agent/tools";
import { randomToken } from "./crypto";
import type { HostEnv } from "./env";
import { DEFAULT_PERSONA } from "./generated/persona";
import { MODELS } from "./generated/models";
import { nowSeconds } from "./http";
import {
  checkKey,
  CLOUD_PROVIDERS,
  isProviderName,
  type Message,
  type ModelRole,
  type Provider,
  ProviderError,
  providerFor,
  type ProviderName,
  plausibleKey,
  type TextBlock,
  type ToolUseBlock,
  type Usage,
} from "./providers";
import { open, seal, VaultError } from "./vault";

export const APPROVAL_SECONDS = 600;
export const THREAD_SECONDS = 86_400;
export const THREAD_MESSAGES_MAX = 50;
export const VISIT_TEXT_MAX = 2000;
export const VISITS_PER_MINUTE = 10;
export const CHAT_TEXT_MAX = 20_000;
export const PROFILE_MAX = 20_000;
export const PERSONA_MAX = 20_000;
export const HISTORY_MESSAGES = 60;
export const SESSIONS_LISTED = 100;
const KEY_PURPOSE = "provider_key";
const SCHEMA_VERSION = 1;

export type Language = "en" | "tr";
export type UniverseChoice = boolean | null;

/** The outcome of an RPC call: a value, or the HTTP status and error code the Worker answers. */
export type Outcome<T> = { ok: true; value: T } | { ok: false; status: number; error: string; detail?: string };

function ok<T>(value: T): Outcome<T> {
  return { ok: true, value };
}

function fail(status: number, error: string, detail?: string): { ok: false; status: number; error: string; detail?: string } {
  return detail === undefined ? { ok: false, status, error } : { ok: false, status, error, detail };
}

const SCHEMA = [
  "CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
  `CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    sub TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
  )`,
  "CREATE INDEX IF NOT EXISTS sessions_updated ON sessions (updated_at)",
  `CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    at INTEGER NOT NULL
  )`,
  "CREATE INDEX IF NOT EXISTS messages_session ON messages (session, id)",
  `CREATE TABLE IF NOT EXISTS subs (
    name TEXT PRIMARY KEY,
    def TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
  )`,
  `CREATE TABLE IF NOT EXISTS approvals (
    id TEXT PRIMARY KEY,
    session TEXT NOT NULL,
    tool TEXT NOT NULL,
    call_id TEXT NOT NULL,
    input TEXT NOT NULL,
    effect TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,
    decided_at INTEGER,
    turn TEXT NOT NULL DEFAULT ''
  )`,
  "CREATE INDEX IF NOT EXISTS approvals_status ON approvals (status, expires_at)",
  `CREATE TABLE IF NOT EXISTS spend (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at INTEGER NOT NULL,
    month TEXT NOT NULL,
    kind TEXT NOT NULL,
    role TEXT NOT NULL,
    sub TEXT NOT NULL DEFAULT '',
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    input INTEGER NOT NULL,
    output INTEGER NOT NULL,
    cache_read INTEGER NOT NULL,
    cache_write INTEGER NOT NULL,
    cost_usd REAL
  )`,
  "CREATE INDEX IF NOT EXISTS spend_month ON spend (month)",
  `CREATE TABLE IF NOT EXISTS visit_threads (
    id TEXT PRIMARY KEY,
    sub TEXT NOT NULL,
    visitor TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,
    messages INTEGER NOT NULL DEFAULT 0
  )`,
  "CREATE INDEX IF NOT EXISTS visit_threads_expires ON visit_threads (expires_at)",
  `CREATE TABLE IF NOT EXISTS visit_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    thread TEXT NOT NULL,
    role TEXT NOT NULL,
    text TEXT NOT NULL,
    at INTEGER NOT NULL
  )`,
  "CREATE INDEX IF NOT EXISTS visit_messages_thread ON visit_messages (thread, id)",
  `CREATE TABLE IF NOT EXISTS visit_days (
    day TEXT NOT NULL,
    sub TEXT NOT NULL,
    count INTEGER NOT NULL,
    PRIMARY KEY (day, sub)
  )`,
  "CREATE TABLE IF NOT EXISTS visit_hits (ip TEXT NOT NULL, at INTEGER NOT NULL)",
  "CREATE INDEX IF NOT EXISTS visit_hits_ip ON visit_hits (ip, at)",
];

/** What the app sees of the settings: never the key, only its provider and last four. */
export interface PublicSettings {
  provider: ProviderName | null;
  key_last4: string;
  has_key: boolean;
  models: Record<ModelRole, string>;
  budget_usd: number;
  language: Language | null;
  persona: string | null;
  profile: string;
  universe: UniverseChoice;
  onboarded: boolean;
}

export type SessionRow = {
  id: string;
  sub: string;
  title: string;
  created_at: number;
  updated_at: number;
};

export interface StoredMessage {
  id: number;
  role: "user" | "assistant";
  content: Message["content"];
  at: number;
}

export interface ApprovalCard {
  id: string;
  session: string;
  tool: string;
  /** The id of the tool call in the session's messages. */
  call_id: string;
  input: Record<string, unknown>;
  effect: string;
  status: "pending" | "approved" | "denied" | "expired";
  created_at: number;
  expires_at: number;
  decided_at: number | null;
}

export interface SubRow extends SubTau {
  created_at: number;
  updated_at: number;
  visits_today: number;
}

export interface AppState {
  handle: string;
  github_id: number;
  settings: PublicSettings;
  budget: BudgetState;
  subs: SubRow[];
  sessions: SessionRow[];
  approvals: ApprovalCard[];
  defaults: { persona: string; models: Record<string, Record<ModelRole, string>> };
  providers: ProviderName[];
  unpriced: string[];
}

export interface VisitReply {
  thread: string;
  reply: { id: string; text: string; ts: number };
}

export interface PublicSubInfo {
  handle: string;
  name: string;
  about: string;
  starters: string[];
}

interface StoredTurn extends PausedTurn {
  sub: string;
  role: ModelRole;
}

type Json = Record<string, unknown>;

const NDJSON = "application/x-ndjson; charset=utf-8";

function jsonResponse(body: unknown, status: number): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" },
  });
}

function failResponse(outcome: { status: number; error: string; detail?: string }): Response {
  const body: Json = { error: outcome.error };
  if (outcome.detail !== undefined) body.detail = outcome.detail;
  return jsonResponse(body, outcome.status);
}

function dayOf(seconds: number): string {
  return new Date(seconds * 1000).toISOString().slice(0, 10);
}

const MODEL_ID_RE = /^[A-Za-z0-9][A-Za-z0-9._:/@-]{0,127}$/;

function textOf(content: Message["content"]): string {
  return content
    .filter((block): block is TextBlock => block.type === "text")
    .map((block) => block.text)
    .join("")
    .trim();
}

function title(text: string): string {
  const line = text.split(/\s+/).filter(Boolean).join(" ");
  return line.length > 60 ? `${line.slice(0, 59)}…` : line;
}

/** A provider failure as an error code the app translates, with a key-free detail. */
function providerFailure(err: unknown): { code: string; detail: string } {
  if (err instanceof ProviderError) return { code: `provider_${err.kind}`, detail: err.detail };
  if (err instanceof VaultError) return { code: "vault", detail: err.message };
  return { code: "internal", detail: "" };
}

export class Tau extends DurableObject<HostEnv> {
  private readonly sql: SqlStorage;
  /** Sessions with a turn running right now (one turn per session at a time). */
  private readonly busy = new Set<string>();

  constructor(ctx: DurableObjectState, env: HostEnv) {
    super(ctx, env);
    this.sql = ctx.storage.sql;
    this.migrate();
  }

  private migrate(): void {
    for (const statement of SCHEMA) this.sql.exec(statement);
    if (this.get<number>("schema") === null) this.put("schema", SCHEMA_VERSION);
  }

  // -- settings ---------------------------------------------------------------------------

  private get<T>(key: string): T | null {
    const row = this.sql.exec<{ value: string }>("SELECT value FROM settings WHERE key = ?", key).toArray()[0];
    return row === undefined ? null : (JSON.parse(row.value) as T);
  }

  private put(key: string, value: unknown): void {
    this.sql.exec(
      "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT (key) DO UPDATE SET value = excluded.value",
      key,
      JSON.stringify(value),
    );
  }

  private handle(): string {
    const handle = this.get<string>("handle");
    if (handle === null) throw new Error("this tau has no handle yet");
    return handle;
  }

  /** Creates the tau on first sign-in; later calls change nothing. */
  ensure(handle: string, githubId: number): void {
    if (this.get<string>("handle") !== null) return;
    this.put("handle", handle);
    this.put("github_id", githubId);
    this.put("created_at", nowSeconds());
    this.put("budget_usd", DEFAULT_BUDGET_USD);
  }

  exists(): boolean {
    return this.get<string>("handle") !== null;
  }

  private provider(): ProviderName | null {
    const name = this.get<string>("provider");
    return isProviderName(name) ? name : null;
  }

  private models(): Record<ModelRole, string> {
    const stored = this.get<Partial<Record<ModelRole, string>>>("models") ?? {};
    const provider = this.provider();
    const defaults = provider ? MODELS[provider] : undefined;
    return {
      brain: stored.brain ?? defaults?.brain ?? "",
      fast: stored.fast ?? defaults?.fast ?? "",
    };
  }

  private budgetUsd(): number {
    return this.get<number>("budget_usd") ?? DEFAULT_BUDGET_USD;
  }

  private settings(): PublicSettings {
    const provider = this.provider();
    const lang = this.get<string>("language");
    return {
      provider,
      key_last4: this.get<string>("key_last4") ?? "",
      has_key: this.get<string>("key") !== null,
      models: this.models(),
      budget_usd: this.budgetUsd(),
      language: lang === "en" || lang === "tr" ? lang : null,
      persona: this.get<string>("persona"),
      profile: this.get<string>("profile") ?? "",
      universe: this.get<UniverseChoice>("universe"),
      onboarded: this.get<number>("onboarded_at") !== null,
    };
  }

  private spent(now: number): number {
    const row = this.sql
      .exec<{ total: number }>("SELECT COALESCE(SUM(cost_usd), 0) AS total FROM spend WHERE month = ?", monthOf(now))
      .toArray()[0];
    return row?.total ?? 0;
  }

  private budget(now = nowSeconds()): BudgetState {
    return budgetState(this.spent(now), this.budgetUsd(), now);
  }

  private async key(): Promise<string> {
    const provider = this.provider();
    if (provider === "fake") return "";
    const sealed = this.get<string>("key");
    if (sealed === null) throw new VaultError("no provider key is stored");
    return open(this.env.VAULT_KEY, this.handle(), KEY_PURPOSE, sealed);
  }

  private async client(): Promise<Provider> {
    const provider = this.provider();
    if (provider === null) throw new VaultError("no provider is set");
    return providerFor(provider, await this.key());
  }

  /** Checks, seals and stores a provider key (with its provider); never logged or returned. */
  private async storeKey(provider: ProviderName, key: string): Promise<Outcome<null>> {
    if (provider === "fake") {
      this.sql.exec("DELETE FROM settings WHERE key IN ('key', 'key_last4')");
      this.put("provider", provider);
      return ok(null);
    }
    if (!plausibleKey(key)) return fail(400, "bad_key", "the key has the wrong shape");
    const check = await checkKey(provider, key);
    if (!check.ok) return fail(check.reason === "invalid" ? 400 : 502, check.reason === "invalid" ? "key_invalid" : "key_unchecked");
    let sealed: string;
    try {
      sealed = await seal(this.env.VAULT_KEY, this.handle(), KEY_PURPOSE, key);
    } catch (err) {
      return fail(500, "vault", err instanceof VaultError ? err.message : "the key could not be sealed");
    }
    this.put("provider", provider);
    this.put("key", sealed);
    this.put("key_last4", key.slice(-4));
    return ok(null);
  }

  private providerAllowed(provider: unknown, fakeAllowed: boolean): provider is ProviderName {
    return isProviderName(provider) && ((CLOUD_PROVIDERS as readonly string[]).includes(provider) || fakeAllowed);
  }

  async onboard(input: Json, fakeAllowed: boolean): Promise<Outcome<AppState>> {
    const { provider, key, language, universe } = input;
    if (!this.providerAllowed(provider, fakeAllowed)) return fail(400, "bad_request", "unknown provider");
    if (language !== "en" && language !== "tr") return fail(400, "bad_request", "language must be en or tr");
    if (typeof universe !== "boolean") {
      return fail(400, "bad_request", "universe must be chosen explicitly (true or false)");
    }
    if (provider !== "fake" && typeof key !== "string") return fail(400, "bad_request", "a provider key is needed");
    const stored = await this.storeKey(provider, typeof key === "string" ? key.trim() : "");
    if (!stored.ok) return stored;
    this.sql.exec("DELETE FROM settings WHERE key = 'models'");
    this.put("language", language);
    this.put("universe", universe);
    if (this.get<number>("onboarded_at") === null) this.put("onboarded_at", nowSeconds());
    return ok(this.state());
  }

  async updateSettings(patch: Json, fakeAllowed: boolean): Promise<Outcome<AppState>> {
    // Validate everything first, then write: a bad field changes nothing.
    const writes: [string, unknown][] = [];
    const deletes: string[] = [];
    let newKey: { provider: ProviderName; key: string } | null = null;
    const current = this.provider();

    if (patch.provider !== undefined || patch.key !== undefined) {
      const provider = patch.provider ?? current;
      if (!this.providerAllowed(provider, fakeAllowed)) return fail(400, "bad_request", "unknown provider");
      if (provider !== current && provider !== "fake" && typeof patch.key !== "string") {
        return fail(400, "bad_request", "a new provider needs its key");
      }
      if (patch.key !== undefined && typeof patch.key !== "string") return fail(400, "bad_request", "key must be text");
      newKey = { provider, key: typeof patch.key === "string" ? patch.key.trim() : "" };
      if (provider !== current && patch.models === undefined) deletes.push("models");
    }
    if (patch.models !== undefined) {
      const models = patch.models as Json;
      if (typeof models !== "object" || models === null) return fail(400, "bad_request", "models must be an object");
      const next = { ...(this.get<Partial<Record<ModelRole, string>>>("models") ?? {}) };
      for (const role of ["brain", "fast"] as const) {
        const value = models[role];
        if (value === undefined) continue;
        if (typeof value !== "string" || !MODEL_ID_RE.test(value.trim())) {
          return fail(400, "bad_request", `models.${role} is not a model id`);
        }
        next[role] = value.trim();
      }
      writes.push(["models", next]);
    }
    if (patch.budget_usd !== undefined) {
      const budget = patch.budget_usd;
      if (typeof budget !== "number" || !Number.isFinite(budget) || budget < 0 || budget > MAX_BUDGET_USD) {
        return fail(400, "bad_request", `budget_usd must be from 0 to ${MAX_BUDGET_USD}`);
      }
      writes.push(["budget_usd", Math.round(budget * 100) / 100]);
    }
    if (patch.language !== undefined) {
      if (patch.language !== "en" && patch.language !== "tr") return fail(400, "bad_request", "language must be en or tr");
      writes.push(["language", patch.language]);
    }
    if (patch.persona !== undefined) {
      if (patch.persona === null || (typeof patch.persona === "string" && !patch.persona.trim())) {
        deletes.push("persona");
      } else if (typeof patch.persona !== "string" || patch.persona.length > PERSONA_MAX) {
        return fail(400, "bad_request", `persona must be text of at most ${PERSONA_MAX} characters`);
      } else {
        writes.push(["persona", patch.persona.replaceAll("\r\n", "\n")]);
      }
    }
    if (patch.profile !== undefined) {
      if (typeof patch.profile !== "string" || patch.profile.length > PROFILE_MAX) {
        return fail(400, "bad_request", `profile must be text of at most ${PROFILE_MAX} characters`);
      }
      writes.push(["profile", patch.profile.replaceAll("\r\n", "\n")]);
    }
    if (patch.universe !== undefined) {
      if (typeof patch.universe !== "boolean") return fail(400, "bad_request", "universe must be true or false");
      writes.push(["universe", patch.universe]);
    }

    if (newKey !== null && (newKey.key !== "" || newKey.provider === "fake")) {
      const stored = await this.storeKey(newKey.provider, newKey.key);
      if (!stored.ok) return stored;
    } else if (newKey !== null && newKey.provider !== current) {
      return fail(400, "bad_request", "a new provider needs its key");
    }
    for (const key of deletes) this.sql.exec("DELETE FROM settings WHERE key = ?", key);
    for (const [key, value] of writes) this.put(key, value);
    return ok(this.state());
  }

  state(): AppState {
    const now = nowSeconds();
    const models = this.models();
    const provider = this.provider();
    const unpriced = provider
      ? [...new Set([models.brain, models.fast])].filter((id) => id && priceFor(provider, id) === null)
      : [];
    const providers: ProviderName[] = [...CLOUD_PROVIDERS];
    if (this.env.FAKE_PROVIDER === "1") providers.push("fake");
    return {
      handle: this.handle(),
      github_id: this.get<number>("github_id") ?? 0,
      settings: this.settings(),
      budget: this.budget(now),
      subs: this.listSubs(),
      sessions: this.listSessions(),
      approvals: this.listApprovals(true),
      defaults: {
        persona: DEFAULT_PERSONA,
        models: Object.fromEntries(providers.map((name) => [name, { ...(MODELS[name] ?? { brain: "", fast: "" }) }])),
      },
      providers,
      unpriced,
    };
  }

  // -- sessions ---------------------------------------------------------------------------

  listSessions(sub?: string): SessionRow[] {
    const rows =
      sub === undefined
        ? this.sql.exec<SessionRow>(
            "SELECT id, sub, title, created_at, updated_at FROM sessions ORDER BY updated_at DESC LIMIT ?",
            SESSIONS_LISTED,
          )
        : this.sql.exec<SessionRow>(
            "SELECT id, sub, title, created_at, updated_at FROM sessions WHERE sub = ? ORDER BY updated_at DESC LIMIT ?",
            sub,
            SESSIONS_LISTED,
          );
    return rows.toArray();
  }

  private sessionRow(id: string): SessionRow | null {
    return (
      this.sql
        .exec<SessionRow>("SELECT id, sub, title, created_at, updated_at FROM sessions WHERE id = ?", id)
        .toArray()[0] ?? null
    );
  }

  private messagesOf(session: string, limit?: number): StoredMessage[] {
    const rows = this.sql
      .exec<{ id: number; role: string; content: string; at: number }>(
        limit === undefined
          ? "SELECT id, role, content, at FROM messages WHERE session = ? ORDER BY id"
          : "SELECT * FROM (SELECT id, role, content, at FROM messages WHERE session = ? ORDER BY id DESC LIMIT ?) ORDER BY id",
        ...(limit === undefined ? [session] : [session, limit]),
      )
      .toArray();
    return rows.map((row) => ({
      id: row.id,
      role: row.role === "assistant" ? "assistant" : "user",
      content: JSON.parse(row.content) as Message["content"],
      at: row.at,
    }));
  }

  session(id: string): Outcome<{ session: SessionRow; messages: StoredMessage[]; approvals: ApprovalCard[] }> {
    const session = this.sessionRow(id);
    if (session === null) return fail(404, "not_found");
    const approvals = this.sql
      .exec<ApprovalRow>("SELECT * FROM approvals WHERE session = ? ORDER BY created_at", id)
      .toArray()
      .map(card);
    return ok({ session, messages: this.messagesOf(id), approvals });
  }

  newSession(sub: string): Outcome<SessionRow> {
    if (sub !== "" && this.subRow(sub) === null) return fail(404, "not_found", `no sub-tau /${sub}`);
    const now = nowSeconds();
    const row: SessionRow = { id: randomToken(12), sub, title: "", created_at: now, updated_at: now };
    this.sql.exec(
      "INSERT INTO sessions (id, sub, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
      row.id,
      row.sub,
      row.title,
      row.created_at,
      row.updated_at,
    );
    return ok(row);
  }

  deleteSession(id: string): Outcome<null> {
    if (this.sessionRow(id) === null) return fail(404, "not_found");
    if (this.busy.has(id)) return fail(409, "busy");
    this.sql.exec("DELETE FROM messages WHERE session = ?", id);
    this.sql.exec("DELETE FROM approvals WHERE session = ?", id);
    this.sql.exec("DELETE FROM sessions WHERE id = ?", id);
    return ok(null);
  }

  private append(session: string, message: Message): void {
    const now = nowSeconds();
    this.sql.exec(
      "INSERT INTO messages (session, role, content, at) VALUES (?, ?, ?, ?)",
      session,
      message.role,
      JSON.stringify(message.content),
      now,
    );
    this.sql.exec("UPDATE sessions SET updated_at = ? WHERE id = ?", now, session);
  }

  private recordSpend(kind: string, role: ModelRole, sub: string, model: string, usage: Usage): void {
    const provider = this.provider() ?? "fake";
    const price = priceFor(provider, model);
    const now = nowSeconds();
    this.sql.exec(
      `INSERT INTO spend (at, month, kind, role, sub, provider, model, input, output, cache_read, cache_write, cost_usd)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
      now,
      monthOf(now),
      kind,
      role,
      sub,
      provider,
      model,
      usage.input,
      usage.output,
      usage.cacheRead,
      usage.cacheWrite,
      price === null ? null : cost(usage, price),
    );
  }

  // -- sub-taus ---------------------------------------------------------------------------

  private subRow(name: string): (SubTau & { created_at: number; updated_at: number }) | null {
    const row = this.sql
      .exec<{ def: string; created_at: number; updated_at: number }>(
        "SELECT def, created_at, updated_at FROM subs WHERE name = ?",
        name,
      )
      .toArray()[0];
    if (row === undefined) return null;
    return { ...(JSON.parse(row.def) as SubTau), created_at: row.created_at, updated_at: row.updated_at };
  }

  private visitsToday(name: string, now = nowSeconds()): number {
    const row = this.sql
      .exec<{ count: number }>("SELECT count FROM visit_days WHERE day = ? AND sub = ?", dayOf(now), name)
      .toArray()[0];
    return row?.count ?? 0;
  }

  listSubs(): SubRow[] {
    const now = nowSeconds();
    return this.sql
      .exec<{ name: string }>("SELECT name FROM subs ORDER BY name")
      .toArray()
      .map((row) => this.subRow(row.name))
      .filter((sub): sub is SubTau & { created_at: number; updated_at: number } => sub !== null)
      .map((sub) => ({ ...sub, visits_today: this.visitsToday(sub.name, now) }));
  }

  getSub(name: string): Outcome<SubRow> {
    const sub = this.subRow(name);
    if (sub === null) return fail(404, "not_found");
    return ok({ ...sub, visits_today: this.visitsToday(name) });
  }

  private insertSub(sub: SubTau): void {
    const now = nowSeconds();
    this.sql.exec(
      "INSERT INTO subs (name, def, created_at, updated_at) VALUES (?, ?, ?, ?)",
      sub.name,
      JSON.stringify(sub),
      now,
      now,
    );
  }

  createSub(input: Json): Outcome<SubRow> {
    let sub: SubTau;
    try {
      sub = validateSub(input);
    } catch (err) {
      if (err instanceof SubTauError) return fail(400, "invalid_sub", err.message);
      throw err;
    }
    if (this.subRow(sub.name) !== null) return fail(409, "exists", `/${sub.name} already exists.`);
    this.insertSub(sub);
    return this.getSub(sub.name);
  }

  updateSub(name: string, input: Json): Outcome<SubRow> {
    const current = this.subRow(name);
    if (current === null) return fail(404, "not_found");
    let sub: SubTau;
    try {
      const { created_at: _created, updated_at: _updated, ...fields } = current;
      sub = validateSub({ ...fields, ...input, name });
    } catch (err) {
      if (err instanceof SubTauError) return fail(400, "invalid_sub", err.message);
      throw err;
    }
    this.sql.exec("UPDATE subs SET def = ?, updated_at = ? WHERE name = ?", JSON.stringify(sub), nowSeconds(), name);
    return this.getSub(name);
  }

  deleteSub(name: string): Outcome<null> {
    if (this.subRow(name) === null) return fail(404, "not_found");
    const sessions = this.sql.exec<{ id: string }>("SELECT id FROM sessions WHERE sub = ?", name).toArray();
    if (sessions.some((row) => this.busy.has(row.id))) return fail(409, "busy");
    for (const { id } of sessions) {
      this.sql.exec("DELETE FROM messages WHERE session = ?", id);
      this.sql.exec("DELETE FROM approvals WHERE session = ?", id);
    }
    this.sql.exec("DELETE FROM sessions WHERE sub = ?", name);
    const threads = this.sql.exec<{ id: string }>("SELECT id FROM visit_threads WHERE sub = ?", name).toArray();
    for (const { id } of threads) this.sql.exec("DELETE FROM visit_messages WHERE thread = ?", id);
    this.sql.exec("DELETE FROM visit_threads WHERE sub = ?", name);
    this.sql.exec("DELETE FROM visit_days WHERE sub = ?", name);
    this.sql.exec("DELETE FROM subs WHERE name = ?", name);
    return ok(null);
  }

  templates() {
    return TEMPLATES;
  }

  /** A draft from a description, by the brain (ADR 0012 §3); the owner reads it before saving. */
  async draft(name: unknown, description: unknown): Promise<Outcome<{ about: string; persona: string }>> {
    let checked: string;
    try {
      checked = validateName(name);
    } catch (err) {
      if (err instanceof SubTauError) return fail(400, "invalid_sub", err.message);
      throw err;
    }
    if (typeof description !== "string" || !description.trim()) {
      return fail(400, "bad_request", "the description is empty; say what the sub-tau should do");
    }
    const ready = this.ready();
    if (!ready.ok) return ready;
    const budget = this.budget();
    if (budget.exhausted) return fail(402, "budget", JSON.stringify(budget));
    const model = this.models().brain;
    try {
      const client = await this.client();
      const response = await client.complete({
        model,
        system: DRAFT_PERSONA,
        messages: [{ role: "user", content: [{ type: "text", text: draftPrompt(checked, description) }] }],
        tools: [],
        maxTokens: MAX_TOKENS,
      });
      this.recordSpend("draft", "brain", checked, model, response.usage);
      return ok(parseDraft(textOf(response.content)));
    } catch (err) {
      if (err instanceof DraftError) return fail(502, "draft_failed", err.message);
      const failure = providerFailure(err);
      return fail(502, failure.code, failure.detail);
    }
  }

  // -- approvals --------------------------------------------------------------------------

  listApprovals(pendingOnly = false): ApprovalCard[] {
    const rows = pendingOnly
      ? this.sql.exec<ApprovalRow>("SELECT * FROM approvals WHERE status = 'pending' ORDER BY created_at")
      : this.sql.exec<ApprovalRow>("SELECT * FROM approvals ORDER BY created_at DESC LIMIT 50");
    return rows.toArray().map(card);
  }

  private pendingIn(session: string): boolean {
    return (
      this.sql.exec("SELECT 1 FROM approvals WHERE session = ? AND status = 'pending'", session).toArray().length > 0
    );
  }

  // -- the owner's turns ------------------------------------------------------------------

  /** Onboarded with a provider (and its key): turns can run. */
  private ready(): Outcome<null> {
    if (!this.settings().onboarded || this.provider() === null) {
      return fail(409, "not_onboarded", "choose a provider and paste its key first");
    }
    return ok(null);
  }

  /** The main tau's tools (ADR 0013 §2); issue 162 adds net_send (tier 2) here. */
  private tools(): HostTool[] {
    return [
      {
        spec: ASK_SUB_SPEC,
        tier: 0,
        run: (input) => this.askSub(input),
      },
      {
        spec: CREATE_SUB_SPEC,
        tier: 2,
        effect: CREATE_EFFECT,
        run: async (input) => this.createSubTool(input),
      },
    ];
  }

  private listing(): string {
    const subs = this.listSubs();
    if (subs.length === 0) return "The owner has no sub-taus yet.";
    return ["The owner's sub-taus (ask one with ask_sub):", ...subs.map((sub) => `- ${sub.name}: ${sub.about}`)].join("\n");
  }

  private async askSub(input: Json): Promise<{ text: string; error?: boolean }> {
    const wanted = String(input.name ?? "").trim().replace(/^\//, "");
    if (!wanted) return { text: this.listing() };
    const sub = this.subRow(wanted);
    if (sub === null) return { text: `There is no sub-tau named /${wanted}. ${this.listing()}` };
    const question = String(input.question ?? "").trim();
    if (!question) return { text: "The question is empty; say what the sub-tau should answer." };
    const budget = this.budget();
    if (budget.exhausted) return { text: `/${sub.name} was not asked: this month's budget is used up.`, error: true };
    const model = this.models()[sub.role];
    const client = await this.client();
    const response = await client.complete({
      model,
      system: systemPrompt(subPersona(sub), profileSection(this.get<string>("profile")), {
        now: nowSeconds(),
        budget: budgetLine(budget),
      }),
      messages: [{ role: "user", content: [{ type: "text", text: question }] }],
      tools: [],
      maxTokens: MAX_TOKENS,
    });
    this.recordSpend("ask_sub", sub.role, sub.name, model, response.usage);
    const answer = textOf(response.content);
    return answer
      ? { text: `/${sub.name} answered:\n${answer}` }
      : { text: `/${sub.name} gave no answer.` };
  }

  private createSubTool(input: Json): { text: string; error?: boolean } {
    const name = String(input.name ?? "").trim().replace(/^\//, "");
    let sub: SubTau;
    try {
      sub = validateSub({ name, about: input.about, persona: input.persona });
    } catch (err) {
      if (err instanceof SubTauError) return { text: `Not created: ${err.message}`, error: true };
      throw err;
    }
    if (this.subRow(sub.name) !== null) {
      return { text: `Not created: /${sub.name} already exists; an existing sub-tau is never replaced.`, error: true };
    }
    this.insertSub(sub);
    return {
      text: `Created /${sub.name}. Ask it with ask_sub; the owner can talk to it and change it in the app.`,
    };
  }

  /**
   * The approver of the owner's turns. It never approves: it stores a pending approval card
   * (streamed to the app by the caller) and pauses the turn. `created` collects the ids.
   */
  private approver(session: string, created: string[], emit?: (event: Json) => void): Approver {
    return {
      request: async (call: ToolUseBlock, tool: HostTool) => {
        const now = nowSeconds();
        const id = randomToken(12);
        this.sql.exec(
          `INSERT INTO approvals (id, session, tool, call_id, input, effect, status, created_at, expires_at, turn)
           VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?, '')`,
          id,
          session,
          call.name,
          call.id,
          JSON.stringify(call.input),
          tool.effect ?? "",
          now,
          now + APPROVAL_SECONDS,
        );
        created.push(id);
        const row = this.sql.exec<ApprovalRow>("SELECT * FROM approvals WHERE id = ?", id).toArray()[0];
        if (row !== undefined) emit?.({ t: "approval", approval: card(row) });
        return "pending";
      },
    };
  }

  /**
   * Runs (or resumes) a turn in the background and returns its NDJSON stream at once.
   * Every message is stored as it completes, so the turn survives a closed tab.
   */
  private stream(
    session: SessionRow,
    history: Message[],
    resume?: { paused: PausedTurn; resolution: Resolution },
    role: ModelRole = "brain",
  ): Response {
    const { readable, writable } = new TransformStream<Uint8Array, Uint8Array>();
    const writer = writable.getWriter();
    const encoder = new TextEncoder();
    let open = true;
    const write = (event: Json | TurnEvent): void => {
      if (!open) return;
      writer.write(encoder.encode(`${JSON.stringify(event)}\n`)).catch(() => {
        open = false;
      });
    };
    this.busy.add(session.id);
    const run = async (): Promise<void> => {
      const created: string[] = [];
      try {
        write({ t: "start", session: session.id, sub: session.sub });
        const sub = session.sub ? this.subRow(session.sub) : null;
        if (session.sub && sub === null) {
          write({ t: "error", code: "not_found", detail: `no sub-tau /${session.sub}` });
          return;
        }
        const budget = this.budget();
        const persona = sub ? subPersona(sub) : personaText(this.get<string>("persona"));
        const system = systemPrompt(persona, profileSection(this.get<string>("profile")), {
          now: nowSeconds(),
          budget: budgetLine(budget),
        });
        const model = this.models()[role];
        const client = await this.client();
        const outcome = await runTurn({
          provider: client,
          model,
          system,
          history,
          // Sub-taus get no tools: a hosted tau's only tools are the ones a sub-tau may never use.
          tools: sub ? [] : this.tools(),
          approver: this.approver(session.id, created, write),
          hooks: {
            emit: write,
            append: (message) => this.append(session.id, message),
            usage: (usage) => this.recordSpend(sub ? "sub" : "chat", role, session.sub, model, usage),
            mayCallModel: () => !this.budget().exhausted,
          },
          resume,
        });
        if (outcome.status === "paused") {
          const id = created.at(-1);
          const turn: StoredTurn = { ...outcome.paused, sub: session.sub, role };
          if (id !== undefined) this.sql.exec("UPDATE approvals SET turn = ? WHERE id = ?", JSON.stringify(turn), id);
          await this.scheduleAlarm();
          write({ t: "done", stop: "paused", approval: id ?? null, budget: this.budget() });
        } else {
          write({ t: "done", stop: outcome.stop, budget: this.budget() });
        }
      } catch (err) {
        const failure = providerFailure(err);
        if (failure.code === "internal") {
          console.error(JSON.stringify({ event: "turn_failed", error: err instanceof Error ? err.name : "error" }));
        }
        write({ t: "error", code: failure.code, detail: failure.detail });
      } finally {
        this.busy.delete(session.id);
        if (open) await writer.close().catch(() => undefined);
      }
    };
    this.ctx.waitUntil(run());
    return new Response(readable, {
      status: 200,
      headers: { "content-type": NDJSON, "cache-control": "no-store", "x-content-type-options": "nosniff" },
    });
  }

  /** One owner message: in `session`, or in a new session with the main tau or `sub`. */
  async chat(input: { session?: unknown; sub?: unknown; text?: unknown }): Promise<Response> {
    const text = typeof input.text === "string" ? input.text.trim() : "";
    if (!text) return failResponse(fail(400, "bad_request", "text is empty"));
    if (text.length > CHAT_TEXT_MAX) return failResponse(fail(413, "too_large", `at most ${CHAT_TEXT_MAX} characters`));
    const ready = this.ready();
    if (!ready.ok) return failResponse(ready);
    // Every refusal comes before a new session is made, so a refused turn leaves nothing.
    const budget = this.budget();
    if (budget.exhausted) return failResponse(fail(402, "budget", JSON.stringify(budget)));

    let session: SessionRow | null;
    if (typeof input.session === "string" && input.session) {
      session = this.sessionRow(input.session);
      if (session === null) return failResponse(fail(404, "not_found", "no such session"));
      if (this.busy.has(session.id)) return failResponse(fail(409, "busy", "a turn is running in this session"));
      if (this.pendingIn(session.id)) {
        return failResponse(fail(409, "awaiting_approval", "answer the approval in this session first"));
      }
    } else {
      const wanted = typeof input.sub === "string" ? input.sub : "";
      const created = this.newSession(wanted);
      if (!created.ok) return failResponse(created);
      session = created.value;
    }

    const sub = session.sub ? this.subRow(session.sub) : null;
    const role: ModelRole = sub?.role ?? "brain";
    const user: Message = { role: "user", content: [{ type: "text", text }] };
    if (!session.title) {
      this.sql.exec("UPDATE sessions SET title = ? WHERE id = ?", title(text), session.id);
      session = { ...session, title: title(text) };
    }
    this.append(session.id, user);
    const history = normalizeHistory(this.messagesOf(session.id, HISTORY_MESSAGES));
    return this.stream(session, history, undefined, role);
  }

  /** The owner's answer to an approval card: the call runs (approve) or is refused (deny). */
  async decide(id: string, decision: unknown): Promise<Response> {
    if (decision !== "approve" && decision !== "deny") {
      return failResponse(fail(400, "bad_request", "decision must be approve or deny"));
    }
    const row = this.sql.exec<ApprovalRow>("SELECT * FROM approvals WHERE id = ?", id).toArray()[0];
    if (row === undefined) return failResponse(fail(404, "not_found"));
    if (row.status !== "pending") return failResponse(fail(409, "decided", row.status));
    if (nowSeconds() >= row.expires_at) {
      this.expire(row);
      return failResponse(fail(409, "decided", "expired"));
    }
    const session = this.sessionRow(row.session);
    if (session === null || !row.turn) {
      this.sql.exec("UPDATE approvals SET status = 'denied', decided_at = ? WHERE id = ?", nowSeconds(), id);
      return failResponse(fail(409, "stale", "the turn of this approval is gone"));
    }
    if (this.busy.has(session.id)) return failResponse(fail(409, "busy"));
    const resolution: Resolution = decision === "approve" ? "approved" : "denied";
    this.sql.exec("UPDATE approvals SET status = ?, decided_at = ? WHERE id = ?", resolution, nowSeconds(), id);
    const turn = JSON.parse(row.turn) as StoredTurn;
    const history = normalizeHistory(this.messagesOf(session.id, HISTORY_MESSAGES), true);
    return this.stream(session, history, { paused: turn, resolution }, turn.role);
  }

  /**
   * An approval nobody answered: the call is refused, the calls after it in the same message
   * are not run, and the answers go into the session so the next turn starts cleanly. No
   * model call: nobody is there to read it.
   */
  private expire(row: ApprovalRow): void {
    this.sql.exec("UPDATE approvals SET status = 'expired', decided_at = ? WHERE id = ?", nowSeconds(), row.id);
    if (!row.turn || this.sessionRow(row.session) === null) return;
    const turn = JSON.parse(row.turn) as StoredTurn;
    const results = [...turn.results];
    turn.queue.forEach((call, index) => {
      results.push({
        type: "tool_result",
        id: call.id,
        name: call.name,
        text: index === 0 ? refusal(call.name, "expired") : TOOL_LIMIT_NOTE,
        error: true,
      });
    });
    this.append(row.session, { role: "user", content: results });
  }

  // -- visitors ---------------------------------------------------------------------------

  /** A public web sub-tau as visitors see it, or null. */
  visitInfo(name: string): PublicSubInfo | null {
    if (!this.exists()) return null;
    const sub = this.subRow(name);
    if (sub === null || !isWebSub(sub)) return null;
    return { handle: this.handle(), name: sub.name, about: sub.about, starters: sub.starters };
  }

  /**
   * One visitor turn (ADR 0013 §5): the sub-tau's persona and public note, no profile, no
   * tools, no approvals; within `web_daily`, the budget, 10 messages a minute per IP, 2 000
   * characters, 50 messages and 24 hours per thread.
   */
  async visit(
    name: string,
    input: { visitor?: unknown; thread?: unknown; text?: unknown },
    ipHash: string | null,
  ): Promise<Outcome<VisitReply>> {
    const sub = this.exists() ? this.subRow(name) : null;
    if (sub === null || !isWebSub(sub)) return fail(404, "not_found");
    const visitor = input.visitor;
    if (typeof visitor !== "string" || !/^[A-Za-z0-9_-]{8,64}$/.test(visitor)) {
      return fail(400, "bad_request", "visitor must be 8 to 64 characters of A-Z a-z 0-9 _ -");
    }
    const text = typeof input.text === "string" ? input.text.trim() : "";
    if (!text) return fail(400, "bad_request", "text is empty");
    if (text.length > VISIT_TEXT_MAX) return fail(413, "too_large", `at most ${VISIT_TEXT_MAX} characters`);
    if (input.thread !== undefined && input.thread !== null && typeof input.thread !== "string") {
      return fail(400, "bad_request", "thread must be text");
    }
    if (this.provider() === null || !this.settings().onboarded) return fail(503, "unavailable");

    const now = nowSeconds();
    if (ipHash !== null) {
      const recent = this.sql
        .exec<{ n: number }>("SELECT COUNT(*) AS n FROM visit_hits WHERE ip = ? AND at > ?", ipHash, now - 60)
        .toArray()[0]?.n ?? 0;
      if (recent >= VISITS_PER_MINUTE) return fail(429, "rate_limited");
      this.sql.exec("INSERT INTO visit_hits (ip, at) VALUES (?, ?)", ipHash, now);
    }

    let thread: string;
    const isNew = !(typeof input.thread === "string" && input.thread);
    if (typeof input.thread === "string" && input.thread) {
      const row = this.sql
        .exec<{ sub: string; visitor: string; expires_at: number; messages: number }>(
          "SELECT sub, visitor, expires_at, messages FROM visit_threads WHERE id = ?",
          input.thread,
        )
        .toArray()[0];
      if (row === undefined || row.sub !== name || row.visitor !== visitor || row.expires_at <= now) {
        return fail(404, "unknown_thread");
      }
      if (row.messages + 2 > THREAD_MESSAGES_MAX) return fail(409, "thread_full");
      thread = input.thread;
    } else {
      thread = randomToken(16);
    }

    if (this.visitsToday(name, now) >= sub.web_daily) return fail(429, "daily_cap");
    const budget = this.budget(now);
    if (budget.exhausted) return fail(402, "budget");
    this.sql.exec(
      `INSERT INTO visit_days (day, sub, count) VALUES (?, ?, 1)
       ON CONFLICT (day, sub) DO UPDATE SET count = count + 1`,
      dayOf(now),
      name,
    );

    const history: HistoryLine[] = this.sql
      .exec<{ role: string; text: string }>("SELECT role, text FROM visit_messages WHERE thread = ? ORDER BY id", thread)
      .toArray()
      .map((row) => ({ direction: row.role === "sub" ? "out" : "in", text: row.text }));
    const model = this.models()[sub.role];
    let reply: string;
    try {
      const client = await this.client();
      const response = await client.complete({
        model,
        system: systemPrompt(subPersona(sub), publicNoteSection(sub.public_note), { now, budget: "", visitor: true }),
        messages: [{ role: "user", content: [{ type: "text", text: visitFrame(sub.name, text, history) }] }],
        tools: [],
        maxTokens: MAX_TOKENS,
      });
      this.recordSpend("visit", sub.role, sub.name, model, response.usage);
      reply = stripNoReply(textOf(response.content));
    } catch (err) {
      const failure = providerFailure(err);
      return fail(502, failure.code, failure.detail);
    }
    if (isNoReply(reply)) return fail(502, "no_reply");
    reply = reply.slice(0, VISIT_TEXT_MAX * 2);

    const at = nowSeconds();
    if (isNew) {
      this.sql.exec(
        "INSERT INTO visit_threads (id, sub, visitor, created_at, expires_at, messages) VALUES (?, ?, ?, ?, ?, 0)",
        thread,
        name,
        visitor,
        at,
        at + THREAD_SECONDS,
      );
      await this.scheduleAlarm();
    }
    this.sql.exec("INSERT INTO visit_messages (thread, role, text, at) VALUES (?, 'visitor', ?, ?)", thread, text, at);
    const id = this.sql
      .exec<{ id: number }>("INSERT INTO visit_messages (thread, role, text, at) VALUES (?, 'sub', ?, ?) RETURNING id", thread, reply, at)
      .toArray()[0]?.id;
    this.sql.exec("UPDATE visit_threads SET messages = messages + 2 WHERE id = ?", thread);
    return ok({ thread, reply: { id: String(id ?? 0), text: reply, ts: at } });
  }

  /** The visitor threads of a sub-tau (the last 24 hours), for its owner. */
  visitorThreads(name: string): Outcome<{ id: string; created_at: number; messages: { role: string; text: string; at: number }[] }[]> {
    if (this.subRow(name) === null) return fail(404, "not_found");
    const threads = this.sql
      .exec<{ id: string; created_at: number }>(
        "SELECT id, created_at FROM visit_threads WHERE sub = ? AND expires_at > ? ORDER BY created_at DESC LIMIT 50",
        name,
        nowSeconds(),
      )
      .toArray();
    return ok(
      threads.map((thread) => ({
        ...thread,
        messages: this.sql
          .exec<{ role: string; text: string; at: number }>(
            "SELECT role, text, at FROM visit_messages WHERE thread = ? ORDER BY id",
            thread.id,
          )
          .toArray(),
      })),
    );
  }

  // -- export, delete, alarm --------------------------------------------------------------

  exportAll(): Json {
    const settings = this.settings();
    return {
      format: "tau-host-export/1",
      exported_at: nowSeconds(),
      handle: this.handle(),
      github_id: this.get<number>("github_id"),
      created_at: this.get<number>("created_at"),
      settings: {
        provider: settings.provider,
        key_last4: settings.key_last4,
        models: settings.models,
        budget_usd: settings.budget_usd,
        language: settings.language,
        persona: settings.persona,
        profile: settings.profile,
        universe: settings.universe,
      },
      subs: this.listSubs(),
      sessions: this.sql
        .exec<SessionRow>("SELECT id, sub, title, created_at, updated_at FROM sessions ORDER BY created_at")
        .toArray()
        .map((session) => ({ ...session, messages: this.messagesOf(session.id) })),
      approvals: this.sql.exec<ApprovalRow>("SELECT * FROM approvals ORDER BY created_at").toArray().map(card),
      spend: this.sql.exec("SELECT at, kind, role, sub, provider, model, input, output, cache_read, cache_write, cost_usd FROM spend ORDER BY id").toArray(),
      visits: this.sql
        .exec<{ id: string; sub: string; created_at: number; expires_at: number }>(
          "SELECT id, sub, created_at, expires_at FROM visit_threads ORDER BY created_at",
        )
        .toArray()
        .map((thread) => ({
          ...thread,
          messages: this.sql
            .exec("SELECT role, text, at FROM visit_messages WHERE thread = ? ORDER BY id", thread.id)
            .toArray(),
        })),
    };
  }

  /** Deletes everything of this tau (the account is deleted by the Worker). */
  async destroy(): Promise<void> {
    await this.ctx.storage.deleteAlarm();
    await this.ctx.storage.deleteAll();
    this.migrate();
    this.sql.exec("DELETE FROM settings");
  }

  private async scheduleAlarm(): Promise<void> {
    const next = this.sql
      .exec<{ at: number | null }>(
        `SELECT MIN(at) AS at FROM (
           SELECT MIN(expires_at) AS at FROM approvals WHERE status = 'pending'
           UNION ALL SELECT MIN(expires_at) FROM visit_threads
         )`,
      )
      .toArray()[0]?.at;
    if (next === null || next === undefined) return;
    const when = next * 1000;
    const current = await this.ctx.storage.getAlarm();
    if (current === null || when < current) await this.ctx.storage.setAlarm(when);
  }

  override async alarm(): Promise<void> {
    const now = nowSeconds();
    const due = this.sql
      .exec<ApprovalRow>("SELECT * FROM approvals WHERE status = 'pending' AND expires_at <= ?", now)
      .toArray();
    for (const row of due) this.expire(row);
    const old = this.sql.exec<{ id: string }>("SELECT id FROM visit_threads WHERE expires_at <= ?", now).toArray();
    for (const { id } of old) this.sql.exec("DELETE FROM visit_messages WHERE thread = ?", id);
    this.sql.exec("DELETE FROM visit_threads WHERE expires_at <= ?", now);
    this.sql.exec("DELETE FROM visit_hits WHERE at <= ?", now - 60);
    this.sql.exec("DELETE FROM visit_days WHERE day < ?", dayOf(now - 2 * 86_400));
    await this.scheduleAlarm();
  }
}

interface ApprovalRow {
  id: string;
  session: string;
  tool: string;
  call_id: string;
  input: string;
  effect: string;
  status: string;
  created_at: number;
  expires_at: number;
  decided_at: number | null;
  turn: string;
  [key: string]: SqlStorageValue;
}

function card(row: ApprovalRow): ApprovalCard {
  const status = row.status;
  return {
    id: row.id,
    session: row.session,
    tool: row.tool,
    call_id: row.call_id,
    input: JSON.parse(row.input) as Record<string, unknown>,
    effect: row.effect,
    status: status === "approved" || status === "denied" || status === "expired" ? status : "pending",
    created_at: row.created_at,
    expires_at: row.expires_at,
    decided_at: row.decided_at,
  };
}
