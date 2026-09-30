/**
 * The owner's app at /app: onboarding, chat with streaming, sessions, sub-taus, approvals
 * and settings. Plain TypeScript and the DOM, bundled by scripts/build.mjs; no framework.
 *
 * Views are paths under /app (history API): /app (chat), /app/chat/<session>,
 * /app/subs, /app/subs/<name>, /app/subs/new, /app/approvals, /app/settings. The Worker
 * serves the same shell for all of them.
 *
 * Everything the owner, a model or a visitor wrote is set as text, never as HTML.
 */

import { character } from "tau-character";
import { ApiError, call, type StreamEvent, stream } from "./api";
import { clear, date, h, pageData, svg, time, usd } from "./dom";
import { MESSAGES, type Messages, type UiLanguage } from "./messages";

// -- the API's shapes --------------------------------------------------------------------

type Role = "brain" | "fast";

interface Settings {
  provider: string | null;
  key_last4: string;
  has_key: boolean;
  models: Record<Role, string>;
  budget_usd: number;
  language: UiLanguage | null;
  persona: string | null;
  profile: string;
  universe: boolean | null;
  onboarded: boolean;
}

interface Budget {
  month: string;
  spent_usd: number;
  budget_usd: number;
  resets_at: number;
  exhausted: boolean;
}

interface Sub {
  name: string;
  about: string;
  persona: string;
  role: Role;
  public: boolean;
  public_note: string;
  web: boolean;
  web_daily: number;
  starters: string[];
  created_at: number;
  updated_at: number;
  visits_today: number;
}

interface Session {
  id: string;
  sub: string;
  title: string;
  created_at: number;
  updated_at: number;
}

interface Approval {
  id: string;
  session: string;
  tool: string;
  call_id: string;
  input: Record<string, unknown>;
  effect: string;
  status: "pending" | "approved" | "denied" | "expired";
  created_at: number;
  expires_at: number;
  decided_at: number | null;
}

type Block =
  | { type: "text"; text: string }
  | { type: "tool_use"; id: string; name: string; input: Record<string, unknown> }
  | { type: "tool_result"; id: string; name: string; text: string; error?: boolean };

interface StoredMessage {
  id: number;
  role: "user" | "assistant";
  content: Block[];
  at: number;
}

interface AppState {
  handle: string;
  github_id: number;
  settings: Settings;
  budget: Budget;
  subs: Sub[];
  sessions: Session[];
  approvals: Approval[];
  defaults: { persona: string; models: Record<string, Record<Role, string>> };
  providers: string[];
  unpriced: string[];
}

interface Template {
  id: string;
  about: string;
  persona: string;
}

// -- app state ---------------------------------------------------------------------------

const page = pageData<{ handle: string; dev: boolean; lang: UiLanguage }>();
const root = document.getElementById("app") as HTMLElement;

let state: AppState | null = null;
let lang: UiLanguage = page.lang === "tr" ? "tr" : "en";
let m: Messages = MESSAGES[lang];
/** The session open in the chat view, or null for a new one with `target`. */
let openSession: string | null = null;
/** The sub-tau a new chat goes to ('' = the main tau). */
let target = "";
let busy = false;

function setLanguage(next: UiLanguage | null): void {
  lang = next ?? lang;
  m = MESSAGES[lang];
  document.documentElement.lang = lang;
}

function errorText(err: unknown): string {
  if (!(err instanceof ApiError)) return m.err_network;
  const detail = err.detail ?? "";
  switch (err.code) {
    case "budget": {
      try {
        const b = JSON.parse(detail) as Budget;
        return m.err_budget(usd(b.spent_usd, lang), usd(b.budget_usd, lang), date(b.resets_at, lang));
      } catch {
        return m.notice_budget;
      }
    }
    case "busy":
      return m.err_busy;
    case "awaiting_approval":
      return m.err_awaiting_approval;
    case "not_onboarded":
      return m.err_not_onboarded;
    case "key_invalid":
      return m.err_key_invalid;
    case "key_unchecked":
      return m.err_key_unchecked;
    case "bad_key":
      return m.err_bad_key;
    case "vault":
      return m.err_vault;
    case "draft_failed":
      return m.err_draft_failed(detail);
    case "decided":
      return m.err_decided(detail);
    case "stale":
      return m.err_stale;
    case "network":
      return m.err_network;
    case "invalid_sub":
    case "exists":
    case "bad_request":
      return detail || m.err_generic(err.code);
    default:
      return streamErrorText(err.code, detail);
  }
}

function streamErrorText(code: string, detail: string): string {
  switch (code) {
    case "provider_auth":
      return m.err_provider_auth;
    case "provider_rate":
      return m.err_provider_rate;
    case "provider_unavailable":
      return m.err_provider_unavailable;
    case "provider_bad_request":
      return m.err_provider_bad_request(detail);
    case "provider_other":
      return m.err_provider_other(detail);
    case "vault":
      return m.err_vault;
    default:
      return m.err_generic(code);
  }
}

async function load(): Promise<void> {
  state = await call<AppState>("GET", "/api/host/state");
  setLanguage(state.settings.language);
}

// -- routing -----------------------------------------------------------------------------

type View =
  | { kind: "chat"; session: string | null }
  | { kind: "subs" }
  | { kind: "sub"; name: string }
  | { kind: "new-sub" }
  | { kind: "approvals" }
  | { kind: "settings" };

function parsePath(path: string): View {
  const parts = path.replace(/^\/app\/?/, "").split("/").filter(Boolean);
  if (parts[0] === "chat" && parts[1]) return { kind: "chat", session: parts[1] };
  if (parts[0] === "subs" && parts[1] === "new") return { kind: "new-sub" };
  if (parts[0] === "subs" && parts[1]) return { kind: "sub", name: parts[1] };
  if (parts[0] === "subs") return { kind: "subs" };
  if (parts[0] === "approvals") return { kind: "approvals" };
  if (parts[0] === "settings") return { kind: "settings" };
  return { kind: "chat", session: null };
}

function pathOf(view: View): string {
  switch (view.kind) {
    case "chat":
      return view.session ? `/app/chat/${view.session}` : "/app";
    case "subs":
      return "/app/subs";
    case "sub":
      return `/app/subs/${view.name}`;
    case "new-sub":
      return "/app/subs/new";
    case "approvals":
      return "/app/approvals";
    case "settings":
      return "/app/settings";
  }
}

function go(view: View, replace = false): void {
  const path = pathOf(view);
  if (replace) history.replaceState(null, "", path);
  else if (location.pathname !== path) history.pushState(null, "", path);
  root.classList.remove("nav-open");
  void render();
}

window.addEventListener("popstate", () => void render());

// -- small pieces ------------------------------------------------------------------------

function charOf(seed: string, label: string, size = 40, animated = false): HTMLElement {
  return h("span", { class: "ring" }, svg(character(seed, { size, animated, label })));
}

function subSeed(name: string): string {
  return `${state?.handle ?? page.handle}/${name}`;
}

function field(label: string, control: HTMLElement, help?: string): HTMLLabelElement {
  return h("label", { class: "field" }, h("span", {}, label), control, help ? h("span", { class: "help" }, help) : null);
}

function meter(): HTMLElement {
  const b = state?.budget;
  if (!b) return h("span");
  const ratio = b.budget_usd > 0 ? Math.min(b.spent_usd / b.budget_usd, 1) : 1;
  const step = Math.round(ratio * 10) * 10;
  return h(
    "div",
    { class: "meter", title: m.spent(usd(b.spent_usd, lang), usd(b.budget_usd, lang)) },
    h("span", { class: "label" }, `${usd(b.spent_usd, lang)} / ${usd(b.budget_usd, lang)}`),
    h("span", { class: "bar" }, h("span", { class: `fill w${step}` })),
  );
}

function navButtons(view: View): HTMLElement {
  const pending = state?.approvals.filter((a) => a.status === "pending").length ?? 0;
  const item = (label: string, next: View, current: boolean, extra?: HTMLElement | null) =>
    h(
      "button",
      { type: "button", "aria-current": current ? "page" : null, onclick: () => go(next) },
      label,
      extra ?? null,
    );
  return h(
    "nav",
    { class: "nav", "aria-label": m.menu },
    item(m.chat, { kind: "chat", session: openSession }, view.kind === "chat"),
    item(m.subTaus, { kind: "subs" }, view.kind === "subs" || view.kind === "sub" || view.kind === "new-sub"),
    item(m.approvals, { kind: "approvals" }, view.kind === "approvals", pending ? h("span", { class: "count" }, String(pending)) : null),
    item(m.settings, { kind: "settings" }, view.kind === "settings"),
  );
}

function topbar(view: View): HTMLElement {
  return h(
    "header",
    { class: "topbar app-top" },
    h(
      "a",
      { class: "brand", href: "/app" },
      markSvg(),
      h("span", {}, "tau"),
      h("span", { class: "brand-tag" }, "host"),
    ),
    h("span", { class: "handle" }, `@${state?.handle ?? page.handle}`),
    h("span", { class: "spacer" }),
    state?.settings.onboarded ? meter() : null,
    state?.settings.onboarded ? navButtons(view) : null,
    h(
      "button",
      {
        class: "btn ghost menu-toggle",
        type: "button",
        "aria-label": m.menu,
        onclick: () => root.classList.toggle("nav-open"),
      },
      "≡",
    ),
    signOutForm(),
  );
}

function markSvg(): HTMLElement {
  return svg(
    '<svg class="mark" viewBox="0 0 32 32" aria-hidden="true"><path d="M16 3 L29 27 L3 27 Z" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M10 13 H22 M16 13 V23" fill="none" stroke="currentColor" stroke-width="1.5"/></svg>',
    "mark-holder",
  );
}

function signOutForm(): HTMLElement {
  return h(
    "form",
    { method: "post", action: "/auth/logout" },
    h("button", { class: "btn ghost", type: "submit" }, m.signOut),
  );
}

// -- rendering ---------------------------------------------------------------------------

async function render(): Promise<void> {
  if (state === null) {
    try {
      await load();
    } catch (err) {
      clear(root);
      root.append(h("p", { class: "panel error-line" }, errorText(err)));
      return;
    }
  }
  const current = state as AppState;
  const view = parsePath(location.pathname);
  clear(root);
  if (!current.settings.onboarded) {
    root.append(topbar(view), h("div", { class: "narrow" }, onboarding()));
    return;
  }
  const main = h("main", { class: "main" });
  root.append(topbar(view), h("div", { class: "body" }, sidebar(view), main));
  switch (view.kind) {
    case "chat":
      await chatView(main, view.session);
      break;
    case "subs":
      subsView(main);
      break;
    case "sub":
      await subView(main, view.name);
      break;
    case "new-sub":
      await newSubView(main);
      break;
    case "approvals":
      approvalsView(main);
      break;
    case "settings":
      settingsView(main);
      break;
  }
}

function sidebar(view: View): HTMLElement {
  const current = state as AppState;
  const sessions = current.sessions;
  const list = h("ul", { class: "session-list" });
  for (const session of sessions) {
    list.append(
      h(
        "li",
        {},
        h(
          "button",
          {
            type: "button",
            "aria-current": view.kind === "chat" && view.session === session.id ? "true" : null,
            onclick: () => {
              openSession = session.id;
              go({ kind: "chat", session: session.id });
            },
          },
          h("span", { class: "who" }, session.sub ? `/${session.sub}` : "τ"),
          h("span", { class: "title" }, session.title || "…"),
        ),
      ),
    );
  }
  return h(
    "aside",
    { class: "side" },
    h("span", { class: "handle" }, `@${current.handle}`),
    meter(),
    navButtons(view),
    h(
      "button",
      {
        class: "btn primary",
        type: "button",
        onclick: () => {
          openSession = null;
          target = "";
          go({ kind: "chat", session: null });
        },
      },
      `+ ${m.newChat}`,
    ),
    h("h3", { class: "hud" }, m.sessions),
    sessions.length ? list : h("p", { class: "muted small" }, m.noSessions),
  );
}

// -- onboarding --------------------------------------------------------------------------

function onboarding(): HTMLElement {
  const current = state as AppState;
  const form = h("form", { class: "panel" });
  const error = h("p", { class: "error-line", role: "alert" });
  const providerLabel = (name: string) =>
    ({ anthropic: "Anthropic", openai: "OpenAI", gemini: "Google Gemini", fake: m.providerFake })[name] ?? name;

  const providers = h("div", {});
  current.providers.forEach((name, index) => {
    providers.append(
      h(
        "label",
        { class: "choice" },
        h("input", { type: "radio", name: "provider", value: name, checked: index === 0, required: true }),
        h("span", {}, providerLabel(name)),
      ),
    );
  });
  const key = h("input", { type: "password", name: "key", autocomplete: "off", spellcheck: "false", class: "code" });
  const language = h(
    "select",
    { name: "language" },
    h("option", { value: "en", selected: lang === "en" }, "English"),
    h("option", { value: "tr", selected: lang === "tr" }, "Türkçe"),
  );
  // The universe choice is explicit: neither option is preselected (ADR 0013 §4).
  const universe = h(
    "div",
    {},
    h("label", { class: "choice" }, h("input", { type: "radio", name: "universe", value: "yes", required: true }), h("span", {}, m.universeYes)),
    h("label", { class: "choice" }, h("input", { type: "radio", name: "universe", value: "no", required: true }), h("span", {}, m.universeNo)),
  );
  const submit = h("button", { class: "btn primary big", type: "submit" }, m.start);

  const keyField = field(m.key, key, m.keyHelp);
  const syncKey = () => {
    const chosen = (form.querySelector('input[name="provider"]:checked') as HTMLInputElement | null)?.value;
    keyField.hidden = chosen === "fake";
    key.required = chosen !== "fake";
  };
  providers.addEventListener("change", syncKey);

  form.append(
    h("h1", {}, m.onboardTitle),
    h("p", { class: "muted" }, m.onboardIntro),
    h("div", { class: "field" }, h("span", {}, m.provider), providers),
    keyField,
    field(m.language, language),
    h("div", { class: "field" }, h("span", {}, m.universe), h("span", { class: "help" }, m.universeHelp), universe, h("span", { class: "help" }, m.universeLater)),
    h(
      "div",
      { class: "notice" },
      h("strong", {}, m.privacyTitle),
      h("ul", { class: "lines" }, h("li", {}, m.privacy1), h("li", {}, m.privacy2), h("li", {}, m.privacy3)),
    ),
    error,
    submit,
  );
  syncKey();
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = new FormData(form);
    const choice = data.get("universe");
    if (choice !== "yes" && choice !== "no") return;
    submit.disabled = true;
    submit.textContent = m.checkingKey;
    error.textContent = "";
    try {
      state = await call<AppState>("POST", "/api/host/onboard", {
        provider: data.get("provider"),
        key: data.get("provider") === "fake" ? undefined : String(data.get("key") ?? ""),
        language: data.get("language"),
        universe: choice === "yes",
      });
      setLanguage(state.settings.language);
      go({ kind: "chat", session: null }, true);
    } catch (err) {
      error.textContent = errorText(err);
      submit.disabled = false;
      submit.textContent = m.start;
    }
  });
  return form;
}

// -- chat --------------------------------------------------------------------------------

function textOf(content: Block[]): string {
  return content
    .filter((b): b is Extract<Block, { type: "text" }> => b.type === "text")
    .map((b) => b.text)
    .join("");
}

function approvalCard(approval: Approval, onDecided: (list: StreamEvent[]) => void): HTMLElement {
  const pending = approval.status === "pending";
  const card = h("div", { class: `approval${pending ? "" : " done"}`, role: "group", "aria-label": m.approvalNeeded });
  const rows = h("dl", {});
  rows.append(h("dt", {}, "tool"), h("dd", {}, approval.tool));
  if (approval.effect) rows.append(h("dt", {}, "effect"), h("dd", {}, approval.effect));
  for (const [key, value] of Object.entries(approval.input)) {
    rows.append(h("dt", {}, key), h("dd", {}, typeof value === "string" ? value : JSON.stringify(value)));
  }
  const status = h("span", { class: pending ? "hud alert" : "hud" }, m[`status_${approval.status}`]);
  card.append(h("div", { class: "hud alert" }, m.approvalNeeded), rows);
  if (!pending) {
    card.append(status);
    return card;
  }
  const decide = async (decision: "approve" | "deny") => {
    for (const button of card.querySelectorAll("button")) button.disabled = true;
    const events: StreamEvent[] = [];
    try {
      await stream(`/api/host/approvals/${approval.id}`, { decision }, (event) => events.push(event));
    } catch (err) {
      card.append(h("p", { class: "error-line" }, errorText(err)));
    }
    onDecided(events);
  };
  card.append(
    h(
      "div",
      { class: "actions" },
      h("button", { class: "btn primary", type: "button", onclick: () => void decide("approve") }, m.approve),
      h("button", { class: "btn danger", type: "button", onclick: () => void decide("deny") }, m.deny),
      h("span", { class: "muted small" }, m.expiresAt(time(approval.expires_at, lang))),
    ),
  );
  return card;
}

function renderMessages(log: HTMLElement, messages: StoredMessage[], approvals: Approval[], who: string, refresh: () => void): void {
  const byCall = new Map(approvals.map((a) => [a.call_id, a]));
  for (const message of messages) {
    if (message.role === "user") {
      const text = textOf(message.content);
      if (text) log.append(h("div", { class: "msg user" }, h("span", { class: "from" }, m.you), h("div", { class: "text" }, text)));
      for (const block of message.content) {
        if (block.type !== "tool_result") continue;
        log.append(
          h(
            "details",
            { class: "result" },
            h("summary", {}, `${m.toolResult} · ${block.name}${block.error ? " · !" : ""}`),
            h("pre", {}, block.text),
          ),
        );
      }
      continue;
    }
    const wrap = h("div", { class: "msg assistant" }, h("span", { class: "from" }, who));
    const text = textOf(message.content);
    if (text) wrap.append(h("div", { class: "text" }, text));
    log.append(wrap);
    for (const block of message.content) {
      if (block.type !== "tool_use") continue;
      const approval = byCall.get(block.id);
      log.append(h("div", { class: `tool${approval ? " tier2" : ""}` }, m.toolCall(block.name)));
      if (approval) log.append(approvalCard(approval, refresh));
    }
  }
}

async function chatView(main: HTMLElement, sessionId: string | null): Promise<void> {
  const current = state as AppState;
  openSession = sessionId;
  let session: Session | null = null;
  let messages: StoredMessage[] = [];
  let approvals: Approval[] = [];
  if (sessionId) {
    try {
      const data = await call<{ session: Session; messages: StoredMessage[]; approvals: Approval[] }>(
        "GET",
        `/api/host/sessions/${sessionId}`,
      );
      session = data.session;
      messages = data.messages;
      approvals = data.approvals;
      target = session.sub;
    } catch {
      go({ kind: "chat", session: null }, true);
      return;
    }
  }
  const sub = target ? current.subs.find((s) => s.name === target) : undefined;
  const who = target ? `/${target}` : "tau";

  const head = h(
    "div",
    { class: "view-head" },
    h("h1", {}, target ? charOf(subSeed(target), `/${target}`, 30) : charOf(current.handle, "tau", 30), session?.title || (sub ? m.chatWith(sub.name) : m.newChat)),
  );
  if (session) {
    head.append(
      h(
        "button",
        {
          class: "btn ghost",
          type: "button",
          onclick: async () => {
            if (!confirm(m.confirmDeleteSession)) return;
            await call("DELETE", `/api/host/sessions/${session?.id}`);
            await load();
            openSession = null;
            go({ kind: "chat", session: null }, true);
          },
        },
        m.deleteSession,
      ),
    );
  }

  const log = h("div", { class: "log", "aria-live": "polite" });
  const refresh = async () => {
    await load();
    if (openSession) go({ kind: "chat", session: openSession }, true);
    else void render();
  };
  if (messages.length === 0) log.append(h("p", { class: "muted" }, m.noMessages));
  renderMessages(log, messages, approvals, who, () => void refresh());

  const text = h("textarea", {
    rows: 2,
    placeholder: target ? m.placeholderSub(target) : m.placeholderMain,
    "aria-label": m.send,
    maxlength: 20000,
  });
  const send = h("button", { class: "btn primary", type: "submit" }, m.send);
  const errorLine = h("p", { class: "error-line", role: "alert" });
  const composer = h("form", { class: "composer" }, text, send);

  const submit = async () => {
    const value = text.value.trim();
    if (!value || busy) return;
    busy = true;
    send.disabled = true;
    errorLine.textContent = "";
    if (messages.length === 0) clear(log);
    log.append(h("div", { class: "msg user" }, h("span", { class: "from" }, m.you), h("div", { class: "text" }, value)));
    text.value = "";
    let live: HTMLElement | null = null;
    let liveText: HTMLElement | null = null;
    let sessionOfTurn = openSession;
    const startLive = () => {
      liveText = h("div", { class: "text" });
      live = h("div", { class: "msg assistant streaming" }, h("span", { class: "from" }, who), liveText);
      log.append(live);
    };
    try {
      await stream("/api/host/chat", openSession ? { session: openSession, text: value } : { sub: target, text: value }, (event) => {
        switch (event.t) {
          case "start":
            sessionOfTurn = String(event.session);
            startLive();
            break;
          case "text":
            if (!liveText) startLive();
            (liveText as HTMLElement | null)?.append(String(event.d));
            window.scrollTo({ top: document.body.scrollHeight });
            break;
          case "tool":
            (live as HTMLElement | null)?.classList.remove("streaming");
            log.append(h("div", { class: `tool${Number(event.tier) >= 2 ? " tier2" : ""}` }, m.toolCall(String(event.name))));
            live = null;
            liveText = null;
            break;
          case "approval":
            log.append(approvalCard(event.approval as Approval, () => void refresh()));
            break;
          case "notice": {
            const key = `notice_${String(event.code)}` as keyof Messages;
            const note = m[key];
            log.append(h("p", { class: "notice" }, typeof note === "string" ? note : m.notice_stopped));
            break;
          }
          case "error":
            errorLine.textContent = streamErrorText(String(event.code), String(event.detail ?? ""));
            break;
        }
      });
    } catch (err) {
      errorLine.textContent = errorText(err);
    }
    busy = false;
    send.disabled = false;
    await load();
    if (sessionOfTurn) {
      openSession = sessionOfTurn;
      history.replaceState(null, "", `/app/chat/${sessionOfTurn}`);
    }
    const error = errorLine.textContent;
    void render().then(() => {
      if (error) main.querySelector(".error-line")?.append(error);
    });
  };
  composer.addEventListener("submit", (event) => {
    event.preventDefault();
    void submit();
  });
  text.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      void submit();
    }
  });

  main.append(h("section", { class: "chat-view" }, head, log, h("div", {}, errorLine, composer)));
  text.focus();
}

// -- sub-taus ----------------------------------------------------------------------------

function subCard(sub: Sub): HTMLElement {
  return h(
    "button",
    { class: "card", type: "button", onclick: () => go({ kind: "sub", name: sub.name }) },
    charOf(subSeed(sub.name), `/${sub.name}`, 44, true),
    h(
      "span",
      {},
      h("span", { class: "name" }, `/${sub.name}`),
      h("p", { class: "about" }, sub.about),
      h(
        "span",
        { class: "badges" },
        h("span", { class: "badge" }, sub.role),
        sub.public ? h("span", { class: "badge on" }, m.public) : null,
        sub.public && sub.web ? h("span", { class: "badge on" }, m.web) : null,
      ),
    ),
  );
}

function subsView(main: HTMLElement): void {
  const current = state as AppState;
  main.append(
    h(
      "div",
      { class: "view-head" },
      h("h1", {}, m.subTaus),
      h("button", { class: "btn primary", type: "button", onclick: () => go({ kind: "new-sub" }) }, `+ ${m.newSub}`),
    ),
  );
  if (current.subs.length === 0) {
    main.append(h("p", { class: "muted" }, m.noSubs));
    return;
  }
  main.append(h("div", { class: "cards" }, current.subs.map(subCard)));
}

interface SubForm {
  element: HTMLFormElement;
  read(): Record<string, unknown>;
}

function subForm(initial: Partial<Sub>, isNew: boolean, onSubmit: (value: Record<string, unknown>, status: HTMLElement) => Promise<void>): SubForm {
  const name = h("input", { name: "name", value: initial.name ?? "", required: true, pattern: "[a-z][a-z0-9-]{1,30}", class: "code", disabled: !isNew });
  const about = h("input", { name: "about", value: initial.about ?? "", required: true, maxlength: 200 });
  const persona = h("textarea", { name: "persona", rows: 10, required: true, maxlength: 20000 });
  persona.value = initial.persona ?? "";
  const role = h(
    "select",
    { name: "role" },
    h("option", { value: "brain", selected: (initial.role ?? "brain") === "brain" }, m.roleBrain),
    h("option", { value: "fast", selected: initial.role === "fast" }, m.roleFast),
  );
  const isPublic = h("input", { type: "checkbox", name: "public", checked: initial.public ?? false });
  const note = h("textarea", { name: "public_note", rows: 3, maxlength: 4000 });
  note.value = initial.public_note ?? "";
  const web = h("input", { type: "checkbox", name: "web", checked: initial.web ?? false });
  const daily = h("input", { type: "number", name: "web_daily", min: 1, max: 1000, step: 1, value: initial.web_daily ?? 50 });
  const starters = [0, 1, 2, 3].map((i) => h("input", { value: initial.starters?.[i] ?? "", maxlength: 80 }));
  const status = h("p", { class: "ok-note", role: "status" });
  const syncWeb = () => {
    web.disabled = !isPublic.checked;
    if (!isPublic.checked) web.checked = false;
  };
  isPublic.addEventListener("change", syncWeb);
  syncWeb();

  const element = h(
    "form",
    { class: "panel" },
    h("div", { class: "row" }, field(m.name, name, isNew ? m.nameHelp : undefined), field(m.role, role)),
    field(m.about, about),
    field(m.persona, persona),
    h("h3", { class: "hud" }, m.flags),
    h("label", { class: "check" }, isPublic, h("span", {}, h("strong", {}, m.public), h("span", { class: "muted small" }, m.publicHelp))),
    field(m.publicNote, note, m.publicNoteHelp),
    h("label", { class: "check" }, web, h("span", {}, h("strong", {}, m.web), h("span", { class: "muted small" }, `${m.webHelp} ${m.webNeedsPublic}`))),
    h("div", { class: "row" }, field(m.webDaily, daily)),
    h("div", { class: "field" }, h("span", {}, m.starters), h("span", { class: "help" }, m.startersHelp), h("div", { class: "starters-edit" }, starters)),
    status,
    h("div", { class: "row" }, h("button", { class: "btn primary", type: "submit" }, isNew ? m.create : m.save)),
  );
  const read = () => ({
    ...(isNew ? { name: name.value.trim() } : {}),
    about: about.value,
    persona: persona.value,
    role: role.value,
    public: isPublic.checked,
    public_note: note.value,
    web: web.checked,
    web_daily: Number(daily.value),
    starters: starters.map((s) => s.value).filter((s) => s.trim()),
  });
  element.addEventListener("submit", (event) => {
    event.preventDefault();
    void onSubmit(read(), status);
  });
  return { element, read };
}

async function newSubView(main: HTMLElement): Promise<void> {
  main.append(
    h(
      "div",
      { class: "view-head" },
      h("h1", {}, m.newSub),
      h("button", { class: "btn ghost", type: "button", onclick: () => go({ kind: "subs" }) }, m.cancel),
    ),
  );
  const templates = await call<Template[]>("GET", "/api/host/templates").catch(() => [] as Template[]);
  const holder = h("div", {});
  const showForm = (initial: Partial<Sub>) => {
    clear(holder);
    const form = subForm(initial, true, async (value, status) => {
      status.textContent = "";
      try {
        const created = await call<Sub>("POST", "/api/host/subs", value);
        await load();
        go({ kind: "sub", name: created.name }, true);
      } catch (err) {
        status.textContent = errorText(err);
        status.className = "error-line";
      }
    });
    holder.append(form.element);
  };

  const tabDescribe = h("button", { type: "button", role: "tab", "aria-selected": "true" }, m.describe);
  const tabTemplate = h("button", { type: "button", role: "tab", "aria-selected": "false" }, m.fromTemplate);
  const pane = h("div", { class: "panel" });
  const showDescribe = () => {
    tabDescribe.setAttribute("aria-selected", "true");
    tabTemplate.setAttribute("aria-selected", "false");
    clear(pane);
    const name = h("input", { required: true, pattern: "[a-z][a-z0-9-]{1,30}", class: "code", placeholder: "coach" });
    const description = h("textarea", { rows: 4, required: true, maxlength: 2000 });
    const button = h("button", { class: "btn primary", type: "submit" }, m.draftIt);
    const status = h("p", { class: "error-line", role: "alert" });
    const form = h("form", {}, field(m.name, name, m.nameHelp), field(m.describe, description, m.describeHelp), status, button);
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      button.disabled = true;
      button.textContent = m.drafting;
      status.textContent = "";
      try {
        const draft = await call<{ about: string; persona: string }>("POST", "/api/host/draft", {
          name: name.value.trim(),
          description: description.value,
        });
        showForm({ name: name.value.trim(), about: draft.about, persona: draft.persona });
      } catch (err) {
        status.textContent = errorText(err);
      }
      button.disabled = false;
      button.textContent = m.draftIt;
    });
    pane.append(form);
  };
  const showTemplates = () => {
    tabDescribe.setAttribute("aria-selected", "false");
    tabTemplate.setAttribute("aria-selected", "true");
    clear(pane);
    const labels: Record<string, string> = {
      blank: m.template_blank,
      coach: m.template_coach,
      writer: m.template_writer,
      tutor: m.template_tutor,
    };
    pane.append(
      h(
        "div",
        { class: "cards" },
        templates.map((template) =>
          h(
            "button",
            {
              class: "card",
              type: "button",
              onclick: () => showForm({ name: template.id === "blank" ? "" : template.id, about: template.about, persona: template.persona }),
            },
            charOf(`template/${template.id}`, labels[template.id] ?? template.id, 40),
            h("span", {}, h("span", { class: "name" }, labels[template.id] ?? template.id), h("p", { class: "about" }, template.about)),
          ),
        ),
      ),
    );
  };
  tabDescribe.addEventListener("click", showDescribe);
  tabTemplate.addEventListener("click", showTemplates);
  main.append(h("p", { class: "hud" }, m.howToStart), h("div", { class: "tabs", role: "tablist" }, tabDescribe, tabTemplate), pane, holder);
  showDescribe();
}

async function subView(main: HTMLElement, name: string): Promise<void> {
  const current = state as AppState;
  const sub = current.subs.find((s) => s.name === name);
  if (!sub) {
    go({ kind: "subs" }, true);
    return;
  }
  const actions = h(
    "div",
    { class: "row" },
    h(
      "button",
      {
        class: "btn primary",
        type: "button",
        onclick: () => {
          openSession = null;
          target = sub.name;
          go({ kind: "chat", session: null });
        },
      },
      m.chatWith(sub.name),
    ),
    sub.public && sub.web ? h("a", { class: "btn", href: `/@${current.handle}/${sub.name}`, target: "_blank", rel: "noopener" }, m.openPage) : null,
    h(
      "button",
      {
        class: "btn danger",
        type: "button",
        onclick: async () => {
          if (!confirm(m.confirmDeleteSub(sub.name))) return;
          await call("DELETE", `/api/host/subs/${sub.name}`);
          await load();
          go({ kind: "subs" }, true);
        },
      },
      m.delete,
    ),
  );
  main.append(
    h(
      "div",
      { class: "view-head" },
      h("h1", {}, charOf(subSeed(sub.name), `/${sub.name}`, 44, true), `/${sub.name}`),
      actions,
    ),
  );
  if (sub.public && sub.web) main.append(h("p", { class: "hud" }, m.visitsToday(sub.visits_today, sub.web_daily)));
  const form = subForm(sub, false, async (value, status) => {
    status.className = "ok-note";
    try {
      await call<Sub>("PUT", `/api/host/subs/${sub.name}`, value);
      await load();
      status.textContent = m.saved;
    } catch (err) {
      status.textContent = errorText(err);
      status.className = "error-line";
    }
  });
  main.append(form.element);

  if (sub.public && sub.web) {
    const panel = h("section", { class: "panel" }, h("h2", { class: "hud" }, m.visitorChats));
    main.append(panel);
    try {
      const threads = await call<{ id: string; created_at: number; messages: { role: string; text: string; at: number }[] }[]>(
        "GET",
        `/api/host/subs/${sub.name}/visits`,
      );
      if (threads.length === 0) panel.append(h("p", { class: "muted small" }, m.noVisitorChats));
      for (const thread of threads) {
        panel.append(
          h(
            "div",
            { class: "thread" },
            thread.messages.map((message) =>
              h("p", {}, h("span", { class: "who" }, message.role === "sub" ? `/${sub.name}` : m.visitor), message.text),
            ),
          ),
        );
      }
    } catch (err) {
      panel.append(h("p", { class: "error-line" }, errorText(err)));
    }
  }
}

// -- approvals ---------------------------------------------------------------------------

function approvalsView(main: HTMLElement): void {
  const current = state as AppState;
  main.append(h("div", { class: "view-head" }, h("h1", {}, m.approvals)));
  const pending = current.approvals.filter((a) => a.status === "pending");
  if (pending.length === 0) {
    main.append(h("p", { class: "muted" }, m.noApprovals));
    return;
  }
  for (const approval of pending) {
    main.append(
      approvalCard(approval, () => {
        void load().then(() => {
          openSession = approval.session;
          go({ kind: "chat", session: approval.session });
        });
      }),
      h(
        "p",
        {},
        h("button", { class: "btn ghost", type: "button", onclick: () => go({ kind: "chat", session: approval.session }) }, m.openSession),
      ),
    );
  }
}

// -- settings ----------------------------------------------------------------------------

function settingsView(main: HTMLElement): void {
  const current = state as AppState;
  const s = current.settings;
  main.append(h("div", { class: "view-head" }, h("h1", {}, m.settings)));

  const section = (title: string, ...children: (Node | null)[]) =>
    h("section", { class: "panel" }, h("h2", { class: "hud" }, title), ...children);

  const saveWith = (build: () => Record<string, unknown>) => async (event: Event) => {
    event.preventDefault();
    const form = event.currentTarget as HTMLFormElement;
    const status = form.querySelector(".status") as HTMLElement;
    const button = form.querySelector("button[type=submit]") as HTMLButtonElement | null;
    status.className = "status ok-note";
    status.textContent = "";
    if (button) button.disabled = true;
    try {
      state = await call<AppState>("PATCH", "/api/host/settings", build());
      const languageChanged = state.settings.language !== lang;
      setLanguage(state.settings.language);
      if (languageChanged) {
        void render();
        return;
      }
      status.textContent = m.saved;
    } catch (err) {
      status.className = "status error-line";
      status.textContent = errorText(err);
    }
    if (button) button.disabled = false;
  };
  const statusLine = () => h("p", { class: "status ok-note", role: "status" });
  const saveButton = () => h("button", { class: "btn primary", type: "submit" }, m.save);

  // Provider and key
  const provider = h(
    "select",
    { name: "provider" },
    current.providers.map((name) => h("option", { value: name, selected: name === s.provider }, name)),
  );
  const key = h("input", { type: "password", autocomplete: "off", spellcheck: "false", class: "code" });
  const keyForm = h(
    "form",
    {},
    h("p", { class: "mono" }, s.provider ? m.currentKey(s.provider, s.key_last4 || "—") : m.noKey),
    h("div", { class: "row" }, field(m.provider, provider), field(m.replaceKey, key)),
    statusLine(),
    saveButton(),
  );
  keyForm.addEventListener(
    "submit",
    saveWith(() => ({ provider: provider.value, ...(key.value.trim() ? { key: key.value.trim() } : {}) })),
  );

  // Models
  const brain = h("input", { value: s.models.brain, class: "code", list: "model-ids" });
  const fast = h("input", { value: s.models.fast, class: "code", list: "model-ids" });
  const ids = new Set(Object.values(current.defaults.models).flatMap((r) => [r.brain, r.fast]));
  const modelsForm = h(
    "form",
    {},
    h("p", { class: "muted small" }, m.modelsHelp),
    h("datalist", { id: "model-ids" }, [...ids].map((id) => h("option", { value: id }))),
    h("div", { class: "row" }, field("brain", brain), field("fast", fast)),
    current.unpriced.length ? h("p", { class: "notice" }, m.unpriced(current.unpriced.join(", "))) : null,
    statusLine(),
    saveButton(),
  );
  modelsForm.addEventListener("submit", saveWith(() => ({ models: { brain: brain.value.trim(), fast: fast.value.trim() } })));

  // Budget and language
  const budget = h("input", { type: "number", min: 0, max: 1000, step: 0.5, value: s.budget_usd });
  const language = h(
    "select",
    {},
    h("option", { value: "en", selected: lang === "en" }, "English"),
    h("option", { value: "tr", selected: lang === "tr" }, "Türkçe"),
  );
  const generalForm = h(
    "form",
    {},
    h("p", { class: "mono" }, m.spent(usd(current.budget.spent_usd, lang), usd(current.budget.budget_usd, lang))),
    h("div", { class: "row" }, field(m.budget, budget, m.budgetHelp), field(m.language, language)),
    statusLine(),
    saveButton(),
  );
  generalForm.addEventListener("submit", saveWith(() => ({ budget_usd: Number(budget.value), language: language.value })));

  // Persona and profile
  const persona = h("textarea", { rows: 12, class: "code", maxlength: 20000 });
  persona.value = s.persona ?? current.defaults.persona;
  const personaForm = h(
    "form",
    {},
    field(m.persona, persona, m.personaHelp),
    statusLine(),
    h(
      "div",
      { class: "row" },
      saveButton(),
      h(
        "button",
        {
          class: "btn ghost",
          type: "button",
          onclick: () => {
            persona.value = current.defaults.persona;
          },
        },
        m.resetPersona,
      ),
    ),
  );
  personaForm.addEventListener(
    "submit",
    saveWith(() => ({ persona: persona.value.trim() === current.defaults.persona.trim() ? null : persona.value })),
  );
  const profile = h("textarea", { rows: 8, maxlength: 20000 });
  profile.value = s.profile;
  const profileForm = h("form", {}, field(m.profile, profile, m.profileHelp), statusLine(), saveButton());
  profileForm.addEventListener("submit", saveWith(() => ({ profile: profile.value })));

  // Universe
  const yes = h("input", { type: "radio", name: "universe-setting", value: "yes", checked: s.universe === true });
  const no = h("input", { type: "radio", name: "universe-setting", value: "no", checked: s.universe === false });
  const universeForm = h(
    "form",
    {},
    h("p", { class: "muted small" }, m.universeHelp),
    h("label", { class: "choice" }, yes, h("span", {}, m.universeYes)),
    h("label", { class: "choice" }, no, h("span", {}, m.universeNo)),
    h("p", { class: "muted small" }, m.universeSaved),
    statusLine(),
    saveButton(),
  );
  universeForm.addEventListener("submit", saveWith(() => ({ universe: yes.checked })));

  // Export and delete
  const confirmInput = h("input", { class: "code", autocomplete: "off", placeholder: current.handle });
  const deleteButton = h("button", { class: "btn danger", type: "submit", disabled: true }, m.deleteButton);
  confirmInput.addEventListener("input", () => {
    deleteButton.disabled = confirmInput.value !== current.handle;
  });
  const deleteForm = h("form", {}, h("p", { class: "muted small" }, m.deleteHelp), field(m.deleteConfirm(current.handle), confirmInput), statusLine(), deleteButton);
  deleteForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await call("POST", "/api/host/account/delete", { confirm: confirmInput.value });
      location.href = "/";
    } catch (err) {
      (deleteForm.querySelector(".status") as HTMLElement).textContent = errorText(err);
    }
  });

  main.append(
    section(m.provider, keyForm),
    section(m.models, modelsForm),
    section(`${m.budget} · ${m.language}`, generalForm),
    section(m.persona, personaForm),
    section(m.profile, profileForm),
    section(m.universeSetting, universeForm),
    section(
      m.exportTitle,
      h("p", { class: "muted small" }, m.exportHelp),
      h("a", { class: "btn", href: "/api/host/export", download: `tau-${current.handle}-export.json` }, m.exportButton),
    ),
    section(m.deleteAccount, deleteForm),
  );
}

void render();
