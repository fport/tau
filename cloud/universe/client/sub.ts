/**
 * The sub-tau page, `/<slug>` and `/@<handle>/<name>` (ADR 0013 §5–§6): reads
 * `GET /api/subs/<target>`, shows the sub-tau's character, name, about line and owner, and,
 * when it takes visitors (`web`), its starter chips and a chat box.
 *
 * The chat speaks the universe's visitor API: `POST /api/chat/<target>` with
 * `{text, thread?}` answers `{thread, id}`, and `GET /api/chat/<target>/<thread>?after=<n>`
 * long-polls for `{messages, done?}`. `<target>` is the slug or `@<handle>/<name>`. The
 * thread is kept in sessionStorage so a reload continues it (the universe keeps threads for
 * 24 hours). Replies are set as text, never parsed.
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
/** How long the page keeps waiting for an answer before it says so, in milliseconds. */
const PATIENCE = 10 * 60 * 1000;

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
    status.append(html("span", "pip"), t.online.toLowerCase());
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
  name: string;
  /** A hub-run sub-tau whose hub is offline: messages wait. */
  offline: boolean;
  thread: string | null;
  last: number;
  /** The number of the newest visitor message still without an answer after it. */
  waitingFor: number | null;
  waitingSince: number;
  polling: boolean;
  sending: boolean;
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
  const list = log();
  const last = list.lastElementChild;
  if (last instanceof HTMLElement) {
    last.scrollIntoView({ block: "nearest", behavior: reducedMotion.matches ? "auto" : "smooth" });
  }
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
  const from = message.from === "sub" ? "sub" : "visitor";
  const list = log();
  if (list.querySelector(`[data-n="${message.n}"]`) === null) {
    const next = [...list.querySelectorAll<HTMLElement>("[data-n]")].find(
      (item) => Number(item.dataset.n) > message.n,
    );
    list.insertBefore(bubble(from, text(message.text), message.n), next ?? null);
  }
  if (from === "visitor") {
    if (chat.waitingFor === null) chat.waitingSince = Date.now();
    chat.waitingFor = message.n;
  } else if (chat.waitingFor !== null && message.n > chat.waitingFor) {
    chat.waitingFor = null;
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

/** Long-polls the thread until the newest visitor message has an answer (or patience ends). */
async function poll(chat: Chat): Promise<void> {
  if (chat.polling || chat.thread === null) return;
  chat.polling = true;
  let backoff = 1000;
  try {
    while (chat.thread !== null) {
      const thread: string = chat.thread;
      const result = await getJson<ChatPoll>(
        `/api/chat/${chat.key}/${encodeURIComponent(thread)}?after=${chat.last}`,
      );
      if (chat.thread !== thread) continue;
      if (result.status === 404) {
        // The thread is gone (older than a day): start over.
        chat.thread = null;
        chat.waitingFor = null;
        saveThread(chat.key, null);
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
      byId<HTMLElement>("chat-typing").hidden = chat.waitingFor === null || chat.offline;
      if (chat.waitingFor === null && result.data.done !== false) break;
      if (chat.offline) setNotice(t.waitingOffline);
      if (Date.now() - chat.waitingSince > PATIENCE) {
        setNotice(t.stillWaiting);
        break;
      }
      if (messages.length === 0 && chat.offline) await sleep(4000);
    }
  } finally {
    chat.polling = false;
    if (chat.waitingFor === null) setNotice(null);
    byId<HTMLElement>("chat-typing").hidden = true;
  }
}

function sendError(status: number, error: string | null): string {
  const code = error ?? "";
  if (code.includes("cap") || code === "daily_limit") return t.dailyCap;
  if (code.includes("budget")) return t.overBudget;
  if (status === 413 || code.includes("too_long") || code.includes("too_large")) {
    return t.tooLong(formatNumber(MAX_TEXT));
  }
  if (status === 429) return t.rateLimited;
  if (code === "not_web" || code === "closed" || code === "not_public") return t.chatClosed;
  return t.chatFailed;
}

async function send(chat: Chat, body: string): Promise<void> {
  const message = body.trim();
  if (message === "" || chat.sending) return;
  if (message.length > MAX_TEXT) {
    setNotice(t.tooLong(formatNumber(MAX_TEXT)), "error");
    return;
  }
  chat.sending = true;
  const button = byId<HTMLButtonElement>("chat-send");
  button.disabled = true;
  byId<HTMLElement>("starters").hidden = true;
  const pending = bubble("visitor", message, null);
  pending.classList.add("msg-pending");
  log().append(pending);
  scrollToEnd();
  input().value = "";
  updateCount();
  setNotice(null);

  const result = await postJson<ChatSent>(`/api/chat/${chat.key}`, {
    text: message,
    ...(chat.thread !== null ? { thread: chat.thread } : {}),
  });
  chat.sending = false;
  button.disabled = false;
  if (result.status !== 200 || result.data === null || typeof result.data.thread !== "string") {
    pending.remove();
    input().value = message;
    updateCount();
    setNotice(sendError(result.status, result.error), "error");
    byId<HTMLElement>("starters").hidden = log().childElementCount > 0;
    return;
  }
  const id = typeof result.data.id === "number" ? result.data.id : chat.last + 1;
  pending.classList.remove("msg-pending");
  pending.dataset.n = String(id);
  if (chat.thread !== result.data.thread) {
    chat.thread = result.data.thread;
    saveThread(chat.key, chat.thread);
  }
  chat.waitingFor = id;
  chat.waitingSince = Date.now();
  byId<HTMLElement>("chat-new").hidden = false;
  byId<HTMLElement>("chat-typing").hidden = chat.offline;
  if (chat.offline) setNotice(t.waitingOffline);
  void poll(chat);
}

function updateCount(): void {
  const used = input().value.length;
  const counter = byId<HTMLElement>("chat-count");
  counter.textContent = `${formatNumber(used)} / ${formatNumber(MAX_TEXT)}`;
  counter.classList.toggle("is-over", used > MAX_TEXT);
}

function startChat(view: SubView, where: SubTarget): void {
  const chat: Chat = {
    key: targetKey(where),
    name: view.name,
    offline: view.hosted !== true && view.online !== true,
    thread: null,
    last: 0,
    waitingFor: null,
    waitingSince: 0,
    polling: false,
    sending: false,
  };
  byId<HTMLElement>("chat").hidden = false;
  const field = input();
  field.placeholder = t.messagePlaceholder(view.name);
  field.maxLength = MAX_TEXT;
  byId<HTMLElement>("chat-typing-name").textContent = view.name;
  byId<HTMLElement>("chat-typing-text").textContent = t.waiting;

  const starters = byId<HTMLUListElement>("starters");
  starters.replaceChildren();
  const list = Array.isArray(view.starters) ? view.starters.filter((s) => typeof s === "string") : [];
  for (const starter of list.slice(0, 4)) {
    const chip = html("button", "chip", starter);
    chip.type = "button";
    chip.addEventListener("click", () => void send(chat, starter));
    const item = html("li");
    item.append(chip);
    starters.append(item);
  }
  starters.hidden = list.length === 0;

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
    chat.thread = null;
    chat.last = 0;
    chat.waitingFor = null;
    saveThread(chat.key, null);
    log().replaceChildren();
    setNotice(null);
    byId<HTMLElement>("chat-typing").hidden = true;
    byId<HTMLElement>("chat-new").hidden = true;
    starters.hidden = list.length === 0;
    field.focus();
  });

  // Continue the thread of this tab, when there is one.
  const thread = savedThread(chat.key);
  if (thread !== null) {
    chat.thread = thread;
    starters.hidden = true;
    byId<HTMLElement>("chat-new").hidden = false;
    void poll(chat);
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
