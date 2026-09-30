/**
 * The scripted `fake` provider: no key, no network, no cost. Development (`wrangler dev`
 * with FAKE_PROVIDER=1) and tests only. It answers from the last message, so a person
 * trying the app can drive every path by hand:
 *
 * - after tool results: "Done." and the first line of each result;
 * - a drafting request: a JSON draft built from the description;
 * - a visitor turn (the `[tau web]` frame): an echo of the visitor's message, as the sub-tau;
 * - `/create NAME ABOUT` (when `create_sub` is offered): a `create_sub` call (tier 2);
 * - `/ask NAME QUESTION` (when `ask_sub` is offered): an `ask_sub` call;
 * - anything else: an echo, streamed word by word.
 *
 * Usage is counted as one token per four characters, so budgets and the spend view have
 * numbers to show; the fake models have no price, so the cost stays zero.
 */

import type { Message, ModelRequest, ModelResponse, OnText, Provider, ToolUseBlock } from "./types";

/** The first line of tau-host's drafting prompt; the fake recognizes drafting by it. */
export const FAKE_DRAFT_MARKER = "You draft sub-taus.";

function lastText(messages: Message[]): string {
  for (let i = messages.length - 1; i >= 0; i--) {
    const message = messages[i];
    if (message?.role !== "user") continue;
    const texts = message.content.filter((b) => b.type === "text").map((b) => b.text);
    if (texts.length > 0) return texts.join("\n");
    return "";
  }
  return "";
}

function between(text: string, start: string, end: string): string | null {
  const from = text.indexOf(start);
  const to = text.indexOf(end, from + start.length);
  if (from === -1 || to === -1) return null;
  return text.slice(from + start.length, to).trim();
}

function tokens(text: string): number {
  return Math.ceil(text.length / 4);
}

let counter = 0;

export class FakeProvider implements Provider {
  readonly name = "fake" as const;

  async complete(request: ModelRequest, onText?: OnText): Promise<ModelResponse> {
    const input =
      tokens(request.system) +
      request.messages.reduce(
        (sum, m) => sum + m.content.reduce((s, b) => s + tokens(JSON.stringify(b)), 0),
        0,
      );
    const last = request.messages.at(-1);
    const offered = new Set(request.tools.map((tool) => tool.name));

    const reply = (text: string): ModelResponse => {
      const words = text.split(/(?<= )/);
      for (const word of words) onText?.(word);
      return {
        content: [{ type: "text", text }],
        stop: "end",
        usage: { input, output: tokens(text), cacheRead: 0, cacheWrite: 0 },
      };
    };
    const call = (name: string, args: Record<string, unknown>): ModelResponse => {
      const block: ToolUseBlock = { type: "tool_use", id: `fake_${++counter}`, name, input: args };
      return {
        content: [block],
        stop: "tool_use",
        usage: { input, output: tokens(JSON.stringify(args)), cacheRead: 0, cacheWrite: 0 },
      };
    };

    const results = last?.content.filter((b) => b.type === "tool_result") ?? [];
    if (last?.role === "user" && results.length > 0) {
      const lines = results.map((r) => (r.type === "tool_result" ? r.text.split("\n")[0] : ""));
      return reply(`Done. ${lines.join(" ")}`);
    }

    const text = lastText(request.messages);
    if (request.system.startsWith(FAKE_DRAFT_MARKER)) {
      const description = between(text, "<<<", ">>>") ?? text;
      const about = description.split(/[.!?\n]/)[0]?.trim().slice(0, 120) || "A small specialist.";
      return reply(
        JSON.stringify({
          about,
          persona: `You help your owner with this: ${description}\n\nKeep answers short and ask one question when something is unclear.`,
          tools: [],
        }),
      );
    }

    if (text.startsWith("[tau web]")) {
      const message = between(text, "<<<BEGIN MESSAGE>>>", "<<<END MESSAGE>>>") ?? "";
      const sub = /\/([a-z][a-z0-9-]{1,30})/.exec(text)?.[1] ?? "sub";
      return reply(`(fake /${sub}) You said: ${message}`);
    }

    const create = /^\/create\s+([a-z][a-z0-9-]{1,30})\s*(.*)$/s.exec(text.trim());
    if (create && offered.has("create_sub")) {
      const about = create[2]?.trim() || `A specialist named ${create[1]}.`;
      return call("create_sub", {
        name: create[1],
        about,
        persona: `You are a small specialist: ${about} Keep answers short.`,
      });
    }
    const ask = /^\/ask(?:\s+(\S+))?\s*(.*)$/s.exec(text.trim());
    if (ask && offered.has("ask_sub")) {
      return call("ask_sub", { name: ask[1] ?? "", question: ask[2]?.trim() || "Hello?" });
    }

    const sub = /^You are \/([a-z][a-z0-9-]{1,30}),/.exec(request.system)?.[1];
    return reply(`(fake${sub ? ` /${sub}` : ""}) You said: ${text}`);
  }
}
