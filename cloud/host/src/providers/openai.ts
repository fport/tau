/**
 * OpenAI Chat Completions over plain fetch, streamed (server-sent events).
 *
 * Request: POST /v1/chat/completions with a bearer key, the system prompt as the first
 * message, tool calls as `tool_calls` and tool answers as `role: "tool"` messages,
 * `stream: true` and `stream_options.include_usage` (the last chunk carries the usage).
 * Stream: `choices[0].delta` carries text (`content`) and tool calls in pieces (by `index`:
 * `id` and `function.name` first, then `function.arguments` fragments); `finish_reason` ends
 * the choice; `data: [DONE]` ends the stream. `prompt_tokens` include the cached ones
 * (`prompt_tokens_details.cached_tokens`), which are subtracted from `input`.
 */

import { sseEvents } from "./sse";
import {
  errorFromResponse,
  type Message,
  type ModelRequest,
  type ModelResponse,
  type OnText,
  parseArguments,
  type Provider,
  ProviderError,
  redact,
  CALL_TIMEOUT_MS,
  type StopReason,
  type TextBlock,
  type ToolUseBlock,
  type Usage,
} from "./types";

export const OPENAI_URL = "https://api.openai.com/v1/chat/completions";
export const OPENAI_MODELS_URL = "https://api.openai.com/v1/models";

type Json = Record<string, unknown>;

export function toOpenAIMessages(system: string, messages: Message[]): Json[] {
  const out: Json[] = [{ role: "system", content: system }];
  for (const message of messages) {
    if (message.role === "assistant") {
      const text = message.content
        .filter((b): b is TextBlock => b.type === "text")
        .map((b) => b.text)
        .join("");
      const calls = message.content
        .filter((b): b is ToolUseBlock => b.type === "tool_use")
        .map((b) => ({
          id: b.id,
          type: "function",
          function: { name: b.name, arguments: JSON.stringify(b.input) },
        }));
      if (!text && calls.length === 0) continue;
      out.push({
        role: "assistant",
        content: text || null,
        ...(calls.length > 0 ? { tool_calls: calls } : {}),
      });
      continue;
    }
    // A user message: tool answers first (they must follow the assistant's calls), then text.
    for (const block of message.content) {
      if (block.type === "tool_result") {
        out.push({ role: "tool", tool_call_id: block.id, content: block.text });
      }
    }
    const text = message.content
      .filter((b): b is TextBlock => b.type === "text")
      .map((b) => b.text)
      .join("\n\n");
    if (text) out.push({ role: "user", content: text });
  }
  return out;
}

export function openAIBody(request: ModelRequest): Json {
  return {
    model: request.model,
    messages: toOpenAIMessages(request.system, request.messages),
    max_completion_tokens: request.maxTokens,
    ...(request.tools.length > 0
      ? {
          tools: request.tools.map((tool) => ({
            type: "function",
            function: {
              name: tool.name,
              description: tool.description,
              parameters: tool.parameters,
            },
          })),
        }
      : {}),
    stream: true,
    stream_options: { include_usage: true },
  };
}

function stopOf(reason: unknown): StopReason {
  if (reason === "stop") return "end";
  if (reason === "tool_calls" || reason === "function_call") return "tool_use";
  if (reason === "length") return "max_tokens";
  return "other";
}

function num(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

export class OpenAIProvider implements Provider {
  readonly name = "openai" as const;

  constructor(
    private readonly key: string,
    private readonly url: string = OPENAI_URL,
  ) {}

  async complete(request: ModelRequest, onText?: OnText): Promise<ModelResponse> {
    let response: Response;
    try {
      response = await fetch(this.url, {
        method: "POST",
        headers: { "content-type": "application/json", authorization: `Bearer ${this.key}` },
        body: JSON.stringify(openAIBody(request)),
        signal: request.signal ?? AbortSignal.timeout(CALL_TIMEOUT_MS),
      });
    } catch (err) {
      throw new ProviderError("unavailable", 0, redact(String(err), this.key));
    }
    if (!response.ok || response.body === null) throw await errorFromResponse(response, this.key);

    const usage: Usage = { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 };
    let text = "";
    const calls = new Map<number, { id: string; name: string; args: string }>();
    let stop: StopReason = "other";
    for await (const { data } of sseEvents(response.body)) {
      if (data.trim() === "[DONE]") break;
      let chunk: Json;
      try {
        chunk = JSON.parse(data) as Json;
      } catch {
        continue;
      }
      if (typeof chunk.error === "object" && chunk.error !== null) {
        const message = String((chunk.error as Json).message ?? "stream error");
        throw new ProviderError("other", 0, redact(message, this.key));
      }
      const choices = Array.isArray(chunk.choices) ? (chunk.choices as Json[]) : [];
      const choice = choices[0];
      if (choice !== undefined) {
        const delta = (choice.delta ?? {}) as Json;
        if (typeof delta.content === "string" && delta.content) {
          text += delta.content;
          onText?.(delta.content);
        }
        if (Array.isArray(delta.tool_calls)) {
          for (const raw of delta.tool_calls as Json[]) {
            const index = num(raw.index);
            const fn = (raw.function ?? {}) as Json;
            const call = calls.get(index) ?? { id: "", name: "", args: "" };
            if (typeof raw.id === "string" && raw.id) call.id = raw.id;
            if (typeof fn.name === "string" && fn.name) call.name += fn.name;
            if (typeof fn.arguments === "string") call.args += fn.arguments;
            calls.set(index, call);
          }
        }
        if (choice.finish_reason !== undefined && choice.finish_reason !== null) {
          stop = stopOf(choice.finish_reason);
        }
      }
      if (typeof chunk.usage === "object" && chunk.usage !== null) {
        const u = chunk.usage as Json;
        const cached = num(((u.prompt_tokens_details ?? {}) as Json).cached_tokens);
        usage.input = Math.max(num(u.prompt_tokens) - cached, 0);
        usage.cacheRead = cached;
        usage.output = num(u.completion_tokens);
      }
    }

    const content: (TextBlock | ToolUseBlock)[] = [];
    if (text) content.push({ type: "text", text });
    for (const index of [...calls.keys()].sort((a, b) => a - b)) {
      const call = calls.get(index);
      if (call === undefined || !call.name) continue;
      content.push({
        type: "tool_use",
        id: call.id || `call_${index}`,
        name: call.name,
        input: parseArguments(call.args),
      });
    }
    return { content, stop, usage };
  }
}

/** One small, free request that proves a key: the models list. */
export async function checkOpenAIKey(key: string): Promise<Response> {
  return fetch(OPENAI_MODELS_URL, { headers: { authorization: `Bearer ${key}` } });
}
