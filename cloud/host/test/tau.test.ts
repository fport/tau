/**
 * A hosted tau end to end through the Worker: onboarding and settings (the key never comes
 * back), chat turns streamed as NDJSON on the fake provider, tier-2 approvals (pause,
 * approve, deny, expiry), budgets, export and account deletion.
 */

import { reset, runDurableObjectAlarm, runInDurableObject } from "cloudflare:test";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import anthropicText from "./fixtures/anthropic-text.sse?raw";
import {
  api,
  apiJson,
  devSignIn,
  events,
  mockFetch,
  onboardedOwner,
  type Owner,
  sse,
  streamedText,
  tau,
} from "./helpers";

beforeEach(async () => {
  await reset();
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

const KEY = "sk-ant-test-0000000000000000000000000abcd";

interface State {
  settings: Record<string, unknown>;
  budget: { spent_usd: number; budget_usd: number; exhausted: boolean };
  subs: { name: string }[];
  sessions: { id: string; sub: string; title: string }[];
  approvals: { id: string; status: string; tool: string; input: Record<string, unknown>; session: string }[];
  providers: string[];
}

async function state(owner: Owner): Promise<State> {
  return (await apiJson<State>(owner, "GET", "/api/host/state")).body;
}

async function chat(owner: Owner, body: Record<string, unknown>) {
  const response = await api(owner, "POST", "/api/host/chat", body);
  return { response, list: response.status === 200 ? await events(response) : [] };
}

describe("onboarding and settings", () => {
  it("needs a provider, a language and an explicit universe choice", async () => {
    const owner = await devSignIn("alice");
    expect((await state(owner)).settings.onboarded).toBe(false);
    const missing = await api(owner, "POST", "/api/host/onboard", { provider: "fake", language: "en" });
    expect(missing.status).toBe(400);
    expect(await missing.text()).toContain("universe must be chosen explicitly");
    const ok = await apiJson<State>(owner, "POST", "/api/host/onboard", { provider: "fake", language: "tr", universe: true });
    expect(ok.status).toBe(200);
    expect(ok.body.settings).toMatchObject({ onboarded: true, provider: "fake", language: "tr", universe: true });
  });

  it("checks a key with one request, seals it, and shows only provider and last four", async () => {
    const { seen } = mockFetch({ "https://api.anthropic.com/v1/models": () => Response.json({ data: [] }) });
    const owner = await devSignIn("alice");
    const response = await api(owner, "POST", "/api/host/onboard", {
      provider: "anthropic",
      key: KEY,
      language: "en",
      universe: false,
    });
    const text = await response.text();
    expect(response.status).toBe(200);
    expect(text).not.toContain(KEY);
    expect(seen).toHaveLength(1);
    const settings = JSON.parse(text).settings;
    expect(settings).toMatchObject({ provider: "anthropic", key_last4: "abcd", has_key: true });
    expect(settings.models).toEqual({ brain: "claude-sonnet-5", fast: "claude-haiku-4-5" });
    const stored = await runInDurableObject(tau("alice"), (_i, s) =>
      s.storage.sql.exec<{ value: string }>("SELECT value FROM settings WHERE key = 'key'").toArray(),
    );
    expect(stored[0]?.value).toMatch(/^"v1\./);
    expect(stored[0]?.value).not.toContain("abcd");
    const exported = await (await api(owner, "GET", "/api/host/export")).text();
    expect(exported).not.toContain(KEY);
    expect(exported).not.toContain("v1.");
  });

  it("refuses a key the provider rejects and stores nothing", async () => {
    mockFetch({ "https://api.openai.com/v1/models": () => new Response("{}", { status: 401 }) });
    const owner = await devSignIn("alice");
    const response = await apiJson(owner, "POST", "/api/host/onboard", {
      provider: "openai",
      key: "sk-wrong-000000000000",
      language: "en",
      universe: false,
    });
    expect(response).toEqual({ status: 400, body: { error: "key_invalid" } });
    expect((await state(owner)).settings).toMatchObject({ onboarded: false, has_key: false });
  });

  it("offers the fake provider only when FAKE_PROVIDER is on", async () => {
    const owner = await devSignIn("alice");
    expect((await state(owner)).providers).toEqual(["anthropic", "openai", "gemini", "fake"]);
    const refused = await runInDurableObject(tau("alice"), (instance) =>
      instance.onboard({ provider: "fake", language: "en", universe: false }, false),
    );
    expect(refused).toMatchObject({ ok: false, status: 400 });
  });

  it("changes models, budget, language, persona and profile, and validates them", async () => {
    const owner = await onboardedOwner();
    const good = await apiJson<State>(owner, "PATCH", "/api/host/settings", {
      models: { fast: "fake-mini" },
      budget_usd: 2.5,
      language: "tr",
      persona: "You are terse.",
      profile: "- Name: Alice",
    });
    expect(good.status).toBe(200);
    expect(good.body.settings).toMatchObject({
      models: { brain: "fake-brain", fast: "fake-mini" },
      budget_usd: 2.5,
      language: "tr",
      persona: "You are terse.",
      profile: "- Name: Alice",
    });
    const bad = await api(owner, "PATCH", "/api/host/settings", { budget_usd: -1, language: "de" });
    expect(bad.status).toBe(400);
    const reset_ = await apiJson<State>(owner, "PATCH", "/api/host/settings", { persona: null });
    expect(reset_.body.settings.persona).toBeNull();
  });
});

describe("chat", () => {
  it("streams a turn as NDJSON and stores the session", async () => {
    const owner = await onboardedOwner();
    const { response, list } = await chat(owner, { text: "Hello there" });
    expect(response.headers.get("content-type")).toContain("application/x-ndjson");
    expect(list[0]).toMatchObject({ t: "start", sub: "" });
    expect(streamedText(list)).toBe("(fake) You said: Hello there");
    expect(list.at(-1)).toMatchObject({ t: "done", stop: "end" });
    const session = String(list[0]?.session);
    const stored = await apiJson<{ session: { title: string }; messages: { role: string }[] }>(
      owner,
      "GET",
      `/api/host/sessions/${session}`,
    );
    expect(stored.body.session.title).toBe("Hello there");
    expect(stored.body.messages.map((m) => m.role)).toEqual(["user", "assistant"]);

    const again = await chat(owner, { session, text: "Second" });
    expect(streamedText(again.list)).toBe("(fake) You said: Second");
    expect((await state(owner)).sessions).toHaveLength(1);
  });

  it("refuses before onboarding and with an empty text", async () => {
    const owner = await devSignIn("alice");
    expect((await chat(owner, { text: "Hi" })).response.status).toBe(409);
    const ready = await onboardedOwner("bob");
    expect((await chat(ready, { text: "   " })).response.status).toBe(400);
  });

  it("sends the persona, the profile and the history to the provider, and prices the usage", async () => {
    const { seen } = mockFetch({
      "https://api.anthropic.com/v1/models": () => Response.json({ data: [] }),
      "https://api.anthropic.com/v1/messages": () => sse(anthropicText),
    });
    const owner = await devSignIn("alice");
    await api(owner, "POST", "/api/host/onboard", { provider: "anthropic", key: KEY, language: "en", universe: false });
    await api(owner, "PATCH", "/api/host/settings", { profile: "- Name: Alice <!-- hidden note -->" });
    const { list } = await chat(owner, { text: "Hi" });
    expect(streamedText(list)).toBe("Hello, how can I help?");
    const body = JSON.parse(seen.at(-1)?.body ?? "{}");
    expect(body.model).toBe("claude-sonnet-5");
    expect(body.system).toContain("Sen tau'sun");
    expect(body.system).toContain("## User\n- Name: Alice");
    expect(body.system).not.toContain("hidden note");
    expect(body.system).toContain("## Now\n- Date and time:");
    expect(body.tools.map((t: { name: string }) => t.name)).toEqual(["ask_sub", "create_sub"]);
    const budget = (await state(owner)).budget;
    expect(budget.spent_usd).toBeCloseTo((412 * 2 + 12 * 10 + 100 * 0.2) / 1e6, 9);
  });

  it("a provider error ends the stream with an error code and no key", async () => {
    mockFetch({
      "https://api.anthropic.com/v1/models": () => Response.json({ data: [] }),
      "https://api.anthropic.com/v1/messages": () => new Response(JSON.stringify({ error: { message: `bad ${KEY}` } }), { status: 401 }),
    });
    const owner = await devSignIn("alice");
    await api(owner, "POST", "/api/host/onboard", { provider: "anthropic", key: KEY, language: "en", universe: false });
    const { list } = await chat(owner, { text: "Hi" });
    expect(list.at(-1)).toMatchObject({ t: "error", code: "provider_auth" });
    expect(JSON.stringify(list)).not.toContain(KEY);
  });
});

describe("approvals", () => {
  async function pausedTurn(owner: Owner) {
    const { list } = await chat(owner, { text: "/create coach A strict but kind workout coach." });
    const approval = list.find((event) => event.t === "approval")?.approval as { id: string; tool: string; status: string };
    return { list, approval, session: String(list[0]?.session) };
  }

  it("pauses a create_sub call with an approval card and creates nothing", async () => {
    const owner = await onboardedOwner();
    const { list, approval, session } = await pausedTurn(owner);
    expect(list.find((e) => e.t === "tool")).toMatchObject({ name: "create_sub", tier: 2 });
    expect(approval).toMatchObject({ tool: "create_sub", status: "pending" });
    expect(list.at(-1)).toMatchObject({ t: "done", stop: "paused", approval: approval.id });
    const now = await state(owner);
    expect(now.subs).toEqual([]);
    expect(now.approvals.map((a) => a.id)).toEqual([approval.id]);
    // The session waits for the answer.
    const blocked = await chat(owner, { session, text: "and?" });
    expect(blocked.response.status).toBe(409);
    expect(await blocked.response.json()).toEqual({ error: "awaiting_approval", detail: "answer the approval in this session first" });
  });

  it("approve runs the call and resumes the turn", async () => {
    const owner = await onboardedOwner();
    const { approval, session } = await pausedTurn(owner);
    const resumed = await api(owner, "POST", `/api/host/approvals/${approval.id}`, { decision: "approve" });
    const list = await events(resumed);
    expect(list.find((e) => e.t === "tool_result")).toMatchObject({ name: "create_sub", error: false });
    expect(streamedText(list)).toContain("Done. Created /coach.");
    expect(list.at(-1)).toMatchObject({ t: "done", stop: "end" });
    const now = await state(owner);
    expect(now.subs.map((s) => s.name)).toEqual(["coach"]);
    expect(now.approvals).toEqual([]);
    const again = await api(owner, "POST", `/api/host/approvals/${approval.id}`, { decision: "approve" });
    expect(again.status).toBe(409);
    // The session takes new messages again.
    expect((await chat(owner, { session, text: "thanks" })).response.status).toBe(200);
  });

  it("deny refuses the call and the turn goes on", async () => {
    const owner = await onboardedOwner();
    const { approval } = await pausedTurn(owner);
    const list = await events(await api(owner, "POST", `/api/host/approvals/${approval.id}`, { decision: "deny" }));
    expect(list.find((e) => e.t === "tool_result")).toMatchObject({ name: "create_sub", error: true });
    expect(streamedText(list)).toContain("did not approve create_sub");
    expect((await state(owner)).subs).toEqual([]);
  });

  it("an approval nobody answers expires after 10 minutes and is refused", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-09-30T12:00:00Z"));
    const owner = await onboardedOwner();
    const { approval, session } = await pausedTurn(owner);
    vi.setSystemTime(new Date("2026-09-30T12:09:59Z"));
    await runDurableObjectAlarm(tau("alice"));
    expect((await state(owner)).approvals).toHaveLength(1);
    vi.setSystemTime(new Date("2026-09-30T12:10:01Z"));
    await runDurableObjectAlarm(tau("alice"));
    const stored = await apiJson<{ approvals: { status: string }[]; messages: { content: { type: string; text?: string }[] }[] }>(
      owner,
      "GET",
      `/api/host/sessions/${session}`,
    );
    expect(stored.body.approvals[0]?.status).toBe("expired");
    expect(stored.body.messages.at(-1)?.content[0]?.text).toContain("within 10 minutes");
    expect((await state(owner)).subs).toEqual([]);
    const late = await api(owner, "POST", `/api/host/approvals/${approval.id}`, { decision: "approve" });
    expect(late.status).toBe(409);
    expect((await state(owner)).subs).toEqual([]);
  });

  it("an approval answered after its time without the alarm is still refused", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-09-30T12:00:00Z"));
    const owner = await onboardedOwner();
    const { approval } = await pausedTurn(owner);
    vi.setSystemTime(new Date("2026-09-30T12:11:00Z"));
    const late = await apiJson(owner, "POST", `/api/host/approvals/${approval.id}`, { decision: "approve" });
    expect(late).toEqual({ status: 409, body: { error: "decided", detail: "expired" } });
    expect((await state(owner)).subs).toEqual([]);
  });

  it("only the owner's own session can decide: another account does not see the approval", async () => {
    const alice = await onboardedOwner("alice");
    const { approval } = await pausedTurn(alice);
    const bob = await onboardedOwner("bob");
    const response = await api(bob, "POST", `/api/host/approvals/${approval.id}`, { decision: "approve" });
    expect(response.status).toBe(404);
    expect((await state(alice)).subs).toEqual([]);
  });
});

describe("budget", () => {
  async function spend(handle: string, usd: number) {
    await runInDurableObject(tau(handle), (_i, s) => {
      const now = Math.floor(Date.now() / 1000);
      s.storage.sql.exec(
        `INSERT INTO spend (at, month, kind, role, sub, provider, model, input, output, cache_read, cache_write, cost_usd)
         VALUES (?, ?, 'chat', 'brain', '', 'anthropic', 'claude-sonnet-5', 0, 0, 0, 0, ?)`,
        now,
        new Date(now * 1000).toISOString().slice(0, 7),
        usd,
      );
    });
  }

  it("refuses a turn that would start over the monthly budget, clearly", async () => {
    const owner = await onboardedOwner();
    await spend("alice", 5.01);
    const { response } = await chat(owner, { text: "Hi" });
    expect(response.status).toBe(402);
    const body = (await response.json()) as { error: string; detail: string };
    expect(body.error).toBe("budget");
    const detail = JSON.parse(body.detail);
    expect(detail).toMatchObject({ budget_usd: 5, exhausted: true });
    expect(detail.spent_usd).toBeCloseTo(5.01);
    // Raising the budget lets turns start again.
    await api(owner, "PATCH", "/api/host/settings", { budget_usd: 10 });
    expect((await chat(owner, { text: "Hi" })).response.status).toBe(200);
  });

  it("counts the calendar month in UTC", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-09-30T23:00:00Z"));
    const owner = await onboardedOwner();
    await spend("alice", 6);
    expect((await chat(owner, { text: "Hi" })).response.status).toBe(402);
    vi.setSystemTime(new Date("2026-10-01T00:00:01Z"));
    expect((await chat(owner, { text: "Hi" })).response.status).toBe(200);
  });
});

describe("export and delete", () => {
  it("exports everything but the key", async () => {
    const owner = await onboardedOwner();
    await chat(owner, { text: "Remember this" });
    const response = await api(owner, "GET", "/api/host/export");
    expect(response.headers.get("content-disposition")).toContain('filename="tau-alice-export.json"');
    const data = (await response.json()) as { format: string; handle: string; sessions: { messages: unknown[] }[] };
    expect(data.format).toBe("tau-host-export/1");
    expect(data.handle).toBe("alice");
    expect(data.sessions[0]?.messages).toHaveLength(2);
  });

  it("deletes the tau and the account after the handle is typed", async () => {
    const owner = await onboardedOwner();
    await chat(owner, { text: "Hi" });
    expect((await api(owner, "POST", "/api/host/account/delete", { confirm: "bob" })).status).toBe(400);
    const done = await api(owner, "POST", "/api/host/account/delete", { confirm: "alice" });
    expect(done.status).toBe(200);
    expect(done.headers.getSetCookie().join()).toContain("Max-Age=0");
    expect((await api(owner, "GET", "/api/host/whoami")).status).toBe(401);
    const left = await runInDurableObject(tau("alice"), (_i, s) => ({
      settings: s.storage.sql.exec("SELECT * FROM settings").toArray().length,
      messages: s.storage.sql.exec("SELECT * FROM messages").toArray().length,
    }));
    expect(left).toEqual({ settings: 0, messages: 0 });
    // Signing in again starts a fresh tau.
    const again = await devSignIn("alice");
    expect((await state(again)).settings.onboarded).toBe(false);
  });
});
