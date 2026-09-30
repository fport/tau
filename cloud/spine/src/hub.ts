/**
 * The hub API (§5 of docs/reference/tau-network.md): bearer-token routes the owner's hub
 * uses to publish the card, long-poll the mailbox and acknowledge envelopes. Cloud-mode
 * routes are dispatched to store.ts.
 */

import { ownAddress } from "./address";
import { b64uKey, tokenEquals } from "./crypto";
import { modeOf, type SpineEnv } from "./env";
import {
  badRequest,
  error,
  intParam,
  json,
  methodNotAllowed,
  notFound,
  rawJson,
  readJsonObject,
} from "./http";
import { publicCard, readStoredCard, writeStoredCard } from "./net";
import { SIGNAL_NAME } from "./signal";
import { handleStore, isCloudRoute } from "./store";
import { VERSION } from "./version";

export const MAX_POLL_TIMEOUT_SECONDS = 25;
export const MAX_UPDATES_LIMIT = 100;
const DEFAULT_UPDATES_LIMIT = 50;
const MAX_ACK_SEQS = 1_000;
const MAX_CARD_BODY_BYTES = 4_096;

/** 503 without a HUB_TOKEN secret, 401 without the right bearer token, else null. */
async function authorize(request: Request, env: SpineEnv): Promise<Response | null> {
  const expected = env.HUB_TOKEN ?? "";
  if (expected === "") return error(503, "not_configured");
  const header = request.headers.get("authorization") ?? "";
  const match = /^Bearer\s+(\S+)\s*$/i.exec(header);
  const given = match?.[1] ?? "";
  if (!(await tokenEquals(given, expected))) return error(401, "unauthorized");
  return null;
}

export async function handleHub(request: Request, env: SpineEnv, url: URL): Promise<Response> {
  const denied = await authorize(request, env);
  if (denied !== null) return denied;

  const { pathname: path } = url;
  const method = request.method;
  switch (path) {
    case "/hub/health":
      return method === "GET" ? health(env, url) : methodNotAllowed(["GET"]);
    case "/hub/card":
      return method === "PUT" ? putCard(request, env, url) : methodNotAllowed(["PUT"]);
    case "/hub/updates":
      return method === "GET" ? updates(env, url) : methodNotAllowed(["GET"]);
    case "/hub/ack":
      return method === "POST" ? ack(request, env) : methodNotAllowed(["POST"]);
  }
  if (isCloudRoute(path)) {
    if (modeOf(env) !== "cloud") return error(404, "cloud_mode_off");
    return handleStore(request, env, url);
  }
  return notFound();
}

/** GET /hub/health */
async function health(env: SpineEnv, url: URL): Promise<Response> {
  const [card, mailbox] = await Promise.all([
    readStoredCard(env),
    env.DB.prepare("SELECT COUNT(*) AS n FROM mailbox").first<number>("n"),
  ]);
  return json({
    ok: true,
    address: ownAddress(env, url),
    mode: modeOf(env),
    card: card !== null,
    mailbox: mailbox ?? 0,
    version: VERSION,
  });
}

/** PUT /hub/card: `{name, sign_key, box_key}`; the spine adds address, inbox and software. */
async function putCard(request: Request, env: SpineEnv, url: URL): Promise<Response> {
  const body = await readJsonObject(request, MAX_CARD_BODY_BYTES);
  if (!body.ok) return body.response;
  const { name, sign_key, box_key } = body.value;
  // Characters are counted as code points, like Python's len().
  if (typeof name !== "string" || [...name].length < 1 || [...name].length > 80) {
    return badRequest("name must be a string of 1 to 80 characters");
  }
  if (b64uKey(sign_key) === null) return badRequest("sign_key must be b64u of 32 bytes");
  if (b64uKey(box_key) === null) return badRequest("box_key must be b64u of 32 bytes");
  const stored = { name, sign_key: sign_key as string, box_key: box_key as string };
  await writeStoredCard(env, stored);
  return json(publicCard(env, ownAddress(env, url), stored));
}

interface MailboxRow {
  seq: number;
  received_at: number;
  envelope: string;
}

async function queued(env: SpineEnv, after: number, limit: number): Promise<MailboxRow[]> {
  const { results } = await env.DB.prepare(
    "SELECT seq, received_at, envelope FROM mailbox WHERE seq > ?1 ORDER BY seq LIMIT ?2",
  )
    .bind(after, limit)
    .all<MailboxRow>();
  return results;
}

/**
 * GET /hub/updates?after=&timeout=&limit=
 *
 * With nothing queued and `timeout > 0`, the call waits on the HubSignal object until an
 * envelope arrives or the timeout passes, then queries once more and answers (possibly
 * with an empty list).
 */
async function updates(env: SpineEnv, url: URL): Promise<Response> {
  const after = intParam(url, "after", 0);
  const timeout = intParam(url, "timeout", 0);
  const limit = intParam(url, "limit", DEFAULT_UPDATES_LIMIT);
  if (after === null) return badRequest("after must be a non-negative integer");
  if (timeout === null || timeout > MAX_POLL_TIMEOUT_SECONDS) {
    return badRequest(`timeout must be an integer from 0 to ${MAX_POLL_TIMEOUT_SECONDS}`);
  }
  if (limit === null || limit < 1 || limit > MAX_UPDATES_LIMIT) {
    return badRequest(`limit must be an integer from 1 to ${MAX_UPDATES_LIMIT}`);
  }

  let rows = await queued(env, after, limit);
  if (rows.length === 0 && timeout > 0) {
    const ms = timeout * 1000;
    const started = Date.now();
    try {
      await env.SIGNAL.getByName(SIGNAL_NAME).wait(ms, after);
    } catch (err) {
      // Without the signal the poll still honours its timeout instead of spinning.
      console.error(JSON.stringify({ event: "signal_wait_failed", error: String(err) }));
      const left = ms - (Date.now() - started);
      if (left > 0) await new Promise((resolve) => setTimeout(resolve, left));
    }
    rows = await queued(env, after, limit);
  }

  // Envelopes are stored as serialized JSON; splice them in without re-parsing.
  const items = rows.map(
    (row) => `{"seq":${row.seq},"received_at":${row.received_at},"envelope":${row.envelope}}`,
  );
  return rawJson(`{"updates":[${items.join(",")}]}`);
}

/** POST /hub/ack: `{seqs: [int, ...]}` deletes those envelopes. */
async function ack(request: Request, env: SpineEnv): Promise<Response> {
  const body = await readJsonObject(request, 65_536);
  if (!body.ok) return body.response;
  const seqs = body.value.seqs;
  if (
    !Array.isArray(seqs) ||
    seqs.length > MAX_ACK_SEQS ||
    !seqs.every((s) => Number.isSafeInteger(s) && (s as number) >= 0)
  ) {
    return badRequest(`seqs must be a list of at most ${MAX_ACK_SEQS} non-negative integers`);
  }
  const unique = [...new Set(seqs as number[])];
  if (unique.length === 0) return json({ deleted: 0 });
  // D1 allows 100 bound parameters per statement.
  const statements = [];
  for (let i = 0; i < unique.length; i += 100) {
    const chunk = unique.slice(i, i + 100);
    statements.push(
      env.DB.prepare(`DELETE FROM mailbox WHERE seq IN (${chunk.map(() => "?").join(",")})`).bind(
        ...chunk,
      ),
    );
  }
  const results = await env.DB.batch(statements);
  const deleted = results.reduce((sum, result) => sum + (result.meta.changes ?? 0), 0);
  return json({ deleted });
}
