/**
 * The agent loop with a scripted provider and a scripted approver (the tier gate's only
 * way to "approved" in tests). Nothing here talks to a network.
 */

import { describe, expect, it } from "vitest";
import {
  type Approver,
  type Decision,
  normalizeHistory,
  runTurn,
  type TurnEvent,
  type TurnHooks,
} from "../src/agent/loop";
import type { HostTool } from "../src/agent/tools";
import type { Message, ModelRequest, ModelResponse, Provider, ToolUseBlock, Usage } from "../src/providers/types";

const USAGE: Usage = { input: 10, output: 5, cacheRead: 0, cacheWrite: 0 };

/** A provider that answers from a script, one response per call, and records the requests. */
class ScriptedProvider implements Provider {
  readonly name = "fake" as const;
  readonly requests: ModelRequest[] = [];
  constructor(private readonly script: ModelResponse[]) {}
  async complete(request: ModelRequest, onText?: (d: string) => void): Promise<ModelResponse> {
    this.requests.push({ ...request, messages: structuredClone(request.messages) });
    const next = this.script.shift();
    if (next === undefined) throw new Error("the script ran out");
    for (const block of next.content) if (block.type === "text") onText?.(block.text);
    return next;
  }
}

/** An approver that answers from a list and records what it was asked. */
class ScriptedApprover implements Approver {
  readonly asked: ToolUseBlock[] = [];
  constructor(private readonly answers: Decision[]) {}
  async request(call: ToolUseBlock): Promise<Decision> {
    this.asked.push(call);
    return this.answers.shift() ?? "pending";
  }
}

function text(value: string): ModelResponse {
  return { content: [{ type: "text", text: value }], stop: "end", usage: USAGE };
}

function calls(...blocks: [string, string, Record<string, unknown>][]): ModelResponse {
  return {
    content: blocks.map(([id, name, input]) => ({ type: "tool_use", id, name, input })),
    stop: "tool_use",
    usage: USAGE,
  };
}

function tools(ran: string[]): HostTool[] {
  return [
    {
      spec: { name: "ask_sub", description: "ask", parameters: { type: "object" } },
      tier: 0,
      run: async (input) => {
        ran.push(`ask_sub:${String(input.name)}`);
        return { text: `/${String(input.name)} answered: fine` };
      },
    },
    {
      spec: { name: "create_sub", description: "create", parameters: { type: "object" } },
      tier: 2,
      effect: "Creates a new sub-tau.",
      run: async (input) => {
        ran.push(`create_sub:${String(input.name)}`);
        return { text: `Created /${String(input.name)}.` };
      },
    },
  ];
}

function hooks(allowModel = () => true) {
  const events: TurnEvent[] = [];
  const stored: Message[] = [];
  const usage: Usage[] = [];
  const h: TurnHooks = {
    emit: (event) => events.push(event),
    append: (message) => stored.push(structuredClone(message)),
    usage: (u) => usage.push(u),
    mayCallModel: allowModel,
  };
  return { h, events, stored, usage };
}

const USER: Message = { role: "user", content: [{ type: "text", text: "Hello" }] };

describe("runTurn", () => {
  it("streams text and stores the answer", async () => {
    const provider = new ScriptedProvider([text("Hi there")]);
    const { h, events, stored, usage } = hooks();
    const outcome = await runTurn({ provider, model: "m", system: "s", history: [USER], tools: [], approver: new ScriptedApprover([]), hooks: h });
    expect(outcome).toEqual({ status: "done", stop: "end" });
    expect(events).toEqual([{ t: "text", d: "Hi there" }]);
    expect(stored).toEqual([{ role: "assistant", content: [{ type: "text", text: "Hi there" }] }]);
    expect(usage).toEqual([USAGE]);
  });

  it("runs a tier-0 tool without asking and sends its result back", async () => {
    const ran: string[] = [];
    const provider = new ScriptedProvider([calls(["c1", "ask_sub", { name: "coach" }]), text("The coach says fine.")]);
    const approver = new ScriptedApprover([]);
    const { h, stored } = hooks();
    const outcome = await runTurn({ provider, model: "m", system: "s", history: [USER], tools: tools(ran), approver, hooks: h });
    expect(outcome).toEqual({ status: "done", stop: "end" });
    expect(ran).toEqual(["ask_sub:coach"]);
    expect(approver.asked).toEqual([]);
    expect(stored[1]).toEqual({
      role: "user",
      content: [{ type: "tool_result", id: "c1", name: "ask_sub", text: "/coach answered: fine", error: false }],
    });
    expect(provider.requests[1]?.messages.at(-1)).toEqual(stored[1]);
  });

  it("runs a tier-2 tool only when the approver says approved", async () => {
    const ran: string[] = [];
    const provider = new ScriptedProvider([calls(["c1", "create_sub", { name: "coach" }]), text("Done.")]);
    const approver = new ScriptedApprover(["approved"]);
    const { h } = hooks();
    await runTurn({ provider, model: "m", system: "s", history: [USER], tools: tools(ran), approver, hooks: h });
    expect(approver.asked.map((c) => c.id)).toEqual(["c1"]);
    expect(ran).toEqual(["create_sub:coach"]);
  });

  it("refuses a denied tier-2 call and tells the model", async () => {
    const ran: string[] = [];
    const provider = new ScriptedProvider([calls(["c1", "create_sub", { name: "coach" }]), text("Understood.")]);
    const { h, stored } = hooks();
    await runTurn({ provider, model: "m", system: "s", history: [USER], tools: tools(ran), approver: new ScriptedApprover(["denied"]), hooks: h });
    expect(ran).toEqual([]);
    const result = stored[1]?.content[0];
    expect(result).toMatchObject({ type: "tool_result", id: "c1", error: true });
    expect(result?.type === "tool_result" && result.text).toContain("did not approve create_sub");
  });

  it("pauses on a pending approval, after answering the calls before it", async () => {
    const ran: string[] = [];
    const provider = new ScriptedProvider([
      calls(["c1", "ask_sub", { name: "coach" }], ["c2", "create_sub", { name: "writer" }], ["c3", "ask_sub", { name: "tutor" }]),
    ]);
    const { h, stored } = hooks();
    const outcome = await runTurn({ provider, model: "m", system: "s", history: [USER], tools: tools(ran), approver: new ScriptedApprover(["pending"]), hooks: h });
    expect(outcome.status).toBe("paused");
    if (outcome.status !== "paused") return;
    expect(ran).toEqual(["ask_sub:coach"]);
    expect(outcome.paused.queue.map((c) => c.id)).toEqual(["c2", "c3"]);
    expect(outcome.paused.results.map((r) => r.id)).toEqual(["c1"]);
    expect(outcome.paused.steps).toBe(1);
    // Only the assistant's message is stored; the results wait for the owner's answer.
    expect(stored).toHaveLength(1);
    expect(provider.requests).toHaveLength(1);
  });

  it("resumes an approved pause: runs the call, the rest of the queue, then the model", async () => {
    const ran: string[] = [];
    const paused = {
      queue: [
        { type: "tool_use" as const, id: "c2", name: "create_sub", input: { name: "writer" } },
        { type: "tool_use" as const, id: "c3", name: "ask_sub", input: { name: "tutor" } },
      ],
      results: [{ type: "tool_result" as const, id: "c1", name: "ask_sub", text: "fine", error: false }],
      steps: 1,
    };
    const provider = new ScriptedProvider([text("All done.")]);
    const approver = new ScriptedApprover([]);
    const { h, stored } = hooks();
    const outcome = await runTurn({
      provider,
      model: "m",
      system: "s",
      history: [USER],
      tools: tools(ran),
      approver,
      hooks: h,
      resume: { paused, resolution: "approved" },
    });
    expect(outcome).toEqual({ status: "done", stop: "end" });
    expect(ran).toEqual(["create_sub:writer", "ask_sub:tutor"]);
    expect(approver.asked).toEqual([]); // the owner already answered this one
    expect(stored[0]?.content.map((b) => (b.type === "tool_result" ? b.id : ""))).toEqual(["c1", "c2", "c3"]);
  });

  it("resumes an expired pause as a refusal", async () => {
    const ran: string[] = [];
    const paused = {
      queue: [{ type: "tool_use" as const, id: "c2", name: "create_sub", input: { name: "writer" } }],
      results: [],
      steps: 1,
    };
    const { h, stored } = hooks();
    await runTurn({
      provider: new ScriptedProvider([text("OK.")]),
      model: "m",
      system: "s",
      history: [USER],
      tools: tools(ran),
      approver: new ScriptedApprover([]),
      hooks: h,
      resume: { paused, resolution: "expired" },
    });
    expect(ran).toEqual([]);
    const result = stored[0]?.content[0];
    expect(result?.type === "tool_result" && result.text).toContain("within 10 minutes");
  });

  it("stops at the step limit and when the budget is used up mid-turn", async () => {
    const endless = Array.from({ length: 5 }, (_, i) => calls([`c${i}`, "ask_sub", { name: "coach" }]));
    const limited = await runTurn({
      provider: new ScriptedProvider([...endless]),
      model: "m",
      system: "s",
      history: [USER],
      tools: tools([]),
      approver: new ScriptedApprover([]),
      hooks: hooks().h,
      maxSteps: 3,
    });
    expect(limited).toEqual({ status: "done", stop: "max_steps" });

    let calls_ = 0;
    const { h, events } = hooks(() => ++calls_ < 2);
    const broke = await runTurn({
      provider: new ScriptedProvider([...endless]),
      model: "m",
      system: "s",
      history: [USER],
      tools: tools([]),
      approver: new ScriptedApprover([]),
      hooks: h,
    });
    expect(broke).toEqual({ status: "done", stop: "budget" });
    expect(events.at(-1)).toEqual({ t: "notice", code: "budget" });
  });

  it("answers an unknown tool with an error instead of failing", async () => {
    const { h, stored } = hooks();
    await runTurn({
      provider: new ScriptedProvider([calls(["c1", "rm_rf", {}]), text("Sorry.")]),
      model: "m",
      system: "s",
      history: [USER],
      tools: tools([]),
      approver: new ScriptedApprover([]),
      hooks: h,
    });
    expect(stored[1]?.content[0]).toMatchObject({ type: "tool_result", error: true, text: "Unknown tool rm_rf." });
  });
});

describe("normalizeHistory", () => {
  const call = { type: "tool_use" as const, id: "c1", name: "ask_sub", input: {} };
  const result = { type: "tool_result" as const, id: "c1", name: "ask_sub", text: "ok" };

  it("merges roles, starts at a user text and fills calls left without an answer", () => {
    const out = normalizeHistory([
      { role: "user", content: [result] },
      { role: "assistant", content: [{ type: "text", text: "orphan" }] },
      { role: "user", content: [{ type: "text", text: "a" }] },
      { role: "user", content: [{ type: "text", text: "b" }] },
      { role: "assistant", content: [call] },
      { role: "user", content: [{ type: "text", text: "next" }] },
    ]);
    expect(out.map((m) => m.role)).toEqual(["user", "assistant", "user"]);
    expect(out[0]?.content).toHaveLength(2);
    expect(out[2]?.content[0]).toMatchObject({ type: "tool_result", id: "c1", error: true });
    expect(out[2]?.content[1]).toEqual({ type: "text", text: "next" });
  });

  it("keeps a paused call open when asked", () => {
    const out = normalizeHistory(
      [
        { role: "user", content: [{ type: "text", text: "a" }] },
        { role: "assistant", content: [call] },
      ],
      true,
    );
    expect(out).toHaveLength(2);
    expect(out[1]?.content).toEqual([call]);
  });
});
