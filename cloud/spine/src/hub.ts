/**
 * The hub API (§5 of docs/reference/tau-network.md): bearer-token routes the owner's hub
 * uses to publish the card, fetch or long-poll the mailbox, wait on the doorbell and
 * acknowledge envelopes. The mailbox is the Mailbox Durable Object (mailbox.ts); cloud-mode
 * routes are dispatched to store.ts.
 */

import { ownAddress } from "./address";
import { b64uKey, tokenEquals } from "./crypto";
import { modeOf, type SpineEnv } from "./env";
import {
  badRequest,
  error,
  intParam,
  isWebSocketUpgrade,
  json,
  methodNotAllowed,
  notFound,
  rawJson,
  readJsonObject,
  upgradeRequired,
} from "./http";
import { mailboxOf } from "./mailbox";
import { publicCard, readStoredCard, writeStoredCard } from "./net";
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
    case "/hub/ws":
      return method === "GET" ? doorbell(request, env) : methodNotAllowed(["GET"]);
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
    mailboxOf(env).depth(),
  ]);
  return json({
    ok: true,
    address: ownAddress(env, url),
    mode: modeOf(env),
    card: card !== null,
    mailbox,
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

/**
 * GET /hub/updates?after=&timeout=&limit=
 *
 * With nothing queued and `timeout > 0`, the call waits inside the Mailbox until an
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

  const rows = await mailboxOf(env).updates(after, limit, timeout * 1000);

  // Envelopes are stored as serialized JSON; splice them in without re-parsing.
  const items = rows.map(
    (row) => `{"seq":${row.seq},"received_at":${row.received_at},"envelope":${row.envelope}}`,
  );
  return rawJson(`{"updates":[${items.join(",")}]}`);
}

/**
 * GET /hub/ws: the doorbell. The hub sends its bearer token in the upgrade request (it is not
 * a browser), so it passed authorize() above; the Mailbox accepts the socket. The socket only
 * says "look now": the hub fetches with `GET /hub/updates?timeout=0` and acknowledges with
 * `POST /hub/ack`.
 */
async function doorbell(request: Request, env: SpineEnv): Promise<Response> {
  if (!isWebSocketUpgrade(request)) return upgradeRequired();
  return mailboxOf(env).fetch(request);
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
  const deleted = await mailboxOf(env).ack(unique);
  return json({ deleted });
}
