/** The app's calls to /api/host/*: JSON in and out, and the NDJSON stream of a turn. */

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    readonly detail?: string,
  ) {
    super(code);
  }
}

async function failure(response: Response): Promise<ApiError> {
  try {
    const body = (await response.json()) as { error?: string; detail?: string };
    return new ApiError(response.status, body.error ?? `http_${response.status}`, body.detail);
  } catch {
    return new ApiError(response.status, `http_${response.status}`);
  }
}

export async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      method,
      headers: body === undefined ? {} : { "content-type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
      credentials: "same-origin",
    });
  } catch {
    throw new ApiError(0, "network");
  }
  if (response.status === 401) {
    location.href = `/auth/login?next=${encodeURIComponent(location.pathname)}`;
    throw new ApiError(401, "unauthorized");
  }
  if (!response.ok) throw await failure(response);
  return (await response.json()) as T;
}

export type StreamEvent = Record<string, unknown> & { t: string };

/**
 * POSTs and reads the answer as NDJSON, calling `onEvent` per line. A JSON error answer
 * (the turn did not start) throws an ApiError.
 */
export async function stream(path: string, body: unknown, onEvent: (event: StreamEvent) => void): Promise<void> {
  let response: Response;
  try {
    response = await fetch(path, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
      credentials: "same-origin",
    });
  } catch {
    throw new ApiError(0, "network");
  }
  if (!response.ok || response.body === null) throw await failure(response);
  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += value;
    let newline = buffer.indexOf("\n");
    while (newline !== -1) {
      const line = buffer.slice(0, newline).trim();
      buffer = buffer.slice(newline + 1);
      if (line) {
        try {
          onEvent(JSON.parse(line) as StreamEvent);
        } catch {
          // A broken line is skipped; the next state load shows what was stored.
        }
      }
      newline = buffer.indexOf("\n");
    }
  }
}
