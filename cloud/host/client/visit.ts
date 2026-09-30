/**
 * The chat page of a public web sub-tau at /@<handle>/<name>: the character, the starters
 * and a small chat against POST /api/visit/<handle>/<name>.
 *
 * The visitor is an anonymous random id kept in this browser (localStorage, when it is
 * allowed); the thread id lives for the tab (sessionStorage). Nothing else is stored.
 */

import { character } from "tau-character";
import { clear, h, pageData, svg } from "./dom";
import { MESSAGES, type UiLanguage } from "./messages";

interface Data {
  handle: string;
  name: string;
  about: string;
  starters: string[];
  lang: UiLanguage;
}

interface Reply {
  thread: string;
  reply: { id: string; text: string; ts: number };
}

const data = pageData<Data>();
const m = MESSAGES[data.lang === "tr" ? "tr" : "en"];
const threadKey = `tau-visit-thread:${data.handle}/${data.name}`;

function randomId(): string {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return btoa(String.fromCharCode(...bytes)).replaceAll("+", "-").replaceAll("/", "_").replace(/=+$/, "");
}

function stored(storage: () => Storage, key: string, make?: () => string): string | null {
  try {
    const value = storage().getItem(key);
    if (value) return value;
    if (!make) return null;
    const fresh = make();
    storage().setItem(key, fresh);
    return fresh;
  } catch {
    return make ? make() : null;
  }
}

function store(storage: () => Storage, key: string, value: string | null): void {
  try {
    if (value === null) storage().removeItem(key);
    else storage().setItem(key, value);
  } catch {
    // Private windows and blocked storage: the thread lives for this page only.
  }
}

const visitor = stored(() => localStorage, "tau-visitor", randomId) ?? randomId();
let thread = stored(() => sessionStorage, threadKey);

const slot = document.querySelector(".char-slot");
if (slot) {
  slot.append(
    h("span", { class: "ring" }, svg(character(`${data.handle}/${data.name}`, { size: 96, animated: true, label: `/${data.name}` }))),
  );
}

const log = document.getElementById("log") as HTMLElement;
const form = document.getElementById("composer") as HTMLFormElement;
const text = document.getElementById("text") as HTMLTextAreaElement;
const starters = document.getElementById("starters") as HTMLElement;
const button = form.querySelector("button") as HTMLButtonElement;
text.placeholder = m.visitorPlaceholder;

function line(from: string, value: string, mine: boolean): HTMLElement {
  const element = h("div", { class: `msg ${mine ? "user" : "assistant"}` }, h("span", { class: "from" }, from), h("div", { class: "text" }, value));
  log.append(element);
  element.scrollIntoView({ block: "end" });
  return element;
}

function errorFor(code: string): string {
  if (code === "daily_cap") return m.visitorCap;
  if (code === "rate_limited") return m.visitorBusy;
  return m.visitorError(code);
}

async function send(value: string): Promise<void> {
  const message = value.trim();
  if (!message) return;
  button.disabled = true;
  starters.hidden = true;
  line(m.you, message, true);
  const waiting = line(`/${data.name}`, "…", false);
  waiting.classList.add("streaming");
  try {
    let response = await post(message);
    if (response.status === 404 && thread) {
      // The thread expired (24 hours): start a new one.
      thread = null;
      store(() => sessionStorage, threadKey, null);
      log.append(h("p", { class: "muted small" }, m.visitorThreadGone));
      response = await post(message);
    }
    const body = (await response.json()) as Reply & { error?: string };
    waiting.remove();
    if (!response.ok) {
      line(`/${data.name}`, errorFor(body.error ?? String(response.status)), false).classList.add("alert");
    } else {
      thread = body.thread;
      store(() => sessionStorage, threadKey, thread);
      line(`/${data.name}`, body.reply.text, false);
    }
  } catch {
    waiting.remove();
    line(`/${data.name}`, m.err_network, false).classList.add("alert");
  }
  button.disabled = false;
  text.focus();
}

function post(message: string): Promise<Response> {
  return fetch(`/api/visit/${encodeURIComponent(data.handle)}/${encodeURIComponent(data.name)}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ visitor, text: message, ...(thread ? { thread } : {}) }),
  });
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  const value = text.value;
  text.value = "";
  void send(value);
});
text.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    form.requestSubmit();
  }
});
for (const chip of starters.querySelectorAll<HTMLButtonElement>("[data-starter]")) {
  chip.addEventListener("click", () => void send(chip.dataset.starter ?? ""));
}
if (thread) clear(log);
