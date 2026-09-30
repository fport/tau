/**
 * The agent loop of a hosted tau: model call → tool calls → model call …, until the model
 * answers without tools, the step limit is reached, the budget is used up, or a tier-2 call
 * waits for the owner.
 *
 * The loop is pure: the provider, the tools, the approver and the hooks that persist and
 * stream are passed in, so the tests drive it with fakes. The tier gate is here and nowhere
 * else: a tool of tier 2 runs only when the approver returns "approved" for that very call.
 * tau-host's approver (the Tau object) never does that by itself: it stores an approval card
 * and returns "pending", which pauses the turn; the owner's decision resumes it (`resume`).
 *
 * Tool calls of one assistant message are answered in order, and all their results go back
 * in one user message. A pause keeps the calls still to answer (`queue`, the first one waits)
 * and the results already given, so the resumed turn continues exactly there.
 */

import type {
  Message,
  Provider,
  StopReason,
  ToolResultBlock,
  ToolUseBlock,
  Usage,
} from "../providers/types";
import { type HostTool, refusal } from "./tools";

export const MAX_STEPS = 8;
export const MAX_TOKENS = 2048;
export const TOOL_RESULT_LIMIT = 8000;

export type Decision = "approved" | "denied" | "pending";

export interface Approver {
  /** Asks the owner about one tier-2 call. */
  request(call: ToolUseBlock, tool: HostTool): Promise<Decision>;
}

/** What the loop streams to the app (NDJSON, one event per line). */
export type TurnEvent =
  | { t: "text"; d: string }
  | { t: "tool"; id: string; name: string; input: Record<string, unknown>; tier: number }
  | { t: "tool_result"; id: string; name: string; text: string; error: boolean }
  | { t: "notice"; code: "max_steps" | "budget" | "max_tokens" | "stopped" };

export interface TurnHooks {
  emit(event: TurnEvent): void;
  /** Persists a finished message (the assistant's answer, or the tool results). */
  append(message: Message): void;
  /** Records one model call's usage. */
  usage(usage: Usage): void;
  /** Asked before every model call after the first: false ends the turn (budget used up). */
  mayCallModel(): boolean;
}

export interface PausedTurn {
  queue: ToolUseBlock[];
  results: ToolResultBlock[];
  steps: number;
}

export type Resolution = "approved" | "denied" | "expired";

export interface TurnInput {
  provider: Provider;
  model: string;
  system: string;
  /** The conversation so far: ending with the new user message, or with the paused call. */
  history: Message[];
  tools: HostTool[];
  approver: Approver;
  hooks: TurnHooks;
  resume?: { paused: PausedTurn; resolution: Resolution };
  maxSteps?: number;
  maxTokens?: number;
  signal?: AbortSignal;
}

export type TurnOutcome =
  | { status: "done"; stop: StopReason | "max_steps" | "budget" }
  | { status: "paused"; paused: PausedTurn };

type Answered = { done: true; results: ToolResultBlock[] } | { done: false; paused: Omit<PausedTurn, "steps"> };

function clip(text: string): string {
  return text.length > TOOL_RESULT_LIMIT ? `${text.slice(0, TOOL_RESULT_LIMIT - 1)}…` : text;
}

async function runTool(tool: HostTool, call: ToolUseBlock): Promise<ToolResultBlock> {
  try {
    const out = await tool.run(call.input);
    return { type: "tool_result", id: call.id, name: call.name, text: clip(out.text), error: out.error ?? false };
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return { type: "tool_result", id: call.id, name: call.name, text: `The tool failed: ${message}`, error: true };
  }
}

async function answer(
  input: TurnInput,
  queue: ToolUseBlock[],
  given: ToolResultBlock[],
  first?: Resolution,
): Promise<Answered> {
  const byName = new Map(input.tools.map((tool) => [tool.spec.name, tool]));
  const results = [...given];
  for (let i = 0; i < queue.length; i++) {
    const call = queue[i] as ToolUseBlock;
    const tool = byName.get(call.name);
    let result: ToolResultBlock;
    if (tool === undefined) {
      result = { type: "tool_result", id: call.id, name: call.name, text: `Unknown tool ${call.name}.`, error: true };
    } else if (tool.tier >= 2) {
      const decision: Decision | Resolution = i === 0 && first !== undefined ? first : await input.approver.request(call, tool);
      if (decision === "pending") return { done: false, paused: { queue: queue.slice(i), results } };
      result =
        decision === "approved"
          ? await runTool(tool, call)
          : { type: "tool_result", id: call.id, name: call.name, text: refusal(call.name, decision), error: true };
    } else {
      result = await runTool(tool, call);
    }
    input.hooks.emit({ t: "tool_result", id: result.id, name: result.name, text: result.text, error: result.error ?? false });
    results.push(result);
  }
  return { done: true, results };
}

export async function runTurn(input: TurnInput): Promise<TurnOutcome> {
  const { hooks } = input;
  const maxSteps = input.maxSteps ?? MAX_STEPS;
  const messages = [...input.history];
  const specs = input.tools.map((tool) => tool.spec);
  const tierOf = new Map(input.tools.map((tool) => [tool.spec.name, tool.tier]));
  let steps = input.resume?.paused.steps ?? 0;

  if (input.resume) {
    const { paused, resolution } = input.resume;
    const answered = await answer(input, paused.queue, paused.results, resolution);
    if (!answered.done) return { status: "paused", paused: { ...answered.paused, steps } };
    const results: Message = { role: "user", content: answered.results };
    messages.push(results);
    hooks.append(results);
  }

  for (;;) {
    if (steps >= maxSteps) {
      hooks.emit({ t: "notice", code: "max_steps" });
      return { status: "done", stop: "max_steps" };
    }
    if (steps > 0 && !hooks.mayCallModel()) {
      hooks.emit({ t: "notice", code: "budget" });
      return { status: "done", stop: "budget" };
    }
    steps++;
    const response = await input.provider.complete(
      {
        model: input.model,
        system: input.system,
        messages,
        tools: specs,
        maxTokens: input.maxTokens ?? MAX_TOKENS,
        signal: input.signal,
      },
      (delta) => hooks.emit({ t: "text", d: delta }),
    );
    hooks.usage(response.usage);
    if (response.content.length === 0) {
      if (response.stop === "max_tokens") hooks.emit({ t: "notice", code: "max_tokens" });
      return { status: "done", stop: response.stop };
    }
    const assistant: Message = { role: "assistant", content: response.content };
    messages.push(assistant);
    hooks.append(assistant);

    const calls = response.content.filter((block): block is ToolUseBlock => block.type === "tool_use");
    if (calls.length === 0) {
      if (response.stop === "max_tokens") hooks.emit({ t: "notice", code: "max_tokens" });
      return { status: "done", stop: response.stop };
    }
    for (const call of calls) {
      hooks.emit({ t: "tool", id: call.id, name: call.name, input: call.input, tier: tierOf.get(call.name) ?? 0 });
    }
    const answered = await answer(input, calls, []);
    if (!answered.done) return { status: "paused", paused: { ...answered.paused, steps } };
    const results: Message = { role: "user", content: answered.results };
    messages.push(results);
    hooks.append(results);
  }
}

function merge(messages: readonly Message[]): Message[] {
  const merged: Message[] = [];
  for (const message of messages) {
    if (message.content.length === 0) continue;
    const last = merged.at(-1);
    if (last && last.role === message.role) last.content = [...last.content, ...message.content];
    else merged.push({ role: message.role, content: [...message.content] });
  }
  return merged;
}

/**
 * A stored conversation made safe for any provider: consecutive messages of one role are
 * merged, it starts with a user message that has text, every tool call has an answer (a call
 * left without one, by a turn that broke off, gets an error answer), and no answer is left
 * without its call. With `openTail`, the calls of a final assistant message stay unanswered:
 * that is a paused turn about to be resumed.
 */
export function normalizeHistory(stored: readonly Message[], openTail = false): Message[] {
  const merged = merge(stored);
  const start = merged.findIndex((m) => m.role === "user" && m.content.some((b) => b.type === "text"));
  if (start === -1) return [];
  const out = merged.slice(start);
  for (let i = 0; i < out.length; i++) {
    const message = out[i] as Message;
    if (message.role !== "assistant") continue;
    if (openTail && i === out.length - 1) continue;
    const calls = message.content.filter((b): b is ToolUseBlock => b.type === "tool_use");
    const next = out[i + 1];
    const answered = new Set(
      next?.role === "user" ? next.content.filter((b) => b.type === "tool_result").map((b) => b.id) : [],
    );
    const missing = calls.filter((call) => !answered.has(call.id));
    if (missing.length === 0) continue;
    const fill: ToolResultBlock[] = missing.map((call) => ({
      type: "tool_result",
      id: call.id,
      name: call.name,
      text: "No result: the turn broke off before this call was answered.",
      error: true,
    }));
    if (next?.role === "user") next.content = [...fill, ...next.content];
    else out.splice(i + 1, 0, { role: "user", content: fill });
  }
  // Answers whose call is not in the message before them are dropped.
  for (let i = 0; i < out.length; i++) {
    const message = out[i] as Message;
    if (message.role !== "user") continue;
    const before = out[i - 1];
    const ids = new Set(
      before?.role === "assistant" ? before.content.filter((b) => b.type === "tool_use").map((b) => b.id) : [],
    );
    message.content = message.content.filter((b) => b.type !== "tool_result" || ids.has(b.id));
  }
  return merge(out);
}
