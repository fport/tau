/**
 * Anthropic Messages API over plain fetch, streamed (server-sent events).
 *
 * Request: POST /v1/messages with `x-api-key`, `anthropic-version: 2023-06-01`, the system
 * prompt, the messages, the tools (`input_schema`) and `stream: true`.
 * Stream: message_start (input usage) → content_block_start/delta/stop (text deltas, tool
 * input as partial JSON) → message_delta (stop reason, output usage) → message_stop.
 * Anthropic reports cached input apart from `input_tokens`, so the usage is taken as it is.
 */

import { sseEvents } from "./sse";
import {
  type Block,
  errorFromResponse,
  type Message,
  type ModelRequest,
  type ModelResponse,
  type OnText,
  parseArguments,
  type Provider,
  ProviderError,
  redact,
  type StopReason,
  type TextBlock,
  type ToolUseBlock,
  type Usage,
} from "./types";

export const ANTHROPIC_URL = "https://api.anthropic.com/v1/messages";
export const ANTHROPIC_MODELS_URL = "https://api.anthropic.com/v1/models?limit=1";
export const ANTHROPIC_VERSION = "2023-06-01";

type Json = Record<string, unknown>;

function blockToApi(block: Block): Json | null {
  switch (block.type) {
    case "text":
      return block.text ? { type: "text", text: block.text } : null;
    case "tool_use":
      return { type: "tool_use", id: block.id, name: block.name, input: block.input };
    case "tool_result":
      return {
        type: "tool_result",
        tool_use_id: block.id,
        content: block.text,
        ...(block.error ? { is_error: true } : {}),
      };
  }
}

export function toAnthropicMessages(messages: Message[]): Json[] {
  const out: Json[] = [];
  for (const message of messages) {
    const content = message.content.map(blockToApi).filter((b): b is Json => b !== null);
    if (content.length > 0) out.push({ role: message.role, content });
  }
  return out;
}

export function anthropicBody(request: ModelRequest): Json {
  return {
    model: request.model,
    max_tokens: request.maxTokens,
    system: request.system,
    messages: toAnthropicMessages(request.messages),
    ...(request.tools.length > 0
      ? {
          tools: request.tools.map((tool) => ({
            name: tool.name,
            description: tool.description,
            input_schema: tool.parameters,
          })),
        }
      : {}),
    stream: true,
  };
}

function stopOf(reason: unknown): StopReason {
  if (reason === "end_turn" || reason === "stop_sequence") return "end";
  if (reason === "tool_use") return "tool_use";
  if (reason === "max_tokens") return "max_tokens";
  return "other";
}

function num(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

export class AnthropicProvider implements Provider {
  readonly name = "anthropic" as const;

  constructor(private readonly key: string) {}

  async complete(request: ModelRequest, onText?: OnText): Promise<ModelResponse> {
    let response: Response;
    try {
      response = await fetch(ANTHROPIC_URL, {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "x-api-key": this.key,
          "anthropic-version": ANTHROPIC_VERSION,
        },
        body: JSON.stringify(anthropicBody(request)),
        signal: request.signal,
      });
    } catch (err) {
      throw new ProviderError("unavailable", 0, redact(String(err), this.key));
    }
    if (!response.ok || response.body === null) throw await errorFromResponse(response, this.key);

    const usage: Usage = { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 };
    const blocks = new Map<number, TextBlock | (ToolUseBlock & { json: string })>();
    let stop: StopReason = "other";
    for await (const { data } of sseEvents(response.body)) {
      let event: Json;
      try {
        event = JSON.parse(data) as Json;
      } catch {
        continue;
      }
      switch (event.type) {
        case "message_start": {
          const u = ((event.message as Json | undefined)?.usage ?? {}) as Json;
          usage.input = num(u.input_tokens);
          usage.cacheRead = num(u.cache_read_input_tokens);
          usage.cacheWrite = num(u.cache_creation_input_tokens);
          usage.output = num(u.output_tokens);
          break;
        }
        case "content_block_start": {
          const index = num(event.index);
          const block = (event.content_block ?? {}) as Json;
          if (block.type === "text") {
            blocks.set(index, { type: "text", text: typeof block.text === "string" ? block.text : "" });
          } else if (block.type === "tool_use") {
            blocks.set(index, {
              type: "tool_use",
              id: String(block.id ?? `toolu_${index}`),
              name: String(block.name ?? ""),
              input: {},
              json: "",
            });
          }
          break;
        }
        case "content_block_delta": {
          const block = blocks.get(num(event.index));
          const delta = (event.delta ?? {}) as Json;
          if (block?.type === "text" && delta.type === "text_delta" && typeof delta.text === "string") {
            block.text += delta.text;
            onText?.(delta.text);
          } else if (
            block?.type === "tool_use" &&
            delta.type === "input_json_delta" &&
            typeof delta.partial_json === "string"
          ) {
            block.json += delta.partial_json;
          }
          break;
        }
        case "message_delta": {
          const delta = (event.delta ?? {}) as Json;
          if (delta.stop_reason !== undefined) stop = stopOf(delta.stop_reason);
          const u = (event.usage ?? {}) as Json;
          if (u.output_tokens !== undefined) usage.output = num(u.output_tokens);
          break;
        }
        case "error": {
          const inner = (event.error ?? {}) as Json;
          const type = String(inner.type ?? "error");
          const kind = type === "overloaded_error" ? "unavailable" : type === "rate_limit_error" ? "rate" : "other";
          throw new ProviderError(kind, 0, redact(String(inner.message ?? type), this.key));
        }
      }
    }

    const content: (TextBlock | ToolUseBlock)[] = [];
    for (const index of [...blocks.keys()].sort((a, b) => a - b)) {
      const block = blocks.get(index);
      if (block === undefined) continue;
      if (block.type === "text") {
        if (block.text) content.push(block);
      } else {
        content.push({ type: "tool_use", id: block.id, name: block.name, input: parseArguments(block.json) });
      }
    }
    return { content, stop, usage };
  }
}

/** One small, free request that proves a key: the first page of the models list. */
export async function checkAnthropicKey(key: string): Promise<Response> {
  return fetch(ANTHROPIC_MODELS_URL, {
    headers: { "x-api-key": key, "anthropic-version": ANTHROPIC_VERSION },
  });
}
