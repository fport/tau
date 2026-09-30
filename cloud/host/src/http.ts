/** Small HTTP helpers shared by every route. */

const JSON_TYPE = "application/json; charset=utf-8";

export function json(body: unknown, status = 200, headers?: Record<string, string>): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": JSON_TYPE, "cache-control": "no-store", ...headers },
  });
}

/** `{"error": code}`, plus `detail` when there is something to say. */
export function error(status: number, code: string, detail?: string): Response {
  return json(detail === undefined ? { error: code } : { error: code, detail }, status);
}

export function badRequest(detail: string): Response {
  return error(400, "bad_request", detail);
}

export function notFound(): Response {
  return error(404, "not_found");
}

export function unauthorized(): Response {
  return error(401, "unauthorized");
}

export function methodNotAllowed(allow: string[]): Response {
  return json({ error: "method_not_allowed" }, 405, { allow: allow.join(", ") });
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

export function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export type JsonBody =
  { ok: true; value: Record<string, unknown> } | { ok: false; response: Response };

/**
 * Reads a JSON object body of at most `max` bytes: 415 unless the content type is JSON,
 * 413 too_large, 400 bad_request otherwise.
 */
export async function readJsonObject(request: Request, max: number): Promise<JsonBody> {
  const type = (request.headers.get("content-type") ?? "").split(";")[0]?.trim().toLowerCase();
  if (type !== "application/json") {
    await request.body?.cancel();
    return { ok: false, response: error(415, "unsupported_media_type", "send application/json") };
  }
  const bytes = await readLimited(request.body, max, request.headers.get("content-length"));
  if (bytes === null) return { ok: false, response: error(413, "too_large") };
  let text: string;
  try {
    text = strictUtf8.decode(bytes);
  } catch {
    return { ok: false, response: badRequest("body is not valid UTF-8") };
  }
  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch {
    value = undefined;
  }
  if (!isObject(value)) return { ok: false, response: badRequest("body must be a JSON object") };
  return { ok: true, value };
}

/** Reads a urlencoded form of at most `max` bytes, or null. */
export async function readForm(request: Request, max: number): Promise<URLSearchParams | null> {
  const bytes = await readLimited(request.body, max, request.headers.get("content-length"));
  if (bytes === null) return null;
  try {
    return new URLSearchParams(strictUtf8.decode(bytes));
  } catch {
    return null;
  }
}

export function nowSeconds(): number {
  return Math.floor(Date.now() / 1000);
}

/** The value of one cookie, or null. */
export function cookie(request: Request, name: string): string | null {
  const header = request.headers.get("cookie");
  if (header === null) return null;
  for (const part of header.split(";")) {
    const eq = part.indexOf("=");
    if (eq === -1) continue;
    if (part.slice(0, eq).trim() === name) return part.slice(eq + 1).trim();
  }
  return null;
}

export function redirect(location: string, headers: Record<string, string> = {}): Response {
  return new Response(null, {
    status: 302,
    headers: { location, "cache-control": "no-store", ...headers },
  });
}

/** A redirect that sets several cookies (one Set-Cookie header each). */
export function redirectWithCookies(location: string, cookies: string[]): Response {
  const headers = new Headers({ location, "cache-control": "no-store" });
  for (const value of cookies) headers.append("set-cookie", value);
  return new Response(null, { status: 302, headers });
}
