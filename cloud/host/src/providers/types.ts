/**
 * The provider-neutral shapes of a conversation, and the contract every provider client keeps.
 *
 * A conversation is a list of messages whose content is blocks: text, a tool call
 * (`tool_use`) and a tool's answer (`tool_result`, always in a user message). Each client
 * maps these to its API and back; the agent loop and the stored sessions only know these.
 *
 * Usage is normalized: `input` counts only the fresh input tokens, the cached ones are in
 * `cacheRead`/`cacheWrite` (OpenAI and Gemini report cached tokens inside the prompt count;
 * their clients subtract them), and `output` includes thinking tokens.
 */

export type ProviderName = "anthropic" | "openai" | "gemini" | "fake";

export const CLOUD_PROVIDERS: readonly ProviderName[] = ["anthropic", "openai", "gemini"];

export type ModelRole = "brain" | "fast";

export const ROLES: readonly ModelRole[] = ["brain", "fast"];

export interface TextBlock {
  type: "text";
  text: string;
  /** Gemini's thought signature, sent back as it came. */
  signature?: string;
}

export interface ToolUseBlock {
  type: "tool_use";
  id: string;
  name: string;
  input: Record<string, unknown>;
  /** Gemini's thought signature, sent back as it came. */
  signature?: string;
}

export interface ToolResultBlock {
  type: "tool_result";
  id: string;
  name: string;
  text: string;
  error?: boolean;
}

export type Block = TextBlock | ToolUseBlock | ToolResultBlock;

export interface Message {
  role: "user" | "assistant";
  content: Block[];
}

/** A JSON Schema object of the subset every provider takes (object, string, array, ...). */
export interface JsonSchema {
  type: "object" | "string" | "integer" | "number" | "boolean" | "array";
  description?: string;
  properties?: Record<string, JsonSchema>;
  required?: string[];
  items?: JsonSchema;
}

export interface ToolSpec {
  name: string;
  description: string;
  parameters: JsonSchema;
}

export interface Usage {
  input: number;
  output: number;
  cacheRead: number;
  cacheWrite: number;
}

export const NO_USAGE: Usage = { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 };

export interface ModelRequest {
  model: string;
  system: string;
  messages: Message[];
  tools: ToolSpec[];
  maxTokens: number;
  signal?: AbortSignal;
}

export type StopReason = "end" | "tool_use" | "max_tokens" | "other";

export interface ModelResponse {
  content: (TextBlock | ToolUseBlock)[];
  stop: StopReason;
  usage: Usage;
}

/** Called with every piece of text as it streams in. */
export type OnText = (delta: string) => void;

export interface Provider {
  readonly name: ProviderName;
  complete(request: ModelRequest, onText?: OnText): Promise<ModelResponse>;
}

/**
 * A failed provider call. `kind` is what the owner can act on; `detail` is a short text with
 * every key-like string removed (it may reach the app, never a log line with the key).
 */
export type ProviderErrorKind = "auth" | "rate" | "unavailable" | "bad_request" | "other";

export class ProviderError extends Error {
  constructor(
    readonly kind: ProviderErrorKind,
    readonly status: number,
    readonly detail: string,
  ) {
    super(`${kind} (${status}): ${detail}`);
    this.name = "ProviderError";
  }
}

/** The ProviderError kind of an HTTP status. */
export function kindOf(status: number): ProviderErrorKind {
  if (status === 401 || status === 403) return "auth";
  if (status === 429) return "rate";
  if (status >= 500) return "unavailable";
  if (status >= 400) return "bad_request";
  return "other";
}

const KEY_LIKE = [
  /sk-ant-[A-Za-z0-9_-]{4,}/g,
  /sk-[A-Za-z0-9_-]{4,}/g,
  /AIza[0-9A-Za-z_-]{8,}/g,
  /\b[A-Za-z0-9_-]{32,}\b/g,
];

/** `text` without the key (whole or in part) and without anything that looks like a key. */
export function redact(text: string, key?: string): string {
  let out = text;
  if (key && key.length >= 8) {
    out = out.split(key).join("[redacted]");
    // Providers echo keys shortened as "sk-abc...wxyz": drop any run of the key's ends.
    out = out.split(key.slice(0, 8)).join("[redacted]");
    out = out.split(key.slice(-4)).join("[redacted]");
  }
  for (const pattern of KEY_LIKE) out = out.replace(pattern, "[redacted]");
  return out.length > 300 ? `${out.slice(0, 299)}…` : out;
}

/** A ProviderError from a non-2xx response; reads a small part of the body for the detail. */
export async function errorFromResponse(response: Response, key?: string): Promise<ProviderError> {
  let detail = "";
  try {
    const text = (await response.text()).slice(0, 4000);
    try {
      const parsed = JSON.parse(text) as unknown;
      detail = messageOf(parsed) ?? text;
    } catch {
      detail = text;
    }
  } catch {
    detail = "";
  }
  const kind = kindOf(response.status);
  if (kind === "auth") detail = "the provider refused the key";
  return new ProviderError(kind, response.status, redact(detail.trim() || response.statusText, key));
}

function messageOf(value: unknown): string | undefined {
  if (Array.isArray(value)) return messageOf(value[0]);
  if (typeof value !== "object" || value === null) return undefined;
  const record = value as Record<string, unknown>;
  const inner = record.error;
  if (typeof inner === "object" && inner !== null) {
    const message = (inner as Record<string, unknown>).message;
    if (typeof message === "string") return message;
  }
  if (typeof inner === "string") return inner;
  if (typeof record.message === "string") return record.message;
  return undefined;
}

/** Parses a tool call's JSON arguments; anything but an object becomes `{}`. */
export function parseArguments(text: string): Record<string, unknown> {
  if (!text.trim()) return {};
  try {
    const value = JSON.parse(text) as unknown;
    return typeof value === "object" && value !== null && !Array.isArray(value)
      ? (value as Record<string, unknown>)
      : {};
  } catch {
    return {};
  }
}
