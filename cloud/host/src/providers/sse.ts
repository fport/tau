/** A small server-sent events reader for the providers' streaming answers. */

export interface SseEvent {
  event: string;
  data: string;
}

/**
 * The events of an SSE body, in order. Lines are split on LF or CRLF; `data:` lines of one
 * event are joined with LF; comments and unknown fields are skipped; an event without data
 * is dropped. A body without a trailing blank line still yields its last event.
 */
export async function* sseEvents(body: ReadableStream<Uint8Array>): AsyncGenerator<SseEvent> {
  const reader = body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  let event = "";
  let data: string[] = [];
  let finished = false;
  const flush = (): SseEvent | null => {
    const out = data.length > 0 ? { event: event || "message", data: data.join("\n") } : null;
    event = "";
    data = [];
    return out;
  };
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) {
        finished = true;
        break;
      }
      buffer += value;
      let newline = buffer.indexOf("\n");
      while (newline !== -1) {
        let line = buffer.slice(0, newline);
        buffer = buffer.slice(newline + 1);
        if (line.endsWith("\r")) line = line.slice(0, -1);
        if (line === "") {
          const out = flush();
          if (out) yield out;
        } else if (!line.startsWith(":")) {
          const colon = line.indexOf(":");
          const field = colon === -1 ? line : line.slice(0, colon);
          let rest = colon === -1 ? "" : line.slice(colon + 1);
          if (rest.startsWith(" ")) rest = rest.slice(1);
          if (field === "event") event = rest;
          else if (field === "data") data.push(rest);
        }
        newline = buffer.indexOf("\n");
      }
    }
    if (buffer.trim() !== "") {
      const line = buffer.endsWith("\r") ? buffer.slice(0, -1) : buffer;
      if (line.startsWith("data:")) data.push(line.slice(5).replace(/^ /, ""));
    }
    const last = flush();
    if (last) yield last;
  } finally {
    // A consumer that stops early (an error, a cancelled turn) also stops the download.
    if (!finished) await reader.cancel().catch(() => undefined);
    reader.releaseLock();
  }
}
