/**
 * Google Gemini `generateContent` over plain fetch, streamed
 * (`:streamGenerateContent?alt=sse`).
 *
 * Request: the system prompt as `systemInstruction`, the conversation as `contents` with the
 * roles `user` and `model`, tool calls as `functionCall` parts and tool answers as
 * `functionResponse` parts, the tools as `functionDeclarations` (the Schema subset, with
 * upper-case types). The key goes in the `x-goog-api-key` header, never in the URL.
 * Stream: every event is a partial response whose parts add text or whole function calls;
 * the last ones carry `finishReason` and `usageMetadata`. Gemini 3 attaches
 * `thoughtSignature`s to parts, which must come back unchanged in the next request, so the
 * blocks keep them. `promptTokenCount` includes `cachedContentTokenCount`; thinking tokens
 * (`thoughtsTokenCount`) are billed as output.
 */

import { randomToken } from "../crypto";
import { sseEvents } from "./sse";
import {
  errorFromResponse,
  type JsonSchema,
  type Message,
  type ModelRequest,
  type ModelResponse,
  type OnText,
  type Provider,
  ProviderError,
  redact,
  type StopReason,
  type TextBlock,
  type ToolUseBlock,
  type Usage,
} from "./types";

export const GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta";
export const GEMINI_MODELS_URL = `${GEMINI_BASE}/models?pageSize=1`;

/** Ids tau made up for calls Gemini sent without one; they are never sent back. */
const LOCAL_ID = "local_";

type Json = Record<string, unknown>;

export function toGeminiSchema(schema: JsonSchema): Json {
  const out: Json = { type: schema.type.toUpperCase() };
  if (schema.description) out.description = schema.description;
  if (schema.properties) {
    out.properties = Object.fromEntries(
      Object.entries(schema.properties).map(([name, inner]) => [name, toGeminiSchema(inner)]),
    );
  }
  if (schema.required) out.required = schema.required;
  if (schema.items) out.items = toGeminiSchema(schema.items);
  return out;
}

export function toGeminiContents(messages: Message[]): Json[] {
  const out: Json[] = [];
  for (const message of messages) {
    const parts: Json[] = [];
    for (const block of message.content) {
      if (block.type === "text") {
        if (!block.text && !block.signature) continue;
        parts.push({
          text: block.text,
          ...(block.signature ? { thoughtSignature: block.signature } : {}),
        });
      } else if (block.type === "tool_use") {
        parts.push({
          functionCall: {
            name: block.name,
            args: block.input,
            ...(block.id.startsWith(LOCAL_ID) ? {} : { id: block.id }),
          },
          ...(block.signature ? { thoughtSignature: block.signature } : {}),
        });
      } else {
        parts.push({
          functionResponse: {
            name: block.name,
            response: block.error ? { error: block.text } : { result: block.text },
            ...(block.id.startsWith(LOCAL_ID) ? {} : { id: block.id }),
          },
        });
      }
    }
    if (parts.length > 0) out.push({ role: message.role === "assistant" ? "model" : "user", parts });
  }
  return out;
}

export function geminiBody(request: ModelRequest): Json {
  return {
    systemInstruction: { parts: [{ text: request.system }] },
    contents: toGeminiContents(request.messages),
    ...(request.tools.length > 0
      ? {
          tools: [
            {
              functionDeclarations: request.tools.map((tool) => ({
                name: tool.name,
                description: tool.description,
                parameters: toGeminiSchema(tool.parameters),
              })),
            },
          ],
        }
      : {}),
    generationConfig: { maxOutputTokens: request.maxTokens },
  };
}

export function geminiUrl(model: string): string {
  return `${GEMINI_BASE}/models/${encodeURIComponent(model)}:streamGenerateContent?alt=sse`;
}

function num(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

export class GeminiProvider implements Provider {
  readonly name = "gemini" as const;

  constructor(private readonly key: string) {}

  async complete(request: ModelRequest, onText?: OnText): Promise<ModelResponse> {
    let response: Response;
    try {
      response = await fetch(geminiUrl(request.model), {
        method: "POST",
        headers: { "content-type": "application/json", "x-goog-api-key": this.key },
        body: JSON.stringify(geminiBody(request)),
        signal: request.signal,
      });
    } catch (err) {
      throw new ProviderError("unavailable", 0, redact(String(err), this.key));
    }
    if (!response.ok || response.body === null) throw await errorFromResponse(response, this.key);

    const usage: Usage = { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 };
    const content: (TextBlock | ToolUseBlock)[] = [];
    let finish: unknown;
    for await (const { data } of sseEvents(response.body)) {
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
      const candidates = Array.isArray(chunk.candidates) ? (chunk.candidates as Json[]) : [];
      const candidate = candidates[0];
      if (candidate !== undefined) {
        const parts = Array.isArray((candidate.content as Json | undefined)?.parts)
          ? ((candidate.content as Json).parts as Json[])
          : [];
        for (const part of parts) {
          if (part.thought === true) continue; // a thought summary, never shown or sent back
          const signature = typeof part.thoughtSignature === "string" ? part.thoughtSignature : undefined;
          if (typeof part.functionCall === "object" && part.functionCall !== null) {
            const call = part.functionCall as Json;
            content.push({
              type: "tool_use",
              id: typeof call.id === "string" && call.id ? call.id : LOCAL_ID + randomToken(9),
              name: String(call.name ?? ""),
              input:
                typeof call.args === "object" && call.args !== null && !Array.isArray(call.args)
                  ? (call.args as Record<string, unknown>)
                  : {},
              ...(signature ? { signature } : {}),
            });
          } else if (typeof part.text === "string") {
            const last = content.at(-1);
            if (last?.type === "text") {
              last.text += part.text;
              if (signature) last.signature = signature;
            } else {
              content.push({ type: "text", text: part.text, ...(signature ? { signature } : {}) });
            }
            if (part.text) onText?.(part.text);
          }
        }
        if (candidate.finishReason !== undefined) finish = candidate.finishReason;
      }
      if (typeof chunk.usageMetadata === "object" && chunk.usageMetadata !== null) {
        const u = chunk.usageMetadata as Json;
        const cached = num(u.cachedContentTokenCount);
        usage.input = Math.max(num(u.promptTokenCount) - cached, 0);
        usage.cacheRead = cached;
        usage.output = num(u.candidatesTokenCount) + num(u.thoughtsTokenCount);
      }
    }

    const kept = content.filter((block) => block.type !== "text" || block.text || block.signature);
    let stop: StopReason;
    if (kept.some((block) => block.type === "tool_use")) stop = "tool_use";
    else if (finish === "STOP") stop = "end";
    else if (finish === "MAX_TOKENS") stop = "max_tokens";
    else stop = "other";
    return { content: kept, stop, usage };
  }
}

/** One small, free request that proves a key: the first page of the models list. */
export async function checkGeminiKey(key: string): Promise<Response> {
  return fetch(GEMINI_MODELS_URL, { headers: { "x-goog-api-key": key } });
}
