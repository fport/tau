/**
 * The turn protocol's TypeScript half (ADR 0015 §1, docs/reference/turn-protocol.md): the
 * events a backend streams for one turn, the history blocks of a stored session, and a
 * validator for both. The Python half is tau-core's `tau_core.turn_protocol`; both check
 * `vectors.json`, which tau-core writes (packages/tau-core/scripts/make_turn_vectors.py).
 *
 * Web APIs only, so it runs in workerd (tau-host) and in browsers (the web app). Import it by
 * relative path, e.g. `import { readEvents } from "../../shared/turn/index.ts"`.
 */

export const PROTOCOL_VERSION = 1;

/** Bytes of UTF-8 JSON a tool input may take before it becomes a `preview`. */
export const INPUT_LIMIT = 8192;

export const EVENT_TYPES = [
  "turn",
  "text",
  "reasoning",
  "tool_use",
  "tool_input",
  "tool_progress",
  "tool_result",
  "approval",
  "approval_decided",
  "widget",
  "throttled",
  "notice",
  "guard",
  "end",
  "error",
] as const;

export const BLOCK_TYPES = ["user", "assistant", "reasoning", "tool", "widget", "notice"] as const;

export const DECISIONS = ["approved", "rejected", "timeout"] as const;

/** Every `stop_reason` of an `end` event (tau-core's `STOP_REASONS`). */
export const STOP_REASONS = [
  "end_turn",
  "limit_turns",
  "limit_total_tokens",
  "max_tokens",
  "cancelled",
  "interrupt",
  "error",
  "busy",
  "locked",
] as const;

export type EventType = (typeof EVENT_TYPES)[number];
export type BlockType = (typeof BLOCK_TYPES)[number];
export type Decision = (typeof DECISIONS)[number];
export type StopReason = (typeof STOP_REASONS)[number];

/** A tool input, whole or (over `INPUT_LIMIT`) as a preview of its JSON text. */
export type InputFields =
  | { input: unknown; truncated: false }
  | { input: null; preview: string; truncated: true };

interface Frame {
  v: typeof PROTOCOL_VERSION;
  seq: number;
}

export type TurnStarted = Frame & { type: "turn"; turn: string; session: string };
export type TextEvent = Frame & { type: "text"; delta: string };
export type ReasoningEvent = Frame & { type: "reasoning"; delta: string };
export type ToolUseEvent = Frame & { type: "tool_use"; id: string; tool: string; tier: number | null };
export type ToolInputEvent = Frame & { type: "tool_input"; id: string; tool: string } & InputFields;
export type ToolProgressEvent = Frame & { type: "tool_progress"; id: string; tool: string; message: string };
export type ToolResultEvent = Frame & {
  type: "tool_result";
  id: string;
  tool: string;
  /** `ok`, `error` or `rejected` (refused before it ran). */
  status: string;
  summary: string;
  approval: string | null;
};
export type ApprovalEvent = Frame & {
  type: "approval";
  request: string;
  tool: string;
  tier: number;
  effect: string;
  /** Unix seconds, or `null` when the approval never expires on its own. */
  expires_at: number | null;
} & InputFields;
export type ApprovalDecidedEvent = Frame & { type: "approval_decided"; request: string; decision: Decision };
export type WidgetEvent = Frame & { type: "widget"; id: string; title: string; html: string };
export type ThrottledEvent = Frame & { type: "throttled"; delay_seconds: number };
export type NoticeEvent = Frame & { type: "notice"; text: string };
/** The owner guard (ADR 0008): `action` plus the fields of that action. */
export type GuardEvent = Frame & { type: "guard"; action: string; [field: string]: unknown };
export type EndEvent = Frame & { type: "end"; stop_reason: string };
export type ErrorEvent = Frame & { type: "error"; message: string };

export type TurnEvent =
  | TurnStarted
  | TextEvent
  | ReasoningEvent
  | ToolUseEvent
  | ToolInputEvent
  | ToolProgressEvent
  | ToolResultEvent
  | ApprovalEvent
  | ApprovalDecidedEvent
  | WidgetEvent
  | ThrottledEvent
  | NoticeEvent
  | GuardEvent
  | EndEvent
  | ErrorEvent;

/** ISO 8601 time the block was recorded, or `null` when the store kept none. */
type At = { at: string | null };

export type UserBlock = { type: "user"; text: string } & At;
export type AssistantBlock = { type: "assistant"; text: string } & At;
export type ReasoningBlock = { type: "reasoning"; text: string } & At;
export type ToolBlock = {
  type: "tool";
  id: string;
  tool: string;
  tier: number | null;
  status: string | null;
  summary: string;
  approval: string | null;
  duration_ms: number | null;
} & InputFields &
  At;
export type WidgetBlock = { type: "widget"; id: string; title: string; html: string } & At;
export type NoticeBlock = { type: "notice"; text: string } & At;

export type HistoryBlock = UserBlock | AssistantBlock | ReasoningBlock | ToolBlock | WidgetBlock | NoticeBlock;

// -- validation --------------------------------------------------------------------------------

type Json = Record<string, unknown>;
type Check = (o: Json) => boolean;

const str = (value: unknown): value is string => typeof value === "string";
const num = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);
const int = (value: unknown): value is number => Number.isInteger(value);
const orNull =
  <T>(test: (value: unknown) => value is T) =>
  (value: unknown): boolean =>
    value === null || test(value);
const fields =
  (spec: Record<string, (value: unknown) => boolean>): Check =>
  (o) =>
    Object.entries(spec).every(([key, test]) => test(o[key]));

const inputFields: Check = (o) =>
  o.truncated === false ? "input" in o : o.truncated === true && o.input === null && str(o.preview);

const EVENT_CHECKS: Record<EventType, Check> = {
  turn: fields({ turn: str, session: str }),
  text: fields({ delta: str }),
  reasoning: fields({ delta: str }),
  tool_use: fields({ id: str, tool: str, tier: orNull(int) }),
  tool_input: (o) => fields({ id: str, tool: str })(o) && inputFields(o),
  tool_progress: fields({ id: str, tool: str, message: str }),
  tool_result: fields({ id: str, tool: str, status: str, summary: str, approval: orNull(str) }),
  approval: (o) =>
    fields({ request: str, tool: str, tier: int, effect: str, expires_at: orNull(num) })(o) && inputFields(o),
  approval_decided: fields({ request: str, decision: (d) => (DECISIONS as readonly unknown[]).includes(d) }),
  widget: fields({ id: str, title: str, html: str }),
  throttled: fields({ delay_seconds: num }),
  notice: fields({ text: str }),
  guard: fields({ action: str }),
  end: fields({ stop_reason: str }),
  error: fields({ message: str }),
};

const at = (value: unknown): boolean => value === null || (str(value) && !Number.isNaN(Date.parse(value)));

const BLOCK_CHECKS: Record<BlockType, Check> = {
  user: fields({ text: str, at }),
  assistant: fields({ text: str, at }),
  reasoning: fields({ text: str, at }),
  tool: (o) =>
    fields({
      id: str,
      tool: str,
      tier: orNull(int),
      status: orNull(str),
      summary: str,
      approval: orNull(str),
      duration_ms: orNull(int),
      at,
    })(o) && inputFields(o),
  widget: fields({ id: str, title: str, html: str, at }),
  notice: fields({ text: str, at }),
};

const isObject = (value: unknown): value is Json =>
  typeof value === "object" && value !== null && !Array.isArray(value);

/** `value` as a turn event, or `null` when it is not one. Extra fields are allowed. */
export function parseEvent(value: unknown): TurnEvent | null {
  if (!isObject(value) || value.v !== PROTOCOL_VERSION || !int(value.seq) || value.seq < 0) return null;
  const check = EVENT_CHECKS[value.type as EventType];
  return Object.hasOwn(EVENT_CHECKS, String(value.type)) && check(value) ? (value as TurnEvent) : null;
}

/** `value` as a history block, or `null` when it is not one. Extra fields are allowed. */
export function parseBlock(value: unknown): HistoryBlock | null {
  if (!isObject(value)) return null;
  const check = BLOCK_CHECKS[value.type as BlockType];
  return Object.hasOwn(BLOCK_CHECKS, String(value.type)) && check(value) ? (value as HistoryBlock) : null;
}

// -- NDJSON ------------------------------------------------------------------------------------

export class ProtocolError extends Error {
  override name = "ProtocolError";
}

/** One compact JSON line, as the backends write them. */
export function encodeEvent(event: TurnEvent): string {
  return JSON.stringify(event) + "\n";
}

/** Splits text chunks into complete lines; keeps the unfinished tail for the next chunk. */
export class LineSplitter {
  #tail = "";

  push(chunk: string): string[] {
    const parts = (this.#tail + chunk).split("\n");
    this.#tail = parts.pop() ?? "";
    return parts.filter((line) => line.trim() !== "");
  }

  /** The last line when the stream ended without a newline. */
  flush(): string[] {
    const rest = this.#tail;
    this.#tail = "";
    return rest.trim() === "" ? [] : [rest];
  }
}

function parseLine(line: string): TurnEvent {
  let value: unknown;
  try {
    value = JSON.parse(line);
  } catch {
    throw new ProtocolError("a line of the stream is not JSON");
  }
  const event = parseEvent(value);
  if (event === null) throw new ProtocolError("a line of the stream is not a turn event");
  return event;
}

/** The events of an NDJSON response body; throws `ProtocolError` on a line that is not one. */
export async function* readEvents(body: ReadableStream<Uint8Array>): AsyncGenerator<TurnEvent> {
  const decoder = new TextDecoder();
  const lines = new LineSplitter();
  const reader = body.getReader();
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      for (const line of lines.push(decoder.decode(value, { stream: true }))) yield parseLine(line);
    }
    for (const line of lines.push(decoder.decode())) yield parseLine(line);
    for (const line of lines.flush()) yield parseLine(line);
  } finally {
    reader.releaseLock();
  }
}
