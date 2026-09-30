/**
 * The provider clients against recorded streams (test/fixtures/*.sse) and fetch mocks: the
 * requests they send, the text they stream, the tool calls and usage they read back, the
 * errors they raise. No real provider is ever called.
 */

import { afterEach, describe, expect, it, vi } from "vitest";
import { cost, priceFor } from "../src/agent/budget";
import { AnthropicProvider, anthropicBody } from "../src/providers/anthropic";
import { GeminiProvider, geminiBody } from "../src/providers/gemini";
import { checkKey, providerFor, redact } from "../src/providers";
import { OpenAIProvider, openAIBody } from "../src/providers/openai";
import { sseEvents } from "../src/providers/sse";
import { type Message, type ModelRequest, ProviderError, type ToolSpec } from "../src/providers/types";
import { ASK_SUB_SPEC } from "../src/agent/tools";
import anthropicText from "./fixtures/anthropic-text.sse?raw";
import anthropicTool from "./fixtures/anthropic-tool.sse?raw";
import geminiText from "./fixtures/gemini-text.sse?raw";
import geminiTool from "./fixtures/gemini-tool.sse?raw";
import openaiText from "./fixtures/openai-text.sse?raw";
import openaiTool from "./fixtures/openai-tool.sse?raw";
import { mockFetch, sse } from "./helpers";

afterEach(() => {
  vi.restoreAllMocks();
});

const KEY = "sk-test-0000000000000000wxyz";
const TOOLS: ToolSpec[] = [ASK_SUB_SPEC];

function request(overrides: Partial<ModelRequest> = {}): ModelRequest {
  return {
    model: "test-model",
    system: "You are a test.",
    messages: [{ role: "user", content: [{ type: "text", text: "Hi" }] }],
    tools: TOOLS,
    maxTokens: 256,
    ...overrides,
  };
}

/** A conversation with a tool call and its answer, as the loop stores it. */
const WITH_TOOLS: Message[] = [
  { role: "user", content: [{ type: "text", text: "Ask the coach." }] },
  {
    role: "assistant",
    content: [
      { type: "text", text: "Asking." },
      { type: "tool_use", id: "call_1", name: "ask_sub", input: { name: "coach", question: "Plan?" } },
    ],
  },
  { role: "user", content: [{ type: "tool_result", id: "call_1", name: "ask_sub", text: "/coach answered: rest." }] },
];

describe("sse", () => {
  it("reads events split across chunks, CRLF, multi-line data, comments and a last event without a blank line", async () => {
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        const encoder = new TextEncoder();
        for (const part of [": comment\r\nevent: a\r\ndata: 1\r\n", "data: 2\r\n\r\ndata: {\"x\"", ":3}"]) {
          controller.enqueue(encoder.encode(part));
        }
        controller.close();
      },
    });
    const seen = [];
    for await (const event of sseEvents(body)) seen.push(event);
    expect(seen).toEqual([
      { event: "a", data: "1\n2" },
      { event: "message", data: '{"x":3}' },
    ]);
  });
});

describe("anthropic", () => {
  it("streams text and reads usage (cached input apart)", async () => {
    const { seen } = mockFetch({ "https://api.anthropic.com/v1/messages": () => sse(anthropicText) });
    const deltas: string[] = [];
    const response = await new AnthropicProvider(KEY).complete(request(), (d) => deltas.push(d));
    expect(deltas).toEqual(["Hello", ", how can I help?"]);
    expect(response).toEqual({
      content: [{ type: "text", text: "Hello, how can I help?" }],
      stop: "end",
      usage: { input: 412, output: 12, cacheRead: 100, cacheWrite: 0 },
    });
    const sent = seen[0];
    expect(sent?.headers.get("x-api-key")).toBe(KEY);
    expect(sent?.headers.get("anthropic-version")).toBe("2023-06-01");
    const body = JSON.parse(sent?.body ?? "{}");
    expect(body).toMatchObject({ model: "test-model", max_tokens: 256, system: "You are a test.", stream: true });
    expect(body.tools[0]).toEqual({ name: "ask_sub", description: ASK_SUB_SPEC.description, input_schema: ASK_SUB_SPEC.parameters });
  });

  it("reads a tool call from partial JSON", async () => {
    mockFetch({ "https://api.anthropic.com/v1/messages": () => sse(anthropicTool) });
    const response = await new AnthropicProvider(KEY).complete(request());
    expect(response.stop).toBe("tool_use");
    expect(response.content).toEqual([
      { type: "text", text: "I will ask the coach." },
      { type: "tool_use", id: "toolu_01A", name: "ask_sub", input: { name: "coach", question: "A plan for Monday?" } },
    ]);
    expect(response.usage).toEqual({ input: 500, output: 41, cacheRead: 0, cacheWrite: 20 });
  });

  it("sends tool calls and results back in its own format", () => {
    const body = anthropicBody(request({ messages: WITH_TOOLS }));
    expect(body.messages).toEqual([
      { role: "user", content: [{ type: "text", text: "Ask the coach." }] },
      {
        role: "assistant",
        content: [
          { type: "text", text: "Asking." },
          { type: "tool_use", id: "call_1", name: "ask_sub", input: { name: "coach", question: "Plan?" } },
        ],
      },
      { role: "user", content: [{ type: "tool_result", tool_use_id: "call_1", content: "/coach answered: rest." }] },
    ]);
    expect(anthropicBody(request({ tools: [] }))).not.toHaveProperty("tools");
  });

  it("maps errors without the key", async () => {
    mockFetch({
      "https://api.anthropic.com/v1/messages": () => new Response(
        JSON.stringify({ type: "error", error: { type: "authentication_error", message: `invalid x-api-key ${KEY}` } }),
        { status: 401 },
      ),
    });
    const err = await new AnthropicProvider(KEY).complete(request()).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ProviderError);
    expect((err as ProviderError).kind).toBe("auth");
    expect((err as ProviderError).detail).not.toContain("wxyz");
    expect(String(err)).not.toContain(KEY);
  });

  it("maps an overloaded stream error and a network failure to unavailable", async () => {
    mockFetch({
      "https://api.anthropic.com/v1/messages": () => sse(
        'event: error\ndata: {"type":"error","error":{"type":"overloaded_error","message":"Overloaded"}}\n\n',
      ),
    });
    const overloaded = await new AnthropicProvider(KEY).complete(request()).catch((e: unknown) => e);
    expect((overloaded as ProviderError).kind).toBe("unavailable");
    vi.restoreAllMocks();
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("connection refused"));
    const down = await new AnthropicProvider(KEY).complete(request()).catch((e: unknown) => e);
    expect((down as ProviderError).kind).toBe("unavailable");
  });
});

describe("openai", () => {
  it("streams text and reads usage (cached tokens taken out of the prompt count)", async () => {
    const { seen } = mockFetch({ "https://api.openai.com/v1/chat/completions": () => sse(openaiText) });
    const deltas: string[] = [];
    const response = await new OpenAIProvider(KEY).complete(request(), (d) => deltas.push(d));
    expect(deltas).toEqual(["Hello", ", how can I help?"]);
    expect(response).toEqual({
      content: [{ type: "text", text: "Hello, how can I help?" }],
      stop: "end",
      usage: { input: 320, output: 9, cacheRead: 100, cacheWrite: 0 },
    });
    expect(seen[0]?.headers.get("authorization")).toBe(`Bearer ${KEY}`);
    const body = JSON.parse(seen[0]?.body ?? "{}");
    expect(body).toMatchObject({
      model: "test-model",
      max_completion_tokens: 256,
      stream: true,
      stream_options: { include_usage: true },
    });
    expect(body.messages[0]).toEqual({ role: "system", content: "You are a test." });
    expect(body.tools[0]).toEqual({
      type: "function",
      function: { name: "ask_sub", description: ASK_SUB_SPEC.description, parameters: ASK_SUB_SPEC.parameters },
    });
  });

  it("assembles a tool call from its pieces", async () => {
    mockFetch({ "https://api.openai.com/v1/chat/completions": () => sse(openaiTool) });
    const response = await new OpenAIProvider(KEY).complete(request());
    expect(response.stop).toBe("tool_use");
    expect(response.content).toEqual([
      {
        type: "tool_use",
        id: "call_abc123",
        name: "create_sub",
        input: { name: "coach", about: "A workout coach.", persona: "You coach." },
      },
    ]);
    expect(response.usage).toEqual({ input: 300, output: 30, cacheRead: 0, cacheWrite: 0 });
  });

  it("sends tool calls as tool_calls and results as tool messages", () => {
    const body = openAIBody(request({ messages: WITH_TOOLS }));
    expect(body.messages).toEqual([
      { role: "system", content: "You are a test." },
      { role: "user", content: "Ask the coach." },
      {
        role: "assistant",
        content: "Asking.",
        tool_calls: [
          { id: "call_1", type: "function", function: { name: "ask_sub", arguments: '{"name":"coach","question":"Plan?"}' } },
        ],
      },
      { role: "tool", tool_call_id: "call_1", content: "/coach answered: rest." },
    ]);
  });

  it("redacts a key the provider echoes back", async () => {
    mockFetch({
      "https://api.openai.com/v1/chat/completions": () => new Response(
        JSON.stringify({ error: { message: `Incorrect API key provided: sk-test-00***wxyz.`, type: "invalid_request_error" } }),
        { status: 400 },
      ),
    });
    const err = (await new OpenAIProvider(KEY).complete(request()).catch((e: unknown) => e)) as ProviderError;
    expect(err.kind).toBe("bad_request");
    expect(err.detail).not.toContain("sk-test");
    expect(err.detail).not.toContain("wxyz");
  });

  it("maps 429 to rate and 500 to unavailable", async () => {
    mockFetch({ "https://api.openai.com/v1/chat/completions": () => new Response("{}", { status: 429 }) });
    expect(((await new OpenAIProvider(KEY).complete(request()).catch((e: unknown) => e)) as ProviderError).kind).toBe("rate");
    vi.restoreAllMocks();
    mockFetch({ "https://api.openai.com/v1/chat/completions": () => new Response("oops", { status: 500 }) });
    expect(((await new OpenAIProvider(KEY).complete(request()).catch((e: unknown) => e)) as ProviderError).kind).toBe(
      "unavailable",
    );
  });
});

describe("gemini", () => {
  it("streams text, keeps the thought signature and reads usage (thinking billed as output)", async () => {
    const { seen } = mockFetch({ "https://generativelanguage.googleapis.com/": () => sse(geminiText) });
    const deltas: string[] = [];
    const response = await new GeminiProvider(KEY).complete(request({ model: "gemini-3.5-flash" }), (d) => deltas.push(d));
    expect(deltas).toEqual(["Hello", ", how can I help?"]);
    expect(response).toEqual({
      content: [{ type: "text", text: "Hello, how can I help?", signature: "c2lnLXRleHQ" }],
      stop: "end",
      usage: { input: 310, output: 29, cacheRead: 100, cacheWrite: 0 },
    });
    const sent = seen[0];
    expect(sent?.url).toBe(
      "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:streamGenerateContent?alt=sse",
    );
    expect(sent?.url).not.toContain(KEY);
    expect(sent?.headers.get("x-goog-api-key")).toBe(KEY);
    const body = JSON.parse(sent?.body ?? "{}");
    expect(body.systemInstruction).toEqual({ parts: [{ text: "You are a test." }] });
    expect(body.generationConfig).toEqual({ maxOutputTokens: 256 });
    expect(body.tools[0].functionDeclarations[0].parameters.type).toBe("OBJECT");
    expect(body.tools[0].functionDeclarations[0].parameters.properties.name.type).toBe("STRING");
  });

  it("reads a function call (a local id when Gemini gives none) and sends it back with its signature", async () => {
    mockFetch({ "https://generativelanguage.googleapis.com/": () => sse(geminiTool) });
    const response = await new GeminiProvider(KEY).complete(request());
    expect(response.stop).toBe("tool_use");
    const call = response.content[0];
    expect(call).toMatchObject({
      type: "tool_use",
      name: "ask_sub",
      input: { name: "coach", question: "A plan for Monday?" },
      signature: "c2lnLWNhbGw",
    });
    expect(call?.type === "tool_use" && call.id.startsWith("local_")).toBe(true);
    const id = call?.type === "tool_use" ? call.id : "";
    const body = geminiBody(
      request({
        messages: [
          { role: "user", content: [{ type: "text", text: "Ask." }] },
          { role: "assistant", content: response.content },
          { role: "user", content: [{ type: "tool_result", id, name: "ask_sub", text: "rest" }] },
        ],
      }),
    );
    expect(body.contents).toEqual([
      { role: "user", parts: [{ text: "Ask." }] },
      {
        role: "model",
        parts: [
          {
            functionCall: { name: "ask_sub", args: { name: "coach", question: "A plan for Monday?" } },
            thoughtSignature: "c2lnLWNhbGw",
          },
        ],
      },
      { role: "user", parts: [{ functionResponse: { name: "ask_sub", response: { result: "rest" } } }] },
    ]);
  });
});

describe("key check", () => {
  it("asks each provider's free models list once, with the key in a header", async () => {
    const { seen } = mockFetch({
      "https://api.anthropic.com/v1/models": () => Response.json({ data: [] }),
      "https://api.openai.com/v1/models": () => Response.json({ data: [] }),
      "https://generativelanguage.googleapis.com/v1beta/models": () => Response.json({ models: [] }),
    });
    expect(await checkKey("anthropic", KEY)).toEqual({ ok: true });
    expect(await checkKey("openai", KEY)).toEqual({ ok: true });
    expect(await checkKey("gemini", KEY)).toEqual({ ok: true });
    expect(seen).toHaveLength(3);
    expect(seen[0]?.headers.get("x-api-key")).toBe(KEY);
    expect(seen[1]?.headers.get("authorization")).toBe(`Bearer ${KEY}`);
    expect(seen[2]?.headers.get("x-goog-api-key")).toBe(KEY);
    for (const req of seen) expect(req.url).not.toContain(KEY);
  });

  it("tells a wrong key from a check that could not be done", async () => {
    const status = { value: 401 };
    mockFetch({ "https://api.anthropic.com/": () => new Response("{}", { status: status.value }) });
    expect(await checkKey("anthropic", KEY)).toEqual({ ok: false, reason: "invalid" });
    status.value = 429;
    expect(await checkKey("anthropic", KEY)).toEqual({ ok: true });
    status.value = 503;
    expect(await checkKey("anthropic", KEY)).toEqual({ ok: false, reason: "unreachable" });
    expect(await checkKey("fake", "")).toEqual({ ok: true });
  });
});

describe("pricing", () => {
  it("prices normalized usage with the generated table", () => {
    const price = priceFor("anthropic", "claude-sonnet-5");
    expect(price).not.toBeNull();
    // 412 fresh input at $2/M, 12 output at $10/M, 100 cache reads at $0.20/M.
    expect(cost({ input: 412, output: 12, cacheRead: 100, cacheWrite: 0 }, price!)).toBeCloseTo(
      (412 * 2 + 12 * 10 + 100 * 0.2) / 1e6,
      12,
    );
    expect(priceFor("openai", "no-such-model")).toBeNull();
    expect(priceFor("fake", "fake-brain")).toEqual({ input: 0, output: 0, cache_read: 0, cache_write: 0 });
  });

  it("the fake provider needs no network", async () => {
    const spy = vi.spyOn(globalThis, "fetch");
    const response = await providerFor("fake", "").complete(request({ tools: [] }));
    expect(response.content[0]).toEqual({ type: "text", text: "(fake) You said: Hi" });
    expect(spy).not.toHaveBeenCalled();
  });

  it("redact removes keys and key-like strings", () => {
    expect(redact(`bad key ${KEY}`, KEY)).toBe("bad key [redacted]");
    expect(redact("AIzaSyA-1234567890abcdefghij is wrong")).toBe("[redacted] is wrong");
  });
});
