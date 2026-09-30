/**
 * A hosted tau on the tau network (ADR 0013 §4): what tau-net's `NetNode` does on a hub, in
 * the tau's `Tau` Durable Object, with the spine's inbox in front of it.
 *
 * **Identity.** An Ed25519 and an X25519 key, generated on first need and kept sealed with
 * the vault (`seal(VAULT_KEY, handle, "net_key", …)`). They are never returned or logged.
 *
 * **The inbox** (`inbox`, after the Worker's cheap checks in src/net/routes.ts) keeps the
 * spine's order and codes: the sender's card (fetched, cached an hour), the signature, a
 * duplicate `(from, id)`, 60 envelopes per sender an hour and 1 000 waiting ones. An accepted
 * envelope is stored in `net_queue`, answered with `202 {"status": "accepted", "id"}`, and
 * handled right after in this object (`drain`, kept alive with `waitUntil`). One that was
 * not handled (the object was evicted mid-turn) is taken again by the alarm, at most three
 * times; replies have deterministic ids, so the other tau never gets a second one.
 *
 * **Handling** is tau-net's hub behaviour (docs/reference/tau-network.md §6):
 *
 * - blocked senders and strangers (anything but a `contact_request`) are dropped before
 *   anything else; a pinned contact is verified with its pinned key ("key changed"
 *   otherwise), everyone else with the card, whose keys must match a pending contact's;
 * - the contacts state machine (`pending_in`, `pending_out`, `accepted`, `blocked`) with key
 *   pinning on acceptance; a new request waits for the owner in the app;
 * - a `message` from an accepted contact is a network turn: the persona and the public note,
 *   never the owner's profile, no tools, no approvals, in the other tau's language, with the
 *   untrusted-text frame, `[no reply]`, `max_hops` (6) and 20 auto-replies per contact and
 *   hour; the reply keeps `thread`, answers `id` and carries `hops + 1`;
 * - `sub` by hops parity: an even `hops` names one of this tau's sub-taus, which answers when
 *   it is public (an unknown or private one drops the message unanswered); an odd `hops`
 *   names the other tau's sub-tau, whose answer the main tau handles; every reply carries
 *   the `sub` it answered;
 * - a `visit` from the universe this tau joined, for a public web sub-tau within its
 *   `web_daily`: the universe's keys are pinned at its first visit, the answer goes back as a
 *   `message` and creates no contact and no link. On tau.getporti.com the universe reaches
 *   hosted web sub-taus through tau-host's visitor API instead; visits arrive at a tau-host
 *   that another universe lists (an own host in the public universe).
 *
 * **Sending** posts straight to the recipient's inbox (another hosted tau on this host
 * through this Worker's own handler, src/net/transport.ts). `202` or a `duplicate` counts as
 * delivered. Owner actions that speak for the owner (`add`, `sendMessage`) run only after
 * the owner approved them in the app (src/tau.ts).
 *
 * **The universe**: join, report and leave signed with the tau's key (src/net/universe.ts);
 * reports every hour from the alarm while the owner's choice is to be listed.
 */

import {
  aadFor,
  BadSignature,
  buildEnvelope,
  type Card,
  type Content,
  encodeEnvelope,
  EnvelopeError,
  fetchCard,
  Identity,
  inboxUrl,
  isObject,
  isSubName,
  makeCard,
  MAX_MESSAGE_CHARS,
  openBox,
  openVerified,
  parseAddress,
  parseCard,
  parseContent,
  parseJsonBytes,
  parsePayload,
  parseTarget,
  parseWireEnvelope,
  type Payload,
  peekSender,
  b64uDecode,
  type ReportedSub,
  verifySignature,
  type WireEnvelope,
} from "../../../shared/net/index.ts";
import { subPersona, publicNoteSection, systemPrompt, type HistoryLine } from "../agent/prompt";
import type { SubTau } from "../agent/subs";
import type { HostEnv } from "../env";
import { nowSeconds } from "../http";
import type { ModelRole } from "../providers";
import { open, seal } from "../vault";
import {
  CARD_CACHE_SECONDS,
  fixedNetHost,
  hostedAddress,
  INBOX_HOURLY_CAP,
  insecurePeers,
  LOG_LIMIT,
  MAX_AUTO_REPLIES_PER_HOUR,
  MAX_HOPS,
  netHost,
  QUEUE_CAP,
  QUEUE_RETRY_SECONDS,
  QUEUE_TRIES,
  REPORT_SECONDS,
  SEEN_SECONDS,
  SEND_TIMEOUT_MS,
  SOFTWARE,
  universeHost,
} from "./config";
import { buildFrame, buildVisitFrame, cleanName, cleanNote, NOT_SHARED_NET, replyId, subIsOurs } from "./frames";
import { type Fetcher, netFetcher } from "./transport";
import { listedAddresses, selectLinks, SUB_ABOUT_LIMIT, UniverseClient, UniverseError } from "./universe";

export const NET_KEY_PURPOSE = "net_key";
export const NET_NAME_LIMIT = 80;
export const NET_NOTE_LIMIT = 4000;
export const NET_OWNER_LIMIT = 60;
export const NET_ABOUT_LIMIT = 200;

export const SCHEMA = [
  `CREATE TABLE IF NOT EXISTS net_contacts (
    address TEXT PRIMARY KEY,
    state TEXT NOT NULL,
    name TEXT NOT NULL DEFAULT '',
    sign_key TEXT,
    box_key TEXT,
    note TEXT NOT NULL DEFAULT '',
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    accepted_at INTEGER
  )`,
  "CREATE TABLE IF NOT EXISTS net_replies (address TEXT NOT NULL, at INTEGER NOT NULL)",
  "CREATE INDEX IF NOT EXISTS net_replies_address ON net_replies (address, at)",
  `CREATE TABLE IF NOT EXISTS net_seen (
    sender TEXT NOT NULL,
    id TEXT NOT NULL,
    at INTEGER NOT NULL,
    PRIMARY KEY (sender, id)
  )`,
  "CREATE INDEX IF NOT EXISTS net_seen_at ON net_seen (sender, at)",
  `CREATE TABLE IF NOT EXISTS net_queue (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    sender TEXT NOT NULL,
    id TEXT NOT NULL,
    envelope TEXT NOT NULL,
    received_at INTEGER NOT NULL,
    tries INTEGER NOT NULL DEFAULT 0
  )`,
  `CREATE TABLE IF NOT EXISTS net_log (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER NOT NULL,
    direction TEXT NOT NULL,
    address TEXT NOT NULL,
    kind TEXT NOT NULL,
    id TEXT NOT NULL,
    thread TEXT NOT NULL,
    text TEXT NOT NULL,
    own_sub TEXT,
    peer_sub TEXT
  )`,
  "CREATE UNIQUE INDEX IF NOT EXISTS net_log_entry ON net_log (direction, address, id)",
  "CREATE INDEX IF NOT EXISTS net_log_address ON net_log (address, seq)",
  `CREATE TABLE IF NOT EXISTS net_counts (
    address TEXT PRIMARY KEY,
    n_in INTEGER NOT NULL DEFAULT 0,
    n_out INTEGER NOT NULL DEFAULT 0
  )`,
  `CREATE TABLE IF NOT EXISTS net_cards (
    address TEXT PRIMARY KEY,
    card TEXT NOT NULL,
    fetched_at INTEGER NOT NULL
  )`,
];

/** Every table of the network, for export and account deletion. */
export const TABLES = ["net_contacts", "net_replies", "net_seen", "net_queue", "net_log", "net_counts", "net_cards"];

export type ContactState = "pending_in" | "pending_out" | "accepted" | "blocked";
const STATES: readonly ContactState[] = ["pending_in", "pending_out", "accepted", "blocked"];

export interface Contact {
  address: string;
  state: ContactState;
  name: string;
  sign_key: string | null;
  box_key: string | null;
  note: string;
  created_at: number;
  updated_at: number;
  accepted_at: number | null;
}

export interface LogEntry {
  seq: number;
  ts: number;
  direction: "in" | "out";
  address: string;
  kind: string;
  id: string;
  thread: string;
  text: string;
  own_sub: string | null;
  peer_sub: string | null;
}

/** An owner action the network refused; the message is one plain English line. */
export class NetError extends Error {
  override name = "NetError";
}

/** An owner action the contact's state does not allow. */
export class ContactError extends NetError {
  override name = "ContactError";
}

/** An envelope the recipient did not take (`status` 0: no answer). */
export class DeliveryError extends NetError {
  override name = "DeliveryError";
  constructor(
    readonly address: string,
    readonly status: number,
    readonly code: string,
    readonly detail = "",
  ) {
    super(`delivery to ${address} failed: ${status ? `${status} ` : ""}${code}${detail ? ` (${detail})` : ""}`);
  }
}

export interface Delivery {
  address: string;
  id: string;
  status: string;
}

/** A model call of a network turn: no tools; null when refused, failed or `[no reply]`. */
export interface ModelCall {
  role: ModelRole;
  system: string;
  prompt: string;
  kind: "net" | "net_visit";
  sub: string;
}

/** What the `Tau` object lends its network. */
export interface NetDeps {
  readonly sql: SqlStorage;
  readonly env: HostEnv;
  handle(): string;
  get<T>(key: string): T | null;
  put(key: string, value: unknown): void;
  remove(key: string): void;
  /** One of the owner's sub-taus when it is public, else null. */
  publicSub(name: string): SubTau | null;
  /** Every public sub-tau, by name. */
  publicSubs(): SubTau[];
  /** The main tau's persona text. */
  persona(): string;
  answer(call: ModelCall): Promise<string | null>;
  /** Takes one visitor turn of `name` today when fewer than `cap` were taken. */
  takeVisit(name: string, cap: number, now: number): boolean;
  waitUntil(promise: Promise<unknown>): void;
  scheduleAlarm(): Promise<void>;
}

/** The inbox's answer (after the Worker's own checks). */
export interface InboxAnswer {
  status: number;
  body: { error?: string; detail?: string; status?: string; id?: string };
}

interface Transition {
  action: "notify" | "send_accept" | "send_request" | "accepted" | "turn" | "drop" | "none";
  contact: Contact | null;
  reason?: string;
}

interface TurnJob {
  contact: Contact;
  sender: string;
  envelopeId: string;
  thread: string;
  hops: number;
  text: string;
  history: HistoryLine[];
  /** This tau's public sub-tau that answers, or null for the main tau. */
  sub: SubTau | null;
  /** The other tau's sub-tau that wrote the message. */
  peerSub: string | null;
}

interface Handled {
  outcome: "handled" | "dropped";
  sender?: string;
  kind?: string;
  reason?: string;
  replied?: boolean;
}

/** Drop reasons strangers and visitors cause every day: logged as info, not as warnings. */
const QUIET_DROPS = [
  "blocked",
  "not a contact",
  "no public sub-tau",
  "not the joined universe",
  "not in the universe",
  "no web page",
  "over web_daily",
  "auto_reply is off",
];

export interface UniverseStatus {
  at: number;
  ok: boolean;
  action: "join" | "report" | "leave";
  error?: string;
  visible_links?: number;
  url?: string;
}

export interface UniverseView {
  host: string | null;
  choice: boolean | null;
  joined: boolean;
  last: UniverseStatus | null;
  next_at: number | null;
}

export interface ContactView extends Omit<Contact, "sign_key" | "box_key"> {
  messages: number;
}

export interface NetSummary {
  address: string | null;
  name: string;
  universe: UniverseView;
  contacts: ContactView[];
  pending: number;
}

function drop(reason: string, sender?: string, kind?: string): Handled {
  return { outcome: "dropped", reason, sender, kind };
}

/** The claimed kind of an unverified envelope, only to drop early. */
function peekKind(envelope: WireEnvelope): string | null {
  const bytes = b64uDecode(envelope.payload);
  const data = bytes === null ? undefined : parseJsonBytes(bytes);
  return isObject(data) && typeof data.kind === "string" ? data.kind : null;
}

function pinned(contact: Contact): boolean {
  return contact.state === "accepted" && !!contact.sign_key && !!contact.box_key;
}

function keysMatch(contact: Contact, signKey: string, boxKey: string): boolean {
  if (!contact.sign_key && !contact.box_key) return true;
  return contact.sign_key === signKey && contact.box_key === boxKey;
}

function clip(text: string, limit: number): string {
  return Array.from(text).slice(0, limit).join("");
}

function log(event: string, fields: Record<string, unknown>, level: "info" | "warn" = "info"): void {
  const line = JSON.stringify({ event, ...fields });
  if (level === "warn") console.warn(line);
  else console.log(line);
}

interface ContactRow {
  address: string;
  state: string;
  name: string;
  sign_key: string | null;
  box_key: string | null;
  note: string;
  created_at: number;
  updated_at: number;
  accepted_at: number | null;
  [key: string]: SqlStorageValue;
}

interface LogRow {
  seq: number;
  ts: number;
  direction: string;
  address: string;
  kind: string;
  id: string;
  thread: string;
  text: string;
  own_sub: string | null;
  peer_sub: string | null;
  [key: string]: SqlStorageValue;
}

function toContact(row: ContactRow): Contact | null {
  if (!(STATES as readonly string[]).includes(row.state)) return null;
  return { ...row, state: row.state as ContactState };
}

function toEntry(row: LogRow): LogEntry {
  return { ...row, direction: row.direction === "out" ? "out" : "in" };
}

export class NetNode {
  private identityPromise: Promise<Identity> | null = null;
  private draining: Promise<void> | null = null;

  constructor(private readonly deps: NetDeps) {}

  private get sql(): SqlStorage {
    return this.deps.sql;
  }

  private get env(): HostEnv {
    return this.deps.env;
  }

  /** Forgets what this object holds in memory (after the account's data was deleted). */
  reset(): void {
    this.identityPromise = null;
  }

  // -- where this tau lives ----------------------------------------------------------------

  /** Remembers the request's host as the net host (only when PUBLIC_HOST does not fix it). */
  noteHost(requestHost: string | null | undefined): void {
    if (fixedNetHost(this.env) || !requestHost) return;
    const host = netHost(this.env, requestHost);
    if (host !== null && this.deps.get<string>("net_host") !== host) this.deps.put("net_host", host);
  }

  host(): string | null {
    return netHost(this.env, this.deps.get<string>("net_host"));
  }

  address(): string | null {
    const host = this.host();
    return host === null ? null : hostedAddress(host, this.deps.handle());
  }

  private requireAddress(): string {
    const address = this.address();
    if (address === null) throw new NetError("this host has no network address yet (PUBLIC_HOST, or open the app once)");
    return address;
  }

  universe(): string | null {
    return universeHost(this.env, this.host());
  }

  private fetcher(): Fetcher {
    return netFetcher(this.env, this.host(), this.universe());
  }

  private autoReply(): boolean {
    return this.deps.get<boolean>("net_auto_reply") ?? true;
  }

  // -- identity and card -------------------------------------------------------------------

  /** The tau's identity, made and sealed on first need. Its seeds never leave this object. */
  identity(): Promise<Identity> {
    if (this.identityPromise === null) {
      this.identityPromise = this.loadIdentity().catch((err: unknown) => {
        this.identityPromise = null;
        throw err;
      });
    }
    return this.identityPromise;
  }

  private async loadIdentity(): Promise<Identity> {
    const handle = this.deps.handle();
    const sealed = this.deps.get<string>("net_identity");
    if (sealed !== null) {
      const json = await open(this.env.VAULT_KEY, handle, NET_KEY_PURPOSE, sealed);
      return Identity.fromJson(JSON.parse(json), "the vault");
    }
    const identity = await Identity.generate();
    const value = await seal(this.env.VAULT_KEY, handle, NET_KEY_PURPOSE, JSON.stringify(identity.toIdentityJson()));
    this.deps.put("net_identity", value);
    log("net_identity_created", { handle });
    return identity;
  }

  /** The name on the card: the owner's choice, else `@<handle>`. */
  name(): string {
    const name = cleanName(this.deps.get<string>("net_name") ?? "", NET_NAME_LIMIT);
    return name || `@${this.deps.handle()}`;
  }

  async card(): Promise<Card | null> {
    const address = this.address();
    if (address === null) return null;
    const identity = await this.identity();
    return makeCard({
      address,
      name: this.name(),
      signKey: identity.signKey,
      boxKey: identity.boxKey,
      software: SOFTWARE,
      allowInsecure: insecurePeers(this.env),
    });
  }

  /**
   * The card of `address`: this tau's own, a cached one (an hour), or a fresh fetch.
   * `fresh` skips the cache (the owner adding a contact).
   */
  async peerCard(address: string, fresh = false): Promise<Card | null> {
    if (address === this.address()) return this.card();
    const now = nowSeconds();
    if (!fresh) {
      const row = this.sql
        .exec<{ card: string; fetched_at: number }>("SELECT card, fetched_at FROM net_cards WHERE address = ?", address)
        .toArray()[0];
      if (row !== undefined && row.fetched_at > now - CARD_CACHE_SECONDS) {
        const cached = parseCard(JSON.parse(row.card), address);
        if (cached !== null) return cached;
      }
    }
    const card = await fetchCard(address, {
      allowInsecure: insecurePeers(this.env),
      userAgent: SOFTWARE,
      fetcher: this.fetcher() as typeof fetch,
    });
    if (card !== null) {
      this.sql.exec(
        `INSERT INTO net_cards (address, card, fetched_at) VALUES (?, ?, ?)
         ON CONFLICT (address) DO UPDATE SET card = excluded.card, fetched_at = excluded.fetched_at`,
        address,
        JSON.stringify(card),
        now,
      );
    }
    return card;
  }

  // -- the inbox ---------------------------------------------------------------------------

  /**
   * The spine's checks after the Worker's (docs/reference/tau-network.md §4): the sender's
   * card, the signature, a duplicate, the hourly cap, the queue cap. Then the envelope waits
   * in `net_queue` and is handled right after the answer.
   */
  async inbox(wire: WireEnvelope, now = nowSeconds()): Promise<InboxAnswer> {
    const payloadBytes = b64uDecode(wire.payload);
    const sig = b64uDecode(wire.sig);
    if (payloadBytes === null || sig === null) return { status: 400, body: { error: "bad_request", detail: "not base64url" } };
    let header: Payload;
    try {
      header = parsePayload(parseJsonBytes(payloadBytes));
    } catch (err) {
      return { status: 400, body: { error: "bad_request", detail: err instanceof EnvelopeError ? err.reason : "bad payload" } };
    }
    const card = await this.peerCard(header.from);
    if (card === null) return { status: 502, body: { error: "sender_card_unavailable" } };
    if (!(await verifySignature(card.sign_key, payloadBytes, sig))) return { status: 403, body: { error: "bad_signature" } };
    const seen = this.sql.exec("SELECT 1 FROM net_seen WHERE sender = ? AND id = ?", header.from, header.id).toArray();
    if (seen.length > 0) return { status: 200, body: { status: "duplicate", id: header.id } };
    const recent =
      this.sql
        .exec<{ n: number }>("SELECT COUNT(*) AS n FROM net_seen WHERE sender = ? AND at > ?", header.from, now - 3600)
        .toArray()[0]?.n ?? 0;
    if (recent >= INBOX_HOURLY_CAP) return { status: 429, body: { error: "rate_limited" } };
    const waiting = this.sql.exec<{ n: number }>("SELECT COUNT(*) AS n FROM net_queue").toArray()[0]?.n ?? 0;
    if (waiting >= QUEUE_CAP) return { status: 503, body: { error: "mailbox_full" } };
    this.sql.exec("INSERT INTO net_seen (sender, id, at) VALUES (?, ?, ?)", header.from, header.id, now);
    this.sql.exec(
      "INSERT INTO net_queue (sender, id, envelope, received_at) VALUES (?, ?, ?, ?)",
      header.from,
      header.id,
      JSON.stringify({ payload: wire.payload, sig: wire.sig }),
      now,
    );
    log("net_envelope_accepted", { kind: header.kind, from: header.from });
    this.deps.waitUntil(this.drain());
    await this.deps.scheduleAlarm();
    return { status: 202, body: { status: "accepted", id: header.id } };
  }

  /** Handles every waiting envelope in order; one drain at a time. */
  drain(): Promise<void> {
    if (this.draining === null) {
      this.draining = this.drainAll().finally(() => {
        this.draining = null;
      });
    }
    return this.draining;
  }

  /** Waits until nothing is being handled (tests, and the account's deletion). */
  async settle(): Promise<void> {
    while (this.draining !== null) await this.draining;
  }

  private async drainAll(): Promise<void> {
    for (;;) {
      const row = this.sql
        .exec<{ seq: number; sender: string; envelope: string; tries: number }>(
          "SELECT seq, sender, envelope, tries FROM net_queue ORDER BY seq LIMIT 1",
        )
        .toArray()[0];
      if (row === undefined) return;
      this.sql.exec("UPDATE net_queue SET tries = tries + 1 WHERE seq = ?", row.seq);
      if (row.tries >= QUEUE_TRIES) {
        this.sql.exec("DELETE FROM net_queue WHERE seq = ?", row.seq);
        this.report(drop(`not handled after ${QUEUE_TRIES} tries`, row.sender));
        continue;
      }
      let handled: Handled;
      try {
        handled = await this.receive(parseWireEnvelope(JSON.parse(row.envelope)));
      } catch (err) {
        handled = drop(`internal error (${err instanceof Error ? err.name : "error"})`, row.sender);
      }
      this.sql.exec("DELETE FROM net_queue WHERE seq = ?", row.seq);
      this.report(handled);
    }
  }

  private report(handled: Handled): void {
    if (handled.outcome === "handled") {
      log("net_handled", { kind: handled.kind, from: handled.sender, replied: handled.replied ?? false });
      return;
    }
    const quiet = QUIET_DROPS.some((reason) => (handled.reason ?? "").includes(reason));
    log("net_dropped", { kind: handled.kind ?? "envelope", from: handled.sender ?? null, reason: handled.reason }, quiet ? "info" : "warn");
  }

  // -- receiving (tau-net's NetNode.receive) -----------------------------------------------

  private async receive(wire: WireEnvelope): Promise<Handled> {
    let sender: string;
    try {
      sender = peekSender(wire);
    } catch (err) {
      return drop(err instanceof EnvelopeError ? err.reason : "malformed envelope");
    }
    const contact = this.contact(sender);
    if (contact?.state === "blocked") return drop("blocked", sender);
    const claimed = peekKind(wire);
    if (claimed === "visit") return this.receiveVisit(wire, sender);

    let card: Card | null = null;
    let signKey = "";
    let boxKey = "";
    let payload: Payload;
    try {
      if (contact !== null && pinned(contact)) {
        signKey = contact.sign_key ?? "";
        boxKey = contact.box_key ?? "";
        try {
          payload = await openVerified(wire, signKey);
        } catch (err) {
          if (!(err instanceof BadSignature)) throw err;
          log("net_key_changed", { from: sender, detail: "does not verify with its pinned key" }, "warn");
          return drop("key changed", sender);
        }
      } else {
        if (contact === null && claimed !== "contact_request") return drop("not a contact", sender);
        card = await this.peerCard(sender);
        if (card === null) return drop("sender card unavailable", sender);
        signKey = card.sign_key;
        boxKey = card.box_key;
        payload = await openVerified(wire, signKey);
        if (contact !== null && !keysMatch(contact, signKey, boxKey)) {
          log("net_key_changed", { from: sender, detail: "the card no longer matches the stored keys" }, "warn");
          return drop("key changed", sender);
        }
      }
    } catch (err) {
      if (err instanceof BadSignature) return drop("bad signature", sender);
      if (err instanceof EnvelopeError) return drop(err.reason, sender);
      throw err;
    }
    const kind = payload.kind;
    if (payload.from !== sender) return drop("sender mismatch", sender, kind);
    if (payload.to !== this.address()) return drop("wrong recipient", sender, kind);
    let content: Content;
    try {
      const raw = await openBox(payload.box, await this.identity(), aadFor(payload.id, kind, payload.from, payload.to));
      content = parseContent(kind, raw);
    } catch (err) {
      if (err instanceof EnvelopeError) return drop(err.reason, sender, kind);
      throw err;
    }
    const text = "text" in content ? content.text : "";
    const entry: Omit<LogEntry, "seq"> = {
      ts: payload.ts,
      direction: "in",
      address: sender,
      kind,
      id: payload.id,
      thread: payload.thread,
      text,
      own_sub: null,
      peer_sub: null,
    };
    const name = ("name" in content && content.name) || card?.name || "";

    if (kind === "contact_request") {
      const transition = this.onRequest(sender, name, text, signKey, boxKey);
      if (transition.action === "drop") return drop(transition.reason ?? "dropped", sender, kind);
      this.appendLog(entry);
      if (transition.action === "notify") {
        log("net_contact_request", { from: sender });
      } else if (transition.action === "send_accept") {
        try {
          await this.send(sender, boxKey, "contact_accept", { name: this.name() });
        } catch (err) {
          log("net_accept_not_sent", { to: sender, error: err instanceof Error ? err.message : "error" }, "warn");
        }
      }
      return { outcome: "handled", sender, kind };
    }
    if (kind === "contact_accept") {
      const transition = this.onAccept(sender, name, signKey, boxKey);
      if (transition.action === "drop") return drop(transition.reason ?? "dropped", sender, kind);
      this.appendLog(entry);
      if (transition.action === "accepted") log("net_contact_accepted", { by: sender });
      return { outcome: "handled", sender, kind };
    }
    if (kind !== "message") return drop("unexpected kind", sender, kind);

    const transition = this.onMessage(sender);
    if (transition.action !== "turn" || transition.contact === null) {
      return drop(transition.reason ?? "dropped", sender, kind);
    }
    const subName = "sub" in content && typeof content.sub === "string" ? content.sub : null;
    let sub: SubTau | null = null;
    let peerSub: string | null = null;
    if (subName !== null && subIsOurs(payload.hops)) {
      sub = this.deps.publicSub(subName);
      if (sub === null) return drop(`no public sub-tau /${subName}`, sender, kind);
      entry.own_sub = subName;
    } else if (subName !== null) {
      peerSub = subName;
      entry.peer_sub = subName;
    }
    // The main tau and each of its sub-taus keep their own history with a contact.
    const history = this.history(sender, payload.id, entry.own_sub);
    if (this.appendLog(entry)) this.count(sender, "in");
    const job = this.turnJob(transition.contact, payload, text, history, sub, peerSub);
    if (job === null) return { outcome: "handled", sender, kind };
    const reply = await this.turn(job);
    const replied = await this.finish(job, reply);
    return { outcome: "handled", sender, kind, replied };
  }

  private history(address: string, excludeId: string, ownSub: string | null, thread?: string): HistoryLine[] {
    const rows =
      thread === undefined
        ? this.sql
            .exec<LogRow>("SELECT * FROM net_log WHERE address = ? AND id != ? AND own_sub IS ? ORDER BY seq", address, excludeId, ownSub)
            .toArray()
        : this.sql
            .exec<LogRow>(
              "SELECT * FROM net_log WHERE address = ? AND id != ? AND own_sub IS ? AND thread = ? ORDER BY seq",
              address,
              excludeId,
              ownSub,
              thread,
            )
            .toArray();
    return rows.map((row) => ({ direction: row.direction === "out" ? "out" : "in", text: row.text }));
  }

  private turnJob(
    contact: Contact,
    payload: Payload,
    text: string,
    history: HistoryLine[],
    sub: SubTau | null,
    peerSub: string | null,
  ): TurnJob | null {
    if (!this.autoReply()) return null;
    if (payload.hops + 1 > MAX_HOPS) {
      log("net_no_reply", { to: contact.address, reason: `a reply would be hop ${payload.hops + 1}, over max_hops ${MAX_HOPS}` });
      return null;
    }
    if (this.autoRepliesLastHour(contact.address) >= MAX_AUTO_REPLIES_PER_HOUR) {
      log("net_no_reply", { to: contact.address, reason: `${MAX_AUTO_REPLIES_PER_HOUR} auto-replies this hour` });
      return null;
    }
    return {
      contact,
      sender: contact.address,
      envelopeId: payload.id,
      thread: payload.thread,
      hops: payload.hops,
      text,
      history,
      sub,
      peerSub,
    };
  }

  /** The public note a sub-tau shows: its own, else the tau's (tau-net's rule). */
  private noteOf(sub: SubTau | null): string {
    const own = sub?.public_note.trim() ?? "";
    return own || (this.deps.get<string>("net_note") ?? "");
  }

  /** One network turn (the model is called only here); the reply, or null. */
  private turn(job: TurnJob): Promise<string | null> {
    const persona = job.sub ? subPersona(job.sub) : this.deps.persona();
    const system = systemPrompt(persona, publicNoteSection(this.noteOf(job.sub)), {
      now: nowSeconds(),
      budget: "",
      withheld: NOT_SHARED_NET,
    });
    const prompt = buildFrame({
      name: job.contact.name,
      address: job.sender,
      text: job.text,
      history: job.history,
      sub: job.sub?.name ?? null,
      peerSub: job.peerSub,
    });
    return this.deps.answer({ role: job.sub?.role ?? "brain", system, prompt, kind: "net", sub: job.sub?.name ?? "" });
  }

  /** Sends the reply of a network turn, if there is one; true when it was delivered. */
  private async finish(job: TurnJob, reply: string | null): Promise<boolean> {
    if (!reply) return false;
    const contact = this.contact(job.sender);
    if (contact === null || contact.state !== "accepted" || !contact.box_key) {
      log("net_no_reply", { to: job.sender, reason: "no longer a contact" });
      return false;
    }
    const content: Record<string, unknown> = { text: clip(reply, MAX_MESSAGE_CHARS) };
    const replySub = job.sub?.name ?? job.peerSub;
    if (replySub) content.sub = replySub;
    try {
      await this.send(job.sender, contact.box_key, "message", content, {
        thread: job.thread,
        replyTo: job.envelopeId,
        hops: job.hops + 1,
        id: await replyId(this.requireAddress(), job.sender, job.envelopeId),
      });
      this.recordAutoReply(job.sender);
      return true;
    } catch (err) {
      if (!(err instanceof NetError) && !(err instanceof EnvelopeError)) throw err;
      log("net_reply_not_sent", { to: job.sender, error: err.message }, "warn");
      return false;
    }
  }

  // -- visits (a universe relays an anonymous visitor of a public web sub-tau) -------------

  private async receiveVisit(wire: WireEnvelope, sender: string): Promise<Handled> {
    const kind = "visit";
    const universe = this.universe();
    if (universe === null || sender !== universe) return drop("not the joined universe", sender, kind);
    if (this.deps.get<boolean>("universe") !== true) return drop("not in the universe", sender, kind);
    const pins = this.deps.get<Record<string, { sign_key: string; box_key: string; pinned_at: number }>>("universe_pins") ?? {};
    const pin = pins[universe];
    let boxKey: string;
    let payload: Payload;
    try {
      if (pin !== undefined) {
        boxKey = pin.box_key;
        try {
          payload = await openVerified(wire, pin.sign_key);
        } catch (err) {
          if (!(err instanceof BadSignature)) throw err;
          log("net_key_changed", { from: sender, detail: "a visit does not verify with the universe's pinned key; leave and join trust a new key" }, "warn");
          return drop("key changed", sender, kind);
        }
      } else {
        const card = await this.peerCard(sender);
        if (card === null) return drop("sender card unavailable", sender, kind);
        payload = await openVerified(wire, card.sign_key);
        boxKey = card.box_key;
        this.deps.put("universe_pins", { ...pins, [universe]: { sign_key: card.sign_key, box_key: card.box_key, pinned_at: nowSeconds() } });
        log("net_universe_pinned", { universe });
      }
    } catch (err) {
      if (err instanceof BadSignature) return drop("bad signature", sender, kind);
      if (err instanceof EnvelopeError) return drop(err.reason, sender, kind);
      throw err;
    }
    if (payload.kind !== kind || payload.from !== sender) return drop("sender mismatch", sender, kind);
    if (payload.to !== this.address()) return drop("wrong recipient", sender, kind);
    let content: { text: string; sub: string };
    try {
      const raw = await openBox(payload.box, await this.identity(), aadFor(payload.id, kind, payload.from, payload.to));
      content = parseContent(kind, raw) as { text: string; sub: string };
    } catch (err) {
      if (err instanceof EnvelopeError) return drop(err.reason, sender, kind);
      throw err;
    }
    const name = content.sub;
    const sub = this.deps.publicSub(name);
    if (sub === null) return drop(`no public sub-tau /${name}`, sender, kind);
    if (!sub.web) return drop(`no web page for /${name}`, sender, kind);
    if (!this.autoReply()) return drop("auto_reply is off", sender, kind);
    if (payload.hops + 1 > MAX_HOPS) return drop("a reply would pass max_hops", sender, kind);
    if (!this.deps.takeVisit(name, sub.web_daily, nowSeconds())) {
      return drop(`/${name} is over web_daily (${sub.web_daily} visitor turns today)`, sender, kind);
    }
    const history = this.history(sender, payload.id, name, payload.thread);
    this.appendLog({
      ts: payload.ts,
      direction: "in",
      address: sender,
      kind,
      id: payload.id,
      thread: payload.thread,
      text: content.text,
      own_sub: name,
      peer_sub: null,
    });
    const system = systemPrompt(subPersona(sub), publicNoteSection(this.noteOf(sub)), {
      now: nowSeconds(),
      budget: "",
      withheld: NOT_SHARED_NET,
    });
    const prompt = buildVisitFrame({ sub: name, universe: sender, text: content.text, history });
    const reply = await this.deps.answer({ role: sub.role, system, prompt, kind: "net_visit", sub: name });
    let replied = false;
    if (reply) {
      try {
        await this.send(
          sender,
          boxKey,
          "message",
          { text: clip(reply, MAX_MESSAGE_CHARS), sub: name },
          {
            thread: payload.thread,
            replyTo: payload.id,
            hops: payload.hops + 1,
            id: await replyId(this.requireAddress(), sender, payload.id),
            count: false,
          },
        );
        replied = true;
      } catch (err) {
        if (!(err instanceof NetError) && !(err instanceof EnvelopeError)) throw err;
        log("net_visit_not_answered", { sub: name, error: err.message }, "warn");
      }
    }
    return { outcome: "handled", sender, kind, replied };
  }

  // -- sending -----------------------------------------------------------------------------

  /** Seals, signs and posts one envelope; logs it once it was delivered. */
  private async send(
    to: string,
    boxKey: string,
    kind: "contact_request" | "contact_accept" | "message",
    content: Record<string, unknown>,
    options: { thread?: string; replyTo?: string; hops?: number; id?: string; count?: boolean } = {},
  ): Promise<Delivery> {
    const from = this.requireAddress();
    const hops = options.hops ?? 0;
    const built = await buildEnvelope(await this.identity(), {
      from,
      to,
      recipientBoxKey: boxKey,
      kind,
      content,
      id: options.id,
      thread: options.thread,
      replyTo: options.replyTo ?? null,
      hops,
      ts: nowSeconds(),
    });
    const delivery = await this.post(to, built.envelope);
    const entry: Omit<LogEntry, "seq"> = {
      ts: built.payload.ts,
      direction: "out",
      address: to,
      kind,
      id: built.payload.id,
      thread: built.payload.thread,
      text: typeof content.text === "string" ? content.text : "",
      own_sub: null,
      peer_sub: null,
    };
    if (typeof content.sub === "string" && content.sub) {
      // An even hop goes to the other tau's sub-tau; an odd one is written by this tau's.
      if (subIsOurs(hops)) entry.peer_sub = content.sub;
      else entry.own_sub = content.sub;
    }
    if (this.appendLog(entry) && kind === "message" && (options.count ?? true)) this.count(to, "out");
    log("net_sent", { kind, to, status: delivery.status });
    return delivery;
  }

  /** `POST <scheme>://<to>/net/inbox`; a DeliveryError unless it was taken (202) or a duplicate. */
  private async post(to: string, envelope: WireEnvelope): Promise<Delivery> {
    let response: Response;
    try {
      response = await this.fetcher()(inboxUrl(to, insecurePeers(this.env)), {
        method: "POST",
        headers: { "content-type": "application/json", accept: "application/json", "user-agent": SOFTWARE },
        body: encodeEnvelope(envelope),
        redirect: "manual",
        signal: AbortSignal.timeout(SEND_TIMEOUT_MS),
      });
    } catch (err) {
      throw new DeliveryError(to, 0, "unreachable", err instanceof Error ? err.name : "");
    }
    let data: unknown = null;
    try {
      data = await response.json();
    } catch {
      data = null;
    }
    const body = isObject(data) ? data : {};
    const id = typeof body.id === "string" ? body.id : "";
    if (response.status === 202) return { address: to, id, status: typeof body.status === "string" ? body.status : "queued" };
    if (response.status === 200 && body.status === "duplicate") return { address: to, id, status: "duplicate" };
    const code = typeof body.error === "string" ? body.error : `http_${response.status}`;
    const detail = typeof body.detail === "string" ? body.detail.slice(0, 200) : "";
    throw new DeliveryError(to, response.status, code, detail);
  }

  // -- the owner's actions -----------------------------------------------------------------

  /** An address the owner typed, checked; ContactError otherwise. */
  checkAddress(text: unknown): string {
    const address = typeof text === "string" ? parseAddress(text) : null;
    if (address === null) throw new ContactError(`${JSON.stringify(text)} is not a tau address`);
    if (address === this.address()) throw new ContactError("that is this tau's own address");
    return address;
  }

  /** A message target the owner typed (`<address>` or `<address>/<name>`), checked. */
  checkTarget(text: unknown): { address: string; sub: string | null } {
    const target = typeof text === "string" ? parseTarget(text) : null;
    if (target === null) throw new ContactError(`${JSON.stringify(text)} is not a tau address or sub-tau target`);
    const contact = this.contact(target.address);
    if (contact === null || contact.state !== "accepted" || !contact.box_key) {
      throw new ContactError(`${target.address} is not an accepted contact (${contact?.state ?? "not a contact"})`);
    }
    return target;
  }

  /** Asks `address` to become a contact (tau-net's `add`). Runs after the owner approved it. */
  async add(text: unknown, note = ""): Promise<Contact> {
    const address = this.checkAddress(text);
    this.requireAddress();
    const card = await this.peerCard(address, true);
    if (card === null) throw new NetError(`the card of ${address} is unavailable`);
    const transition = this.requestOut(address, card, note);
    const contact = transition.contact as Contact;
    try {
      if (transition.action === "send_accept") {
        await this.send(address, card.box_key, "contact_accept", { name: this.name() });
      } else {
        await this.send(address, card.box_key, "contact_request", { name: this.name(), text: cleanNote(note) });
      }
    } catch (err) {
      if (err instanceof NetError || err instanceof EnvelopeError) {
        const what = transition.action === "send_accept" ? `${address} is a contact now` : `the request to ${address} was saved`;
        throw new NetError(`${what}, but ${err.message}`);
      }
      throw err;
    }
    return contact;
  }

  /** Accepts a pending request and tells the other tau (tau-net's `accept`). */
  async accept(text: unknown): Promise<Contact> {
    const address = this.checkAddress(text);
    this.requireAddress();
    const contact = this.contact(address);
    if (contact === null) throw new ContactError(`no contact request from ${address}`);
    if (contact.state === "accepted") throw new ContactError(`${address} is already a contact`);
    if (contact.state !== "pending_in") throw new ContactError(`${address} has not asked to be a contact (${contact.state})`);
    if (!contact.sign_key || !contact.box_key) throw new ContactError(`the request from ${address} carries no keys`);
    const now = nowSeconds();
    const accepted: Contact = { ...contact, state: "accepted", accepted_at: now, updated_at: now };
    this.writeContact(accepted);
    try {
      await this.send(address, contact.box_key, "contact_accept", { name: this.name() });
    } catch (err) {
      if (err instanceof NetError || err instanceof EnvelopeError) throw new NetError(`${address} is a contact now, but ${err.message}`);
      throw err;
    }
    return accepted;
  }

  /** Every state (or none) becomes `blocked`; nothing from it is read again. */
  block(text: unknown): Contact {
    const address = this.checkAddress(text);
    const now = nowSeconds();
    const current = this.contact(address);
    const contact: Contact = current
      ? { ...current, state: "blocked", updated_at: now }
      : { address, state: "blocked", name: "", sign_key: null, box_key: null, note: "", created_at: now, updated_at: now, accepted_at: null };
    this.writeContact(contact);
    return contact;
  }

  /** Forgets a contact or a request (its log stays); false when there was none. */
  remove(text: unknown): boolean {
    const address = this.checkAddress(text);
    const existed = this.contact(address) !== null;
    this.sql.exec("DELETE FROM net_contacts WHERE address = ?", address);
    return existed;
  }

  /** The owner's own message to an accepted contact or its public sub-tau: a new thread. */
  async sendMessage(targetText: unknown, textInput: unknown): Promise<Delivery & { sub: string | null }> {
    const target = this.checkTarget(targetText);
    const text = typeof textInput === "string" ? textInput.trim() : "";
    if (!text) throw new NetError("the message is empty");
    if (Array.from(text).length > MAX_MESSAGE_CHARS) throw new NetError(`the message is longer than ${MAX_MESSAGE_CHARS} characters`);
    const contact = this.contact(target.address) as Contact;
    const content: Record<string, unknown> = target.sub === null ? { text } : { text, sub: target.sub };
    try {
      const delivery = await this.send(target.address, contact.box_key ?? "", "message", content);
      return { ...delivery, sub: target.sub };
    } catch (err) {
      if (err instanceof EnvelopeError) throw new NetError(`the envelope could not be built: ${err.reason}`);
      throw err;
    }
  }

  // -- contacts ----------------------------------------------------------------------------

  contact(address: string): Contact | null {
    const row = this.sql.exec<ContactRow>("SELECT * FROM net_contacts WHERE address = ?", address).toArray()[0];
    return row === undefined ? null : toContact(row);
  }

  contacts(): Contact[] {
    const order = new Map(STATES.map((state, index) => [state, index]));
    return this.sql
      .exec<ContactRow>("SELECT * FROM net_contacts ORDER BY address")
      .toArray()
      .map(toContact)
      .filter((contact): contact is Contact => contact !== null)
      .sort((a, b) => (order.get(a.state) ?? 0) - (order.get(b.state) ?? 0));
  }

  private writeContact(contact: Contact): void {
    this.sql.exec(
      `INSERT INTO net_contacts (address, state, name, sign_key, box_key, note, created_at, updated_at, accepted_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
       ON CONFLICT (address) DO UPDATE SET state = excluded.state, name = excluded.name,
         sign_key = excluded.sign_key, box_key = excluded.box_key, note = excluded.note,
         updated_at = excluded.updated_at, accepted_at = excluded.accepted_at`,
      contact.address,
      contact.state,
      contact.name,
      contact.sign_key,
      contact.box_key,
      contact.note,
      contact.created_at,
      contact.updated_at,
      contact.accepted_at,
    );
  }

  private newContact(address: string, state: ContactState, fields: Partial<Contact>): Contact {
    const now = nowSeconds();
    return { address, state, name: "", sign_key: null, box_key: null, note: "", created_at: now, updated_at: now, accepted_at: null, ...fields };
  }

  private pin(contact: Contact, name: string, signKey: string, boxKey: string): Contact {
    const now = nowSeconds();
    return { ...contact, state: "accepted", name: cleanName(name) || contact.name, sign_key: signKey, box_key: boxKey, accepted_at: now, updated_at: now };
  }

  private onRequest(address: string, name: string, text: string, signKey: string, boxKey: string): Transition {
    const current = this.contact(address);
    if (current === null) {
      const contact = this.newContact(address, "pending_in", { name: cleanName(name), sign_key: signKey, box_key: boxKey, note: cleanNote(text) });
      this.writeContact(contact);
      return { action: "notify", contact };
    }
    if (current.state === "blocked") return { action: "drop", contact: current, reason: "blocked" };
    if (current.state === "pending_out") {
      const contact = this.pin(current, name, signKey, boxKey);
      this.writeContact(contact);
      return { action: "send_accept", contact };
    }
    if (current.state === "accepted") return { action: "send_accept", contact: current };
    // pending_in again: one request, with the latest note
    const contact = { ...current, name: cleanName(name) || current.name, note: cleanNote(text), updated_at: nowSeconds() };
    this.writeContact(contact);
    return { action: "none", contact, reason: "already pending" };
  }

  private onAccept(address: string, name: string, signKey: string, boxKey: string): Transition {
    const current = this.contact(address);
    if (current === null) return { action: "drop", contact: null, reason: "not a contact" };
    if (current.state === "pending_out") {
      const contact = this.pin(current, name, signKey, boxKey);
      this.writeContact(contact);
      return { action: "accepted", contact };
    }
    if (current.state === "accepted") return { action: "none", contact: current, reason: "already accepted" };
    return { action: "drop", contact: current, reason: current.state };
  }

  private onMessage(address: string): Transition {
    const contact = this.contact(address);
    if (contact === null) return { action: "drop", contact: null, reason: "not a contact" };
    if (contact.state !== "accepted") return { action: "drop", contact, reason: contact.state };
    return { action: "turn", contact };
  }

  /** The owner asks `address` (tau-net's `ContactBook.request`). */
  private requestOut(address: string, card: Card, note: string): Transition {
    const current = this.contact(address);
    if (current === null) {
      const contact = this.newContact(address, "pending_out", {
        name: cleanName(card.name),
        sign_key: card.sign_key,
        box_key: card.box_key,
        note: cleanNote(note),
      });
      this.writeContact(contact);
      return { action: "send_request", contact };
    }
    if (current.state === "accepted") throw new ContactError(`${address} is already a contact`);
    if (current.state === "blocked") throw new ContactError(`${address} is blocked; remove it first`);
    if (!keysMatch(current, card.sign_key, card.box_key)) {
      throw new ContactError(`the keys of ${address} changed since its request; remove it and add it again`);
    }
    if (current.state === "pending_in") {
      const contact = this.pin(current, card.name || current.name, card.sign_key, card.box_key);
      this.writeContact(contact);
      return { action: "send_accept", contact };
    }
    const contact: Contact = {
      ...current,
      name: cleanName(card.name) || current.name,
      sign_key: card.sign_key,
      box_key: card.box_key,
      note: note ? cleanNote(note) : current.note,
      updated_at: nowSeconds(),
    };
    this.writeContact(contact);
    return { action: "send_request", contact };
  }

  private autoRepliesLastHour(address: string): number {
    return (
      this.sql
        .exec<{ n: number }>("SELECT COUNT(*) AS n FROM net_replies WHERE address = ? AND at > ?", address, nowSeconds() - 3600)
        .toArray()[0]?.n ?? 0
    );
  }

  private recordAutoReply(address: string): void {
    const now = nowSeconds();
    this.sql.exec("DELETE FROM net_replies WHERE address = ? AND at <= ?", address, now - 3600);
    this.sql.exec("INSERT INTO net_replies (address, at) VALUES (?, ?)", address, now);
  }

  // -- the log and the counts --------------------------------------------------------------

  /** Appends an entry once (per direction, address and id); true when it is new. */
  private appendLog(entry: Omit<LogEntry, "seq">): boolean {
    const written = this.sql.exec(
      `INSERT OR IGNORE INTO net_log (ts, direction, address, kind, id, thread, text, own_sub, peer_sub)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`,
      entry.ts,
      entry.direction,
      entry.address,
      entry.kind,
      entry.id,
      entry.thread,
      entry.text,
      entry.own_sub,
      entry.peer_sub,
    ).rowsWritten;
    if (written > 0) {
      this.sql.exec("DELETE FROM net_log WHERE seq <= (SELECT MAX(seq) FROM net_log) - ?", LOG_LIMIT);
    }
    return written > 0;
  }

  private count(address: string, direction: "in" | "out"): void {
    const column = direction === "in" ? "n_in" : "n_out";
    this.sql.exec(
      `INSERT INTO net_counts (address, n_in, n_out) VALUES (?, ?, ?)
       ON CONFLICT (address) DO UPDATE SET ${column} = ${column} + 1`,
      address,
      direction === "in" ? 1 : 0,
      direction === "out" ? 1 : 0,
    );
  }

  counts(): Map<string, { in: number; out: number }> {
    const rows = this.sql.exec<{ address: string; n_in: number; n_out: number }>("SELECT * FROM net_counts").toArray();
    return new Map(rows.map((row) => [row.address, { in: row.n_in, out: row.n_out }]));
  }

  /** The log, oldest first: everything, or one address (and one of its conversations). */
  log(filter: { address?: string | null; limit?: number } = {}): LogEntry[] {
    const limit = Math.max(1, Math.min(filter.limit ?? LOG_LIMIT, LOG_LIMIT));
    const rows = filter.address
      ? this.sql.exec<LogRow>("SELECT * FROM (SELECT * FROM net_log WHERE address = ? ORDER BY seq DESC LIMIT ?) ORDER BY seq", filter.address, limit)
      : this.sql.exec<LogRow>("SELECT * FROM (SELECT * FROM net_log ORDER BY seq DESC LIMIT ?) ORDER BY seq", limit);
    return rows.toArray().map(toEntry);
  }

  // -- the universe ------------------------------------------------------------------------

  private universeClient(): UniverseClient | null {
    const host = this.universe();
    if (host === null) return null;
    return new UniverseClient({
      host,
      fetcher: this.fetcher(),
      allowInsecure: insecurePeers(this.env),
      now: nowSeconds,
      lastTs: () => this.deps.get<number>("universe_ts") ?? 0,
      saveTs: (ts) => this.deps.put("universe_ts", ts),
    });
  }

  /** The `subs` of a report: public sub-taus by name, at most 20 (tau-net's `universe_subs`). */
  reportedSubs(): ReportedSub[] {
    return this.deps
      .publicSubs()
      .filter((sub) => isSubName(sub.name))
      .sort((a, b) => (a.name < b.name ? -1 : 1))
      .slice(0, 20)
      .map((sub) => ({
        name: sub.name,
        about: clip(sub.about.split(/\s+/).filter(Boolean).join(" "), SUB_ABOUT_LIMIT).trimEnd(),
        web: sub.public && sub.web,
        starters: [...sub.starters],
      }));
  }

  private async joinWith(client: UniverseClient, identity: Identity, address: string): Promise<string | undefined> {
    const answer = await client.join(
      identity,
      address,
      clip(this.deps.get<string>("net_owner") ?? "", NET_OWNER_LIMIT),
      clip(this.deps.get<string>("net_about") ?? "", NET_ABOUT_LIMIT),
    );
    this.deps.put("universe_joined", true);
    return typeof answer.url === "string" ? answer.url : client.urlFor(address);
  }

  private async reportWith(client: UniverseClient, identity: Identity, address: string): Promise<number | undefined> {
    const listed = listedAddresses(await client.snapshot());
    const accepted = this.contacts()
      .filter((contact) => contact.state === "accepted")
      .map((contact) => contact.address);
    const links = selectLinks(accepted, this.counts(), listed, address);
    const answer = await client.report(identity, address, links, this.reportedSubs());
    return typeof answer.visible_links === "number" ? answer.visible_links : undefined;
  }

  /**
   * What the alarm does for the universe, and what the owner's toggle does at once: to be
   * listed, join when not joined yet and report (join again after `not_joined`, for example
   * after the universe's 30-day expiry); not to be listed, leave when still joined.
   */
  async syncUniverse(): Promise<UniverseView> {
    const client = this.universeClient();
    const address = this.address();
    const choice = this.deps.get<boolean>("universe");
    const now = nowSeconds();
    if (client === null || address === null) return this.universeView();
    // The next try, whatever happens now: a report every hour, a failed leave again later.
    this.deps.put("universe_next_at", now + REPORT_SECONDS);
    if (choice === true) {
      let action: UniverseStatus["action"] = "report";
      try {
        const identity = await this.identity();
        let url: string | undefined;
        if (this.deps.get<boolean>("universe_joined") !== true) {
          action = "join";
          url = await this.joinWith(client, identity, address);
        }
        let visible: number | undefined;
        try {
          action = "report";
          visible = await this.reportWith(client, identity, address);
        } catch (err) {
          if (!(err instanceof UniverseError) || err.code !== "not_joined") throw err;
          log("net_universe_rejoin", { universe: client.host });
          action = "join";
          url = await this.joinWith(client, identity, address);
          action = "report";
          visible = await this.reportWith(client, identity, address);
        }
        this.status({ at: now, ok: true, action, visible_links: visible, url: url ?? this.deps.get<UniverseStatus>("universe_status")?.url });
      } catch (err) {
        this.universeFailed(action, err);
      }
    } else if (this.deps.get<boolean>("universe_joined") === true) {
      await this.leaveUniverse();
    }
    await this.deps.scheduleAlarm();
    return this.universeView();
  }

  /** Leaves the universe and forgets its pinned keys (a tau that left takes no visits). */
  async leaveUniverse(): Promise<void> {
    const client = this.universeClient();
    const address = this.address();
    if (client === null || address === null) return;
    const pins = { ...(this.deps.get<Record<string, unknown>>("universe_pins") ?? {}) };
    delete pins[client.host];
    this.deps.put("universe_pins", pins);
    try {
      await client.leave(await this.identity(), address);
      this.deps.put("universe_joined", false);
      this.status({ at: nowSeconds(), ok: true, action: "leave" });
    } catch (err) {
      if (err instanceof UniverseError && err.code === "not_joined") {
        this.deps.put("universe_joined", false);
        this.status({ at: nowSeconds(), ok: true, action: "leave" });
        return;
      }
      this.universeFailed("leave", err);
    }
  }

  private status(status: UniverseStatus): void {
    this.deps.put("universe_status", status);
  }

  private universeFailed(action: UniverseStatus["action"], err: unknown): void {
    const error = err instanceof UniverseError ? err.message : err instanceof Error ? `${err.name}: ${err.message}` : "error";
    log("net_universe_failed", { action, error }, "warn");
    this.status({ at: nowSeconds(), ok: false, action, error, url: this.deps.get<UniverseStatus>("universe_status")?.url });
  }

  universeView(): UniverseView {
    return {
      host: this.universe(),
      choice: this.deps.get<boolean>("universe"),
      joined: this.deps.get<boolean>("universe_joined") === true,
      last: this.deps.get<UniverseStatus>("universe_status"),
      next_at: this.deps.get<boolean>("universe") === true ? this.deps.get<number>("universe_next_at") : null,
    };
  }

  // -- summary, alarm, export --------------------------------------------------------------

  summary(): NetSummary {
    const counts = this.counts();
    const contacts = this.contacts().map(({ sign_key: _s, box_key: _b, ...rest }) => ({
      ...rest,
      messages: (counts.get(rest.address)?.in ?? 0) + (counts.get(rest.address)?.out ?? 0),
    }));
    return {
      address: this.address(),
      name: this.name(),
      universe: this.universeView(),
      contacts,
      pending: contacts.filter((contact) => contact.state === "pending_in").length,
    };
  }

  /** When the alarm has network work: a stuck envelope, a report, a leave, old rows. */
  nextAlarm(): number | null {
    const times: number[] = [];
    const oldest = this.sql.exec<{ at: number | null }>("SELECT MIN(received_at) AS at FROM net_queue").toArray()[0]?.at;
    if (typeof oldest === "number") times.push(oldest + QUEUE_RETRY_SECONDS);
    const seen = this.sql.exec<{ at: number | null }>("SELECT MIN(at) AS at FROM net_seen").toArray()[0]?.at;
    if (typeof seen === "number") times.push(seen + SEEN_SECONDS);
    if (this.universe() !== null && this.universeDue() !== null) times.push(this.universeDue() as number);
    return times.length > 0 ? Math.min(...times) : null;
  }

  /** The alarm's network work. */
  async alarm(now: number): Promise<void> {
    this.sql.exec("DELETE FROM net_seen WHERE at <= ?", now - SEEN_SECONDS);
    this.sql.exec("DELETE FROM net_replies WHERE at <= ?", now - 3600);
    this.sql.exec("DELETE FROM net_cards WHERE fetched_at <= ?", now - CARD_CACHE_SECONDS);
    const stuck = this.sql.exec("SELECT 1 FROM net_queue WHERE received_at <= ? LIMIT 1", now - QUEUE_RETRY_SECONDS).toArray();
    if (stuck.length > 0) await this.drain();
    if (this.universe() === null) return;
    const due = this.universeDue();
    if (due !== null && due <= now) await this.syncUniverse();
  }

  /**
   * When the universe needs this tau next: while the owner wants it listed (a report), or
   * while it is still joined although the owner does not (a leave); null otherwise.
   */
  private universeDue(): number | null {
    const wanted = this.deps.get<boolean>("universe") === true;
    const joined = this.deps.get<boolean>("universe_joined") === true;
    if (!wanted && !joined) return null;
    return this.deps.get<number>("universe_next_at") ?? nowSeconds();
  }

  /** The network part of the owner's export: never the identity. */
  exportData(): Record<string, unknown> {
    return {
      address: this.address(),
      name: this.name(),
      contacts: this.contacts(),
      counts: Object.fromEntries(this.counts()),
      log: this.log(),
      universe: this.universeView(),
    };
  }
}
