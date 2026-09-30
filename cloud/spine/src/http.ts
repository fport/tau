/** Small HTTP helpers shared by every route. */

const JSON_TYPE = "application/json; charset=utf-8";

export function json(body: unknown, status = 200, headers?: Record<string, string>): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": JSON_TYPE, ...headers },
  });
}

/** A JSON response from text that is already serialized JSON (stored documents). */
export function rawJson(text: string, status = 200): Response {
  return new Response(text, { status, headers: { "content-type": JSON_TYPE } });
}

/** `{"error": code}`, plus `detail` for bad requests. */
export function error(status: number, code: string, detail?: string): Response {
  return json(detail === undefined ? { error: code } : { error: code, detail }, status);
}

export function badRequest(detail: string): Response {
  return error(400, "bad_request", detail);
}

export function notFound(): Response {
  return error(404, "not_found");
}

export function methodNotAllowed(allow: string[]): Response {
  return json({ error: "method_not_allowed" }, 405, { allow: allow.join(", ") });
}

/** Whether the request asks to switch to WebSocket (`Upgrade: websocket`). */
export function isWebSocketUpgrade(request: Request): boolean {
  return (request.headers.get("upgrade") ?? "").trim().toLowerCase() === "websocket";
}

/** `426 {"error": "upgrade_required"}` with `Upgrade: websocket`. */
export function upgradeRequired(): Response {
  return json({ error: "upgrade_required" }, 426, { upgrade: "websocket" });
}

/**
 * Whether the request declares a JSON body: `Content-Type: application/json`, parameters
 * such as `charset` allowed.
 */
export function isJsonRequest(request: Request): boolean {
  const type = (request.headers.get("content-type") ?? "").split(";", 1)[0] ?? "";
  return type.trim().toLowerCase() === "application/json";
}

/**
 * Reads a body of at most `max` bytes. Returns null as soon as it is larger (the stream is
 * cancelled, so an oversized body is never buffered in full).
 */
export async function readLimited(
  body: ReadableStream<Uint8Array> | null,
  max: number,
  contentLength?: string | null,
): Promise<Uint8Array | null> {
  if (contentLength) {
    const declared = Number(contentLength);
    if (Number.isFinite(declared) && declared > max) {
      await body?.cancel();
      return null;
    }
  }
  if (body === null) return new Uint8Array(0);
  const reader = body.getReader();
  const chunks: Uint8Array[] = [];
  let size = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    size += value.byteLength;
    if (size > max) {
      await reader.cancel();
      return null;
    }
    chunks.push(value);
  }
  const out = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) {
    out.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return out;
}

const strictUtf8 = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true });

/** Decodes UTF-8, or returns null for invalid bytes. */
export function utf8(bytes: Uint8Array): string | null {
  try {
    return strictUtf8.decode(bytes);
  } catch {
    return null;
  }
}

/** Parses JSON, or returns undefined. */
export function parseJson(text: string): unknown {
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return undefined;
  }
}

export function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export type JsonBody =
  { ok: true; value: Record<string, unknown> } | { ok: false; response: Response };

/** Reads a JSON object body of at most `max` bytes: 413 too_large or 400 bad_request otherwise. */
export async function readJsonObject(request: Request, max: number): Promise<JsonBody> {
  const bytes = await readLimited(request.body, max, request.headers.get("content-length"));
  if (bytes === null) return { ok: false, response: error(413, "too_large") };
  const text = utf8(bytes);
  if (text === null) return { ok: false, response: badRequest("body is not valid UTF-8") };
  const value = parseJson(text);
  if (!isObject(value)) return { ok: false, response: badRequest("body must be a JSON object") };
  return { ok: true, value };
}

export function nowSeconds(): number {
  return Math.floor(Date.now() / 1000);
}

export function nowIso(): string {
  return new Date().toISOString();
}

/** A non-negative integer from a query parameter, the default when absent, or null when invalid. */
export function intParam(url: URL, name: string, fallback: number): number | null {
  const raw = url.searchParams.get(name);
  if (raw === null || raw === "") return fallback;
  if (!/^[0-9]{1,15}$/.test(raw)) return null;
  return Number(raw);
}
