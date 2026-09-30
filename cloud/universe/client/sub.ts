/**
 * The sub-tau page, `/<slug>` and `/@<handle>/<name>` (ADR 0013 §5–§6): reads
 * `GET /api/subs/<target>`, shows the sub-tau's character, name, about line and owner, and,
 * when it takes visitors (`web`), its starter chips and a chat box.
 *
 * The chat speaks the universe's visitor API (docs/reference/tau-universe.md §5), where
 * `<target>` is the slug or `@<handle>/<name>`:
 *
 * - `POST /api/chat/<target>` with `{text, thread?}` answers `{thread, id, n}`; the first
 *   one sets the visitor cookie.
 * - `GET /api/chat/<target>/<thread>?after=<n>&wait=25` waits for the answer and returns
 *   `{messages, pending, state}`. The page polls until `pending` is false. `state` says
 *   whether the sub-tau is `resting` (daily cap or budget), the thread `full`, or the last
 *   message `unavailable`.
 * - While a message is pending the send button stays off (the universe would answer `busy`).
 *   A hub whose owner is offline may answer after `pending` went false, so a page left open
 *   looks for late answers every 30 seconds.
 *
 * The thread is kept in sessionStorage per target, so a reload continues it (the universe
 * keeps threads for 24 hours). Replies are set as text, never parsed.
 */

import { getJson, postJson } from "./api";
import { byId, characterElement, html, link } from "./dom";
import {
  HANDLE,
  personPath,
  type SubTarget,
  splitLanguage,
  subFromPath,
  targetKey,
  universePath,
} from "./paths";
import {
  formatNumber,
  hideState,
  language,
  linkLanguageTwin,
  month,
  reducedMotion,
  setCrumbs,
  showState,
  t,
} from "./site";
import type { ChatMessage, ChatPoll, ChatSent, SubView } from "./types";

/** The longest visitor message the universe takes (ADR 0013 §5). */
const MAX_TEXT = 2000;
/** How long one poll may wait for the answer, in seconds (the universe's maximum). */
const WAIT = 25;
/** How often a page left open looks for a late answer, and for how long, in milliseconds. */
const LATE_EVERY = 30_000;
const LATE_FOR = 30 * 60_000;

const target = subFromPath(window.location.pathname);

function text(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function crumbsFor(where: SubTarget | null, view: SubView | null): void {
  if (where === null) {
    setCrumbs([{ text: splitLanguage(window.location.pathname).rest.slice(1) || "?" }]);
    return;
  }
  const owner = view?.owner?.handle ?? (where.kind === "handle" ? where.handle : null);
  const name = view?.name ?? (where.kind === "slug" ? where.slug : where.name);
  if (where.kind === "handle" && owner !== null && HANDLE.test(owner)) {
    setCrumbs([{ text: `@${owner}`, href: personPath(owner, language) }, { text: name }]);
  } else {
    setCrumbs([{ text: name }]);
  }
}

// ---------------------------------------------------------------------------------------
// The page

function renderHead(view: SubView): void {
  const address = text(view.owner?.address);
  const stage = byId<HTMLElement>("sub-stage");
  stage.querySelector(".ch")?.remove();
  stage.append(
    characterElement(`${address}/${view.name}`, { size: 176, animated: !reducedMotion.matches }),
  );
  byId<HTMLElement>("sub-name").textContent = view.name;
  const about = byId<HTMLElement>("sub-about");
  about.textContent = text(view.about);
  about.hidden = text(view.about) === "";

  const by = byId<HTMLElement>("sub-by");
  by.replaceChildren();
  const ownerHandle =
    typeof view.owner?.handle === "string" && HANDLE.test(view.owner.handle)
      ? view.owner.handle
      : null;
  const ownerName = ownerHandle !== null ? `@${ownerHandle}` : text(view.owner?.name) || address;
  const ownerLink = link(
    ownerHandle !== null ? personPath(ownerHandle, language) : universePath(address, language),
    "",
    "sub-owner",
  );
  ownerLink.append(characterElement(address, { size: 28, animated: false }), ownerName);
  // "by @alice" in English, "@alice tarafından" in Turkish: the message places the name.
  const [before = "", after = ""] = t.by("\u0000").split("\u0000");
  if (before !== "") by.append(before);
  by.append(ownerLink);
  if (after !== "") by.append(after);

  const status = byId<HTMLElement>("sub-status");
  status.replaceChildren();
  if (view.hosted === true || view.online === true) {
    status.append(html("span", "pip"), t.online);
  } else {
    status.append(html("span", "pip pip-off"), t.offlineWaits);
  }

  byId<HTMLElement>("sub-details-title").textContent = t.aboutSub(view.name);
  const facts = byId<HTMLElement>("sub-facts");
  facts.replaceChildren();
  const fact = (term: string, value: string | Node) => {
    const row = html("div");
    const dd = html("dd");
    dd.append(value);
    row.append(html("dt", undefined, term), dd);
    facts.append(row);
  };
  const code = html("code", undefined, `${address}/${view.name}`);
  fact(t.factAddress, code);
  fact(t.owner, ownerName);
  const seen = month(view.first_seen);
  if (seen !== "") fact(t.factFirstSeen, seen);
  fact(t.factRunsOn, view.hosted === true ? t.runsHosted : t.runsHub);
}

// ---------------------------------------------------------------------------------------
// The chat

interface Chat {
  key: string;
  /** A hub-run sub-tau whose hub is offline: messages wait. */
  offline: boolean;
  thread: string | null;
  /** The number of the newest message the page shows. */
  last: number;
  /** Whether the universe says the last message still awaits its answer. */
  pending: boolean;
  sending: boolean;
  polling: boolean;
  /** Until when the page looks for a late answer (0: it does not). */
  lateUntil: number;
  lateTimer: number;
  starters: string[];
}

const log = () => byId<HTMLOListElement>("chat-log");
const input = () => byId<HTMLTextAreaElement>("chat-input");

function storageKey(key: string): string {
  return `tau.chat.${key}`;
}

function savedThread(key: string): string | null {
  try {
    return window.sessionStorage.getItem(storageKey(key));
  } catch {
    return null;
  }
}

function saveThread(key: string, thread: string | null): void {
  try {
    if (thread === null) window.sessionStorage.removeItem(storageKey(key));
    else window.sessionStorage.setItem(storageKey(key), thread);
  } catch {
    // A private window without storage: the thread lasts as long as the page.
  }
}

function bubble(from: "visitor" | "sub", body: string, n: number | null): HTMLLIElement {
  const item = html("li", `msg msg-${from}`);
  if (n !== null) item.dataset.n = String(n);
  item.append(
    html("span", "msg-who", from === "visitor" ? t.you : ""),
    html("p", "msg-text", body),
  );
  return item;
}

function setNotice(message: string | null, kind: "wait" | "error" = "wait"): void {
  const notice = byId<HTMLElement>("chat-notice");
  notice.textContent = message ?? "";
  notice.className = `talk-notice talk-notice-${kind}`;
  notice.hidden = message === null;
}

function scrollToEnd(): void {
  const last = log().lastElementChild;
  if (last instanceof HTMLElement) {
    last.scrollIntoView({ block: "nearest", behavior: reducedMotion.matches ? "auto" : "smooth" });
  }
}

/** Whether the newest message on the page is the visitor's, still without an answer. */
function unanswered(): boolean {
  const items = log().querySelectorAll<HTMLElement>("[data-n]");
  const newest = items[items.length - 1];
  return newest !== undefined && newest.classList.contains("msg-visitor");
}

/** The send button and the starters are off while a message is on its way or pending. */
function setBusy(chat: Chat): void {
  const busy = chat.sending || chat.pending;
  byId<HTMLButtonElement>("chat-send").disabled = busy;
  for (const chip of byId<HTMLElement>("starters").querySelectorAll("button")) {
    chip.disabled = busy;
  }
  byId<HTMLElement>("chat-typing").hidden = !chat.pending;
}

/**
 * Adds a message of the thread in its place (by number), unless the page already shows it:
 * the visitor's own messages are shown as soon as they are sent.
 */
function append(chat: Chat, message: ChatMessage): void {
  if (typeof message?.n !== "number" || !Number.isInteger(message.n) || message.n <= chat.last) {
    return;
  }
  chat.last = message.n;
  const list = log();
  if (list.querySelector(`[data-n="${message.n}"]`) !== null) return;
  const from = message.from === "sub" ? "sub" : "visitor";
  const next = [...list.querySelectorAll<HTMLElement>("[data-n]")].find(
    (item) => Number(item.dataset.n) > message.n,
  );
  list.insertBefore(bubble(from, text(message.text), message.n), next ?? null);
}

/** What the thread's state means for the visitor, after the last exchange. */
function explainState(chat: Chat, state: string | undefined): void {
  switch (state) {
    case "resting":
      setNotice(t.resting);
      break;
    case "full":
      setNotice(t.threadFull);
      byId<HTMLElement>("chat-new").hidden = false;
      break;
    case "unavailable":
      setNotice(t.unavailableNow, "error");
      break;
    default:
      setNotice(unanswered() && chat.offline ? t.waitingOffline : null);
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

/** Reads the thread (waiting up to `wait` seconds for an answer) until nothing is pending. */
async function poll(chat: Chat, wait: number): Promise<void> {
  if (chat.polling || chat.thread === null) return;
  chat.polling = true;
  let backoff = 1000;
  try {
    for (;;) {
      const thread: string | null = chat.thread;
      if (thread === null) break;
      const result = await getJson<ChatPoll>(
        `/api/chat/${chat.key}/${encodeURIComponent(thread)}?after=${chat.last}&wait=${wait}`,
      );
      if (chat.thread !== thread) continue;
      if (result.status === 404) {
        // The thread is gone (older than a day, or another browser's): start over.
        forget(chat);
        break;
      }
      if (result.status !== 200 || result.data === null) {
        await sleep(backoff);
        backoff = Math.min(30_000, backoff * 2);
        continue;
      }
      backoff = 1000;
      const messages = Array.isArray(result.data.messages) ? result.data.messages : [];
      for (const message of messages) append(chat, message);
      if (messages.length > 0) scrollToEnd();
      chat.pending = result.data.pending === true;
      setBusy(chat);
      if (!chat.pending) {
        explainState(chat, result.data.state);
        break;
      }
      wait = WAIT;
      if (chat.offline) setNotice(t.waitingOffline);
    }
  } finally {
    chat.polling = false;
    setBusy(chat);
    lookLater(chat);
  }
}

/** A hub whose owner is offline answers when it is back: look again now and then. */
function lookLater(chat: Chat): void {
  window.clearTimeout(chat.lateTimer);
  if (chat.thread === null || chat.pending || !unanswered()) return;
  if (chat.lateUntil === 0) chat.lateUntil = Date.now() + LATE_FOR;
  if (Date.now() > chat.lateUntil) return;
  chat.lateTimer = window.setTimeout(() => {
    if (document.visibilityState === "visible") void poll(chat, 0);
    else lookLater(chat);
  }, LATE_EVERY);
}

function forget(chat: Chat): void {
  chat.thread = null;
  chat.last = 0;
  chat.pending = false;
  chat.lateUntil = 0;
  window.clearTimeout(chat.lateTimer);
  saveThread(chat.key, null);
}

function sendError(status: number, error: string | null): string {
  switch (error) {
    case "rate_limited":
      return t.rateLimited;
    case "too_large":
      return t.tooLong(formatNumber(MAX_TEXT));
    case "not_web":
      return t.chatClosed;
    case "unavailable":
      return t.unavailableNow;
    case "thread_full":
      return t.threadFull;
    case "busy":
      return t.busy;
  }
  if (status === 429) return t.rateLimited;
  if (status === 413) return t.tooLong(formatNumber(MAX_TEXT));
  return t.chatFailed;
}

async function send(chat: Chat, body: string): Promise<void> {
  const message = body.trim();
  if (message === "" || chat.sending || chat.pending) return;
  if (message.length > MAX_TEXT) {
    setNotice(t.tooLong(formatNumber(MAX_TEXT)), "error");
    return;
  }
  chat.sending = true;
  setBusy(chat);
  byId<HTMLElement>("starters").hidden = true;
  const shown = bubble("visitor", message, null);
  shown.classList.add("msg-pending");
  log().append(shown);
  scrollToEnd();
  input().value = "";
  updateCount();
  setNotice(null);
  window.clearTimeout(chat.lateTimer);

  const post = (thread: string | null) =>
    postJson<ChatSent>(
      `/api/chat/${chat.key}`,
      thread === null ? { text: message } : { text: message, thread },
    );
  let result = await post(chat.thread);
  if (result.status === 404 && result.error === "not_found" && chat.thread !== null) {
    // The thread expired: the message starts a new one.
    forget(chat);
    log().replaceChildren(shown);
    result = await post(null);
  }
  chat.sending = false;
  const sent = result.data;
  if (result.status !== 200 || sent === null || typeof sent.thread !== "string") {
    shown.remove();
    input().value = message;
    updateCount();
    setBusy(chat);
    setNotice(sendError(result.status, result.error), "error");
    if (result.error === "thread_full") byId<HTMLElement>("chat-new").hidden = false;
    byId<HTMLElement>("starters").hidden =
      log().childElementCount > 0 || chat.starters.length === 0;
    return;
  }
  shown.classList.remove("msg-pending");
  if (typeof sent.n === "number") shown.dataset.n = String(sent.n);
  if (chat.thread !== sent.thread) {
    chat.thread = sent.thread;
    saveThread(chat.key, chat.thread);
  }
  chat.pending = true;
  chat.lateUntil = 0;
  byId<HTMLElement>("chat-new").hidden = false;
  setBusy(chat);
  if (chat.offline) setNotice(t.waitingOffline);
  void poll(chat, WAIT);
}

function updateCount(): void {
  const used = input().value.length;
  const counter = byId<HTMLElement>("chat-count");
  counter.textContent = `${formatNumber(used)} / ${formatNumber(MAX_TEXT)}`;
  counter.classList.toggle("is-over", used > MAX_TEXT);
}

function startChat(view: SubView, where: SubTarget): void {
  const starters = Array.isArray(view.starters)
    ? view.starters.filter((s) => typeof s === "string" && s.trim() !== "").slice(0, 4)
    : [];
  const chat: Chat = {
    key: targetKey(where),
    offline: view.hosted !== true && view.online !== true,
    thread: null,
    last: 0,
    pending: false,
    sending: false,
    polling: false,
    lateUntil: 0,
    lateTimer: 0,
    starters,
  };
  byId<HTMLElement>("chat").hidden = false;
  const field = input();
  field.placeholder = t.messagePlaceholder(view.name);
  field.maxLength = MAX_TEXT;
  byId<HTMLElement>("chat-typing-name").textContent = view.name;
  byId<HTMLElement>("chat-typing-text").textContent = t.waiting;

  const list = byId<HTMLUListElement>("starters");
  list.replaceChildren();
  for (const starter of starters) {
    const chip = html("button", "chip", starter);
    chip.type = "button";
    chip.addEventListener("click", () => void send(chat, starter));
    const item = html("li");
    item.append(chip);
    list.append(item);
  }
  list.hidden = starters.length === 0;

  byId<HTMLFormElement>("chat-form").addEventListener("submit", (event) => {
    event.preventDefault();
    void send(chat, field.value);
  });
  field.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      void send(chat, field.value);
    }
  });
  field.addEventListener("input", updateCount);
  updateCount();

  byId<HTMLButtonElement>("chat-new").addEventListener("click", () => {
    forget(chat);
    log().replaceChildren();
    setNotice(null);
    setBusy(chat);
    byId<HTMLElement>("chat-new").hidden = true;
    list.hidden = starters.length === 0;
    field.focus();
  });

  // Continue this tab's thread with this sub-tau, when there is one.
  const thread = savedThread(chat.key);
  if (thread !== null) {
    chat.thread = thread;
    list.hidden = true;
    byId<HTMLElement>("chat-new").hidden = false;
    void poll(chat, 0);
  }
}

// ---------------------------------------------------------------------------------------

async function load(): Promise<void> {
  linkLanguageTwin();
  crumbsFor(target, null);
  if (target === null) {
    showState(t.subMissing, null);
    return;
  }
  const key = targetKey(target);
  showState(t.loading, null);
  const result = await getJson<SubView>(`/api/subs/${key}`);
  if (result.status === 404) {
    showState(t.subMissing, t.subMissingHint(`/${key}`));
    return;
  }
  if (result.status !== 200 || result.data === null || typeof result.data.name !== "string") {
    showState(t.pageFailed, null, () => void load());
    return;
  }
  const view = result.data;
  document.title = t.subTitle(view.name);
  crumbsFor(target, view);
  renderHead(view);
  hideState();
  byId<HTMLElement>("sub-view").hidden = false;
  if (view.web === true) {
    startChat(view, target);
  } else {
    const none = byId<HTMLElement>("no-chat");
    none.textContent = t.noChat(view.name);
    none.hidden = false;
  }
}

void load();
