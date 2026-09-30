/** Sub-taus: validation, the owner's API, drafting, ask_sub and chats with a sub-tau. */

import { reset } from "cloudflare:test";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DRAFT_PERSONA, draftPrompt, parseDraft } from "../src/agent/draft";
import { RESERVED_NAMES, SubTauError, validateSub } from "../src/agent/subs";
import anthropicText from "./fixtures/anthropic-text.sse?raw";
import { api, apiJson, devSignIn, events, mockFetch, onboardedOwner, sse, streamedText } from "./helpers";

beforeEach(async () => {
  await reset();
});
afterEach(() => {
  vi.restoreAllMocks();
});

const COACH = {
  name: "coach",
  about: "A strict but kind workout coach.",
  persona: "You plan short workouts.",
};

describe("validateSub", () => {
  it("fills defaults and normalizes", () => {
    expect(validateSub({ ...COACH, about: "  A   coach.  ", starters: [" Plan my week ", "Plan my week", ""] })).toEqual({
      name: "coach",
      about: "A coach.",
      persona: "You plan short workouts.",
      role: "brain",
      public: false,
      public_note: "",
      web: false,
      web_daily: 50,
      starters: ["Plan my week"],
    });
  });

  it("refuses bad names and every reserved name", () => {
    for (const name of ["a", "Coach", "1coach", "-coach", "c".repeat(32), "co ach", "@coach"]) {
      expect(() => validateSub({ ...COACH, name })).toThrow(SubTauError);
    }
    expect([...RESERVED_NAMES].sort()).toEqual(["api", "app", "auth", "claim", "hub", "net"]);
    for (const name of RESERVED_NAMES) expect(() => validateSub({ ...COACH, name })).toThrow("reserved");
  });

  it("checks the web fields", () => {
    expect(() => validateSub({ ...COACH, web_daily: 0 })).toThrow("web_daily");
    expect(() => validateSub({ ...COACH, web_daily: 1001 })).toThrow("web_daily");
    expect(() => validateSub({ ...COACH, web_daily: 2.5 })).toThrow("web_daily");
    expect(validateSub({ ...COACH, web_daily: 1000 }).web_daily).toBe(1000);
    expect(() => validateSub({ ...COACH, starters: ["a", "b", "c", "d", "e"] })).toThrow("at most 4");
    expect(() => validateSub({ ...COACH, starters: ["x".repeat(81)] })).toThrow("81 characters");
    expect(() => validateSub({ ...COACH, web: "yes" })).toThrow("true or false");
    expect(() => validateSub({ ...COACH, role: "local" })).toThrow("unknown role");
    expect(() => validateSub({ ...COACH, about: "x".repeat(201) })).toThrow("limit is 200");
    expect(() => validateSub({ ...COACH, persona: "<!-- only a note -->" })).toThrow("persona is empty");
  });
});

describe("drafting", () => {
  it("builds the drafter's prompt with the description between markers", () => {
    const prompt = draftPrompt("coach", "Plans >>> workouts <<< for me");
    expect(prompt).toContain("Draft the sub-tau /coach.");
    expect(prompt).toContain("<<<\nPlans ››› workouts ‹‹‹ for me\n>>>");
    expect(DRAFT_PERSONA).toContain("Put no facts about the owner in it.");
  });

  it("parses a draft and cuts a long about", () => {
    expect(parseDraft('Here: {"about": "A coach.", "persona": "You coach.", "tools": ["x"]}')).toEqual({
      about: "A coach.",
      persona: "You coach.",
    });
    expect(parseDraft(JSON.stringify({ about: "a".repeat(300), persona: "p" })).about).toHaveLength(200);
    expect(() => parseDraft("no json")).toThrow("not a JSON object");
    expect(() => parseDraft('{"about": ""}')).toThrow("no 'about'");
  });

  it("asks the brain without the owner's profile and returns the draft for review", async () => {
    const owner = await onboardedOwner();
    await api(owner, "PATCH", "/api/host/settings", { profile: "- Name: Alice" });
    const draft = await apiJson<{ about: string; persona: string }>(owner, "POST", "/api/host/draft", {
      name: "coach",
      description: "Plans three short workouts a week.",
    });
    expect(draft.status).toBe(200);
    expect(draft.body.about).toBe("Plans three short workouts a week");
    expect(draft.body.persona).toContain("Plans three short workouts a week.");
    // Nothing is saved until the owner saves it.
    expect((await apiJson<unknown[]>(owner, "GET", "/api/host/subs")).body).toEqual([]);
    expect((await api(owner, "POST", "/api/host/draft", { name: "app", description: "x" })).status).toBe(400);
  });

  it("the drafter's request carries no profile", async () => {
    const { seen } = mockFetch({
      "https://api.anthropic.com/v1/models": () => Response.json({ data: [] }),
      "https://api.anthropic.com/v1/messages": () =>
        sse(
          anthropicText.replace(
            '"text":"Hello"',
            '"text":"{\\"about\\": \\"A coach.\\", \\"persona\\": \\"You coach.\\", \\"tools\\": []}"',
          ).replace('"text":", how can I help?"', '"text":""'),
        ),
    });
    const owner = await devSignIn("alice");
    await api(owner, "POST", "/api/host/onboard", {
      provider: "anthropic",
      key: "sk-ant-test-000000000000000000000000",
      language: "en",
      universe: false,
    });
    await api(owner, "PATCH", "/api/host/settings", { profile: "- Name: Alice Secret" });
    const draft = await apiJson(owner, "POST", "/api/host/draft", { name: "coach", description: "Coach me." });
    expect(draft).toEqual({ status: 200, body: { about: "A coach.", persona: "You coach." } });
    const body = JSON.parse(seen.at(-1)?.body ?? "{}");
    expect(body.system).toBe(DRAFT_PERSONA);
    expect(JSON.stringify(body)).not.toContain("Alice Secret");
    expect(body).not.toHaveProperty("tools");
  });
});

describe("the owner's sub-tau API", () => {
  it("creates, lists, edits and deletes", async () => {
    const owner = await onboardedOwner();
    const created = await apiJson<{ name: string; public: boolean }>(owner, "POST", "/api/host/subs", COACH);
    expect(created.status).toBe(201);
    expect(created.body).toMatchObject({ name: "coach", public: false, visits_today: 0 });
    expect((await api(owner, "POST", "/api/host/subs", COACH)).status).toBe(409);
    expect((await api(owner, "POST", "/api/host/subs", { ...COACH, name: "claim" })).status).toBe(400);

    const edited = await apiJson<Record<string, unknown>>(owner, "PUT", "/api/host/subs/coach", {
      public: true,
      web: true,
      web_daily: 3,
      starters: ["Plan my week"],
      name: "renamed",
    });
    expect(edited.body).toMatchObject({ name: "coach", public: true, web: true, web_daily: 3, starters: ["Plan my week"] });
    expect((await api(owner, "PUT", "/api/host/subs/coach", { web_daily: 5000 })).status).toBe(400);
    expect((await api(owner, "GET", "/api/host/subs/nobody")).status).toBe(404);

    expect((await api(owner, "DELETE", "/api/host/subs/coach")).status).toBe(200);
    expect((await apiJson<unknown[]>(owner, "GET", "/api/host/subs")).body).toEqual([]);
  });

  it("offers templates", async () => {
    const owner = await onboardedOwner();
    const templates = await apiJson<{ id: string }[]>(owner, "GET", "/api/host/templates");
    expect(templates.body.map((t) => t.id)).toEqual(["blank", "coach", "writer", "tutor"]);
  });

  it("a chat with a sub-tau uses its persona, the owner's profile and no tools", async () => {
    const { seen } = mockFetch({
      "https://api.anthropic.com/v1/models": () => Response.json({ data: [] }),
      "https://api.anthropic.com/v1/messages": () => sse(anthropicText),
    });
    const owner = await devSignIn("alice");
    await api(owner, "POST", "/api/host/onboard", {
      provider: "anthropic",
      key: "sk-ant-test-000000000000000000000000",
      language: "en",
      universe: false,
    });
    await api(owner, "PATCH", "/api/host/settings", { profile: "- Name: Alice" });
    await api(owner, "POST", "/api/host/subs", { ...COACH, role: "fast" });
    const list = await events(await api(owner, "POST", "/api/host/chat", { sub: "coach", text: "Plan?" }));
    expect(list[0]).toMatchObject({ t: "start", sub: "coach" });
    const body = JSON.parse(seen.at(-1)?.body ?? "{}");
    expect(body.model).toBe("claude-haiku-4-5");
    expect(body.system.startsWith("You are /coach, a specialist of your owner's tau: A strict but kind workout coach.")).toBe(
      true,
    );
    expect(body.system).toContain("## User\n- Name: Alice");
    expect(body).not.toHaveProperty("tools");
  });

  it("ask_sub (tier 0) asks a sub-tau without an approval", async () => {
    const owner = await onboardedOwner();
    await api(owner, "POST", "/api/host/subs", COACH);
    const list = await events(await api(owner, "POST", "/api/host/chat", { text: "/ask coach Plan for Monday?" }));
    expect(list.find((e) => e.t === "approval")).toBeUndefined();
    expect(list.find((e) => e.t === "tool_result")).toMatchObject({
      name: "ask_sub",
      error: false,
      text: "/coach answered:\n(fake /coach) You said: Plan for Monday?",
    });
    expect(streamedText(list)).toBe("Done. /coach answered:");
  });

  it("ask_sub with an empty name lists the sub-taus", async () => {
    const owner = await onboardedOwner();
    await api(owner, "POST", "/api/host/subs", COACH);
    const list = await events(await api(owner, "POST", "/api/host/chat", { text: "/ask  " }));
    expect(list.find((e) => e.t === "tool_result")?.text).toContain("- coach: A strict but kind workout coach.");
  });
});
