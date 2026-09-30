/**
 * Cloud-mode routes: state, files, sessions and the brain (§5 "Cloud mode only").
 *
 * hub.ts only calls this module when TAU_MODE is "cloud", so a local-mode spine can never
 * hold life data. State and sessions live in D1, which only the cloud configuration binds;
 * files live in KV. Stored documents are opaque: the spine keeps them as JSON text and never
 * interprets them.
 */

import { brainHealth } from "./brain";
import { isUniqueViolation } from "./d1";
import type { SpineEnv } from "./env";
import {
  badRequest,
  error,
  intParam,
  isObject,
  json,
  methodNotAllowed,
  notFound,
  nowIso,
  nowSeconds,
  rawJson,
  readJsonObject,
  readLimited,
  utf8,
} from "./http";

export const MAX_DOCUMENT_BYTES = 1_048_576;
export const MAX_FILE_BYTES = 524_288;
const MAX_SESSIONS_LIMIT = 200;
const DEFAULT_SESSIONS_LIMIT = 20;
const MAX_MESSAGES = 10_000;

const STATE_KEY = /^[a-z0-9][a-z0-9._:-]{0,127}$/;
const ID = /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/;
const MESSAGE_ID = /^[0-9]{1,15}$/;

/** The fixed files the spine keeps (in KV under `file:<name>`). */
export const FILE_NAMES = [
  "tau.toml",
  "persona/persona.md",
  "persona/user.md",
  "persona/net.md",
] as const;

/** The directory of sub-tau files: definitions (`coach.md`) and public notes (`coach.public.md`). */
export const SUBS_PREFIX = "persona/subs/";

/**
 * A file directly in `persona/subs/`: a plain name ending in `.md` that starts with a letter
 * or a digit, so no hidden file, no slash and no `..` segment.
 */
export const SUB_FILE = /^[A-Za-z0-9][A-Za-z0-9._-]{0,80}\.md$/;

/** The environment of the D1 routes (state, sessions): cloud mode with its D1 binding. */
type StoreEnv = SpineEnv & { DB: D1Database };

function hasStore(env: SpineEnv): env is StoreEnv {
  return env.DB !== undefined;
}

export function isCloudRoute(path: string): boolean {
  return (
    path.startsWith("/hub/state/") ||
    path === "/hub/files" ||
    path.startsWith("/hub/files/") ||
    path === "/hub/sessions" ||
    path.startsWith("/hub/sessions/") ||
    path === "/hub/brain"
  );
}

export async function handleStore(request: Request, env: SpineEnv, url: URL): Promise<Response> {
  const path = url.pathname;
  if (path === "/hub/brain") {
    return request.method === "GET" ? brainHealth(env) : methodNotAllowed(["GET"]);
  }
  if (path === "/hub/files" || path.startsWith("/hub/files/")) {
    return files(request, env, path.slice("/hub/files".length).replace(/^\//, ""));
  }
  if (!hasStore(env)) {
    // TAU_MODE=cloud on a configuration without D1 (the local-mode wrangler.jsonc).
    console.error(JSON.stringify({ event: "store_unavailable", reason: "no DB binding" }));
    return error(503, "not_configured");
  }
  if (path.startsWith("/hub/state/")) {
    return state(request, env, path.slice("/hub/state/".length));
  }
  return sessions(request, env, url);
}

function decodeSegment(segment: string): string | null {
  try {
    return decodeURIComponent(segment);
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------------------
// State

interface StateRow {
  value: string;
  updated_at: number;
}

async function state(request: Request, env: StoreEnv, rawKey: string): Promise<Response> {
  const key = decodeSegment(rawKey);
  if (key === null || !STATE_KEY.test(key)) {
    return badRequest("key must match ^[a-z0-9][a-z0-9._:-]{0,127}$");
  }
  switch (request.method) {
    case "GET": {
      const row = await env.DB.prepare("SELECT value, updated_at FROM state WHERE key = ?1")
        .bind(key)
        .first<StateRow>();
      if (row === null) return notFound();
      return rawJson(
        `{"key":${JSON.stringify(key)},"value":${row.value},"updated_at":${row.updated_at}}`,
      );
    }
    case "PUT": {
      const body = await readJsonObject(request, MAX_DOCUMENT_BYTES);
      if (!body.ok) return body.response;
      if (!("value" in body.value)) return badRequest('body must be {"value": <any JSON>}');
      const updatedAt = nowSeconds();
      await env.DB.prepare(
        "INSERT INTO state (key, value, updated_at) VALUES (?1, ?2, ?3) " +
          "ON CONFLICT (key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
      )
        .bind(key, JSON.stringify(body.value.value), updatedAt)
        .run();
      return json({ key, updated_at: updatedAt });
    }
    case "DELETE": {
      const result = await env.DB.prepare("DELETE FROM state WHERE key = ?1").bind(key).run();
      return json({ deleted: (result.meta.changes ?? 0) > 0 });
    }
    default:
      return methodNotAllowed(["GET", "PUT", "DELETE"]);
  }
}

// ---------------------------------------------------------------------------------------
// Files

interface FileMeta {
  size: number;
  updated_at: number;
}

/** A fixed file, or a sub-tau file `persona/subs/<file>`; checked after URL decoding. */
export function isFileName(name: string): boolean {
  if ((FILE_NAMES as readonly string[]).includes(name)) return true;
  return name.startsWith(SUBS_PREFIX) && SUB_FILE.test(name.slice(SUBS_PREFIX.length));
}

interface FileEntry extends FileMeta {
  name: string;
}

/** The sub-tau files in KV, sorted by name; a KV listing carries each key's metadata. */
async function subFiles(env: SpineEnv): Promise<FileEntry[]> {
  const found: FileEntry[] = [];
  let cursor: string | undefined;
  do {
    const page = await env.TAU.list<FileMeta>({
      prefix: `file:${SUBS_PREFIX}`,
      ...(cursor === undefined ? {} : { cursor }),
    });
    for (const key of page.keys) {
      const name = key.name.slice("file:".length);
      if (!isFileName(name)) continue;
      found.push({
        name,
        size: key.metadata?.size ?? 0,
        updated_at: key.metadata?.updated_at ?? 0,
      });
    }
    cursor = page.list_complete ? undefined : page.cursor;
  } while (cursor !== undefined);
  return found.sort((a, b) => (a.name < b.name ? -1 : a.name > b.name ? 1 : 0));
}

async function files(request: Request, env: SpineEnv, rawName: string): Promise<Response> {
  if (rawName === "") {
    if (request.method !== "GET") return methodNotAllowed(["GET"]);
    const fixed = await Promise.all(
      FILE_NAMES.map(async (name): Promise<FileEntry | null> => {
        const { value, metadata } = await env.TAU.getWithMetadata<FileMeta>(`file:${name}`);
        if (value === null) return null;
        return {
          name,
          size: metadata?.size ?? value.length,
          updated_at: metadata?.updated_at ?? 0,
        };
      }),
    );
    const listed = fixed.filter((file) => file !== null);
    return json({ files: [...listed, ...(await subFiles(env))] });
  }

  const name = decodeSegment(rawName);
  if (name === null || !isFileName(name)) return notFound();
  switch (request.method) {
    case "GET": {
      const text = await env.TAU.get(`file:${name}`);
      if (text === null) return notFound();
      return new Response(text, { headers: { "content-type": "text/plain; charset=utf-8" } });
    }
    case "PUT": {
      const bytes = await readLimited(
        request.body,
        MAX_FILE_BYTES,
        request.headers.get("content-length"),
      );
      if (bytes === null) return error(413, "too_large");
      const text = utf8(bytes);
      if (text === null) return badRequest("body must be UTF-8 text");
      const meta: FileMeta = { size: bytes.length, updated_at: nowSeconds() };
      await env.TAU.put(`file:${name}`, text, { metadata: meta });
      return json({ name, ...meta });
    }
    case "DELETE": {
      const existed = (await env.TAU.get(`file:${name}`)) !== null;
      if (existed) await env.TAU.delete(`file:${name}`);
      return json({ deleted: existed });
    }
    default:
      return methodNotAllowed(["GET", "PUT", "DELETE"]);
  }
}

// ---------------------------------------------------------------------------------------
// Sessions

const NEXT_REV = "(SELECT COALESCE(MAX(rev), 0) + 1 FROM sessions)";

/** Refreshes updated_at and moves the session to the top of the listing. */
function touch(env: StoreEnv, sid: string, now: string): D1PreparedStatement {
  return env.DB.prepare(
    `UPDATE sessions SET updated_at = ?2, rev = ${NEXT_REV} WHERE session_id = ?1`,
  ).bind(sid, now);
}

/**
 * Creates the session with a minimal Strands record (§5 "PATCH .../meta") when it is
 * missing, else touches it. With `meta`, the stored meta is replaced by it.
 */
function upsertSession(
  env: StoreEnv,
  sid: string,
  now: string,
  meta?: string,
): D1PreparedStatement {
  const data = JSON.stringify({
    session_id: sid,
    session_type: "AGENT",
    created_at: now,
    updated_at: now,
  });
  return env.DB.prepare(
    "INSERT INTO sessions (session_id, data, meta, created_at, updated_at, rev) " +
      `VALUES (?1, ?2, ?3, ?4, ?4, ${NEXT_REV}) ON CONFLICT (session_id) DO UPDATE SET ` +
      (meta === undefined ? "" : "meta = excluded.meta, ") +
      "updated_at = excluded.updated_at, rev = excluded.rev",
  ).bind(sid, data, meta ?? "{}", now);
}

async function sessionExists(env: StoreEnv, sid: string): Promise<boolean> {
  const row = await env.DB.prepare("SELECT 1 AS found FROM sessions WHERE session_id = ?1")
    .bind(sid)
    .first();
  return row !== null;
}

async function agentExists(env: StoreEnv, sid: string, aid: string): Promise<boolean> {
  const row = await env.DB.prepare(
    "SELECT 1 AS found FROM agents WHERE session_id = ?1 AND agent_id = ?2",
  )
    .bind(sid, aid)
    .first();
  return row !== null;
}

const created = (): Response => json({ ok: true }, 201);
const ok = (): Response => json({ ok: true });
const exists = (): Response => error(409, "exists");

/** A JSON body with a `data` member of any JSON type. */
type DataBody =
  { ok: true; body: Record<string, unknown>; data: string } | { ok: false; response: Response };

async function readData(request: Request): Promise<DataBody> {
  const body = await readJsonObject(request, MAX_DOCUMENT_BYTES);
  if (!body.ok) return body;
  if (!("data" in body.value)) return { ok: false, response: badRequest("body must carry data") };
  return { ok: true, body: body.value, data: JSON.stringify(body.value.data) };
}

async function sessions(request: Request, env: StoreEnv, url: URL): Promise<Response> {
  const raw = url.pathname.slice("/hub/sessions".length).split("/").slice(1);
  const parts = raw.map(decodeSegment);
  if (parts.some((part) => part === null)) return badRequest("bad path encoding");
  const [sid, sub, aid, leaf, mid, ...rest] = parts as string[];
  const method = request.method;

  if (sid === undefined) {
    if (method === "GET") return listSessions(env, url);
    if (method === "POST") return createSession(request, env);
    return methodNotAllowed(["GET", "POST"]);
  }
  if (!ID.test(sid)) return badRequest("session id must match ^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$");

  if (sub === undefined) {
    if (method !== "GET") return methodNotAllowed(["GET"]);
    const row = await env.DB.prepare("SELECT data FROM sessions WHERE session_id = ?1")
      .bind(sid)
      .first<{ data: string }>();
    return row === null ? notFound() : rawJson(`{"data":${row.data}}`);
  }

  if (sub === "meta" && aid === undefined) {
    if (method === "GET") return readMeta(env, sid);
    if (method === "PATCH") return patchMeta(request, env, sid);
    return methodNotAllowed(["GET", "PATCH"]);
  }

  if (sub === "events" && aid === undefined) {
    if (method === "GET") return listEvents(env, sid);
    if (method === "POST") return appendEvent(request, env, sid);
    return methodNotAllowed(["GET", "POST"]);
  }

  if (sub !== "agents") return notFound();
  if (aid === undefined) {
    return method === "POST" ? createAgent(request, env, sid) : methodNotAllowed(["POST"]);
  }
  if (!ID.test(aid)) return badRequest("agent id must match ^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$");

  if (leaf === undefined) {
    if (method === "GET") {
      const row = await env.DB.prepare(
        "SELECT data FROM agents WHERE session_id = ?1 AND agent_id = ?2",
      )
        .bind(sid, aid)
        .first<{ data: string }>();
      return row === null ? notFound() : rawJson(`{"data":${row.data}}`);
    }
    if (method === "PUT") return updateAgent(request, env, sid, aid);
    return methodNotAllowed(["GET", "PUT"]);
  }

  if (leaf !== "messages" || rest.length > 0) return notFound();
  if (mid === undefined) {
    if (method === "GET") return listMessages(env, url, sid, aid);
    if (method === "POST") return createMessage(request, env, sid, aid);
    return methodNotAllowed(["GET", "POST"]);
  }
  if (!MESSAGE_ID.test(mid)) return badRequest("message id must be a non-negative integer");
  const messageId = Number(mid);
  if (method === "GET") {
    const row = await env.DB.prepare(
      "SELECT data FROM messages WHERE session_id = ?1 AND agent_id = ?2 AND message_id = ?3",
    )
      .bind(sid, aid, messageId)
      .first<{ data: string }>();
    return row === null ? notFound() : rawJson(`{"data":${row.data}}`);
  }
  if (method === "PUT") return updateMessage(request, env, sid, aid, messageId);
  return methodNotAllowed(["GET", "PUT"]);
}

interface SessionListRow {
  session_id: string;
  created_at: string;
  updated_at: string;
  meta: string;
  message_count: number;
}

/** GET /hub/sessions?limit= — most recently updated first. */
async function listSessions(env: StoreEnv, url: URL): Promise<Response> {
  const limit = intParam(url, "limit", DEFAULT_SESSIONS_LIMIT);
  if (limit === null || limit < 1 || limit > MAX_SESSIONS_LIMIT) {
    return badRequest(`limit must be an integer from 1 to ${MAX_SESSIONS_LIMIT}`);
  }
  const { results } = await env.DB.prepare(
    "SELECT s.session_id, s.created_at, s.updated_at, s.meta, " +
      "(SELECT COUNT(*) FROM messages m WHERE m.session_id = s.session_id) AS message_count " +
      "FROM sessions s ORDER BY s.rev DESC LIMIT ?1",
  )
    .bind(limit)
    .all<SessionListRow>();
  const items = results.map(
    (row) =>
      `{"session_id":${JSON.stringify(row.session_id)},"created_at":${JSON.stringify(row.created_at)},` +
      `"updated_at":${JSON.stringify(row.updated_at)},"meta":${row.meta},"message_count":${row.message_count}}`,
  );
  return rawJson(`{"sessions":[${items.join(",")}]}`);
}

/** POST /hub/sessions: `{session_id, data}`. */
async function createSession(request: Request, env: StoreEnv): Promise<Response> {
  const read = await readData(request);
  if (!read.ok) return read.response;
  const sid = read.body.session_id;
  if (typeof sid !== "string" || !ID.test(sid)) {
    return badRequest("session_id must match ^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$");
  }
  const now = nowIso();
  try {
    await env.DB.prepare(
      "INSERT INTO sessions (session_id, data, meta, created_at, updated_at, rev) " +
        `VALUES (?1, ?2, '{}', ?3, ?3, ${NEXT_REV})`,
    )
      .bind(sid, read.data, now)
      .run();
  } catch (err) {
    if (isUniqueViolation(err)) return exists();
    throw err;
  }
  return created();
}

async function readMeta(env: StoreEnv, sid: string): Promise<Response> {
  const row = await env.DB.prepare("SELECT meta FROM sessions WHERE session_id = ?1")
    .bind(sid)
    .first<{ meta: string }>();
  return rawJson(`{"meta":${row?.meta ?? "{}"}}`);
}

/** PATCH /hub/sessions/<sid>/meta: a shallow merge; creates the session when missing. */
async function patchMeta(request: Request, env: StoreEnv, sid: string): Promise<Response> {
  const body = await readJsonObject(request, MAX_DOCUMENT_BYTES);
  if (!body.ok) return body.response;
  const patch = body.value.meta;
  if (!isObject(patch)) return badRequest('body must be {"meta": {...}}');
  const row = await env.DB.prepare("SELECT meta FROM sessions WHERE session_id = ?1")
    .bind(sid)
    .first<{ meta: string }>();
  const current: unknown = row === null ? {} : JSON.parse(row.meta);
  const merged = { ...(isObject(current) ? current : {}), ...patch };
  await upsertSession(env, sid, nowIso(), JSON.stringify(merged)).run();
  return json({ meta: merged });
}

async function listEvents(env: StoreEnv, sid: string): Promise<Response> {
  const { results } = await env.DB.prepare(
    "SELECT data FROM events WHERE session_id = ?1 ORDER BY seq",
  )
    .bind(sid)
    .all<{ data: string }>();
  return rawJson(`{"events":[${results.map((row) => row.data).join(",")}]}`);
}

/** POST /hub/sessions/<sid>/events: `{data}`; creates the session when missing. */
async function appendEvent(request: Request, env: StoreEnv, sid: string): Promise<Response> {
  const read = await readData(request);
  if (!read.ok) return read.response;
  await env.DB.batch([
    upsertSession(env, sid, nowIso()),
    env.DB.prepare("INSERT INTO events (session_id, data) VALUES (?1, ?2)").bind(sid, read.data),
  ]);
  return created();
}

/** POST /hub/sessions/<sid>/agents: `{agent_id, data}`. */
async function createAgent(request: Request, env: StoreEnv, sid: string): Promise<Response> {
  const read = await readData(request);
  if (!read.ok) return read.response;
  const aid = read.body.agent_id;
  if (typeof aid !== "string" || !ID.test(aid)) {
    return badRequest("agent_id must match ^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$");
  }
  if (!(await sessionExists(env, sid))) return notFound();
  try {
    await env.DB.batch([
      env.DB.prepare("INSERT INTO agents (session_id, agent_id, data) VALUES (?1, ?2, ?3)").bind(
        sid,
        aid,
        read.data,
      ),
      touch(env, sid, nowIso()),
    ]);
  } catch (err) {
    if (isUniqueViolation(err)) return exists();
    throw err;
  }
  return created();
}

/** PUT /hub/sessions/<sid>/agents/<aid>: `{data}`. */
async function updateAgent(
  request: Request,
  env: StoreEnv,
  sid: string,
  aid: string,
): Promise<Response> {
  const read = await readData(request);
  if (!read.ok) return read.response;
  const result = await env.DB.prepare(
    "UPDATE agents SET data = ?3 WHERE session_id = ?1 AND agent_id = ?2",
  )
    .bind(sid, aid, read.data)
    .run();
  if ((result.meta.changes ?? 0) === 0) return notFound();
  await touch(env, sid, nowIso()).run();
  return ok();
}

/** POST /hub/sessions/<sid>/agents/<aid>/messages: `{message_id, data}`. */
async function createMessage(
  request: Request,
  env: StoreEnv,
  sid: string,
  aid: string,
): Promise<Response> {
  const read = await readData(request);
  if (!read.ok) return read.response;
  const mid = read.body.message_id;
  if (!Number.isSafeInteger(mid) || (mid as number) < 0) {
    return badRequest("message_id must be a non-negative integer");
  }
  if (!(await agentExists(env, sid, aid))) return notFound();
  try {
    await env.DB.batch([
      env.DB.prepare(
        "INSERT INTO messages (session_id, agent_id, message_id, data) VALUES (?1, ?2, ?3, ?4)",
      ).bind(sid, aid, mid, read.data),
      touch(env, sid, nowIso()),
    ]);
  } catch (err) {
    if (isUniqueViolation(err)) return exists();
    throw err;
  }
  return created();
}

/** PUT /hub/sessions/<sid>/agents/<aid>/messages/<mid>: `{data}`. */
async function updateMessage(
  request: Request,
  env: StoreEnv,
  sid: string,
  aid: string,
  mid: number,
): Promise<Response> {
  const read = await readData(request);
  if (!read.ok) return read.response;
  const result = await env.DB.prepare(
    "UPDATE messages SET data = ?4 WHERE session_id = ?1 AND agent_id = ?2 AND message_id = ?3",
  )
    .bind(sid, aid, mid, read.data)
    .run();
  if ((result.meta.changes ?? 0) === 0) return notFound();
  await touch(env, sid, nowIso()).run();
  return ok();
}

/** GET .../messages?offset=&limit= — ordered by message id; without limit all (≤ 10 000). */
async function listMessages(env: StoreEnv, url: URL, sid: string, aid: string): Promise<Response> {
  const offset = intParam(url, "offset", 0);
  const limit = intParam(url, "limit", MAX_MESSAGES);
  if (offset === null) return badRequest("offset must be a non-negative integer");
  if (limit === null) return badRequest("limit must be a non-negative integer");
  if (!(await agentExists(env, sid, aid))) return notFound();
  const { results } = await env.DB.prepare(
    "SELECT data FROM messages WHERE session_id = ?1 AND agent_id = ?2 " +
      "ORDER BY message_id LIMIT ?3 OFFSET ?4",
  )
    .bind(sid, aid, Math.min(limit, MAX_MESSAGES), offset)
    .all<{ data: string }>();
  return rawJson(`{"messages":[${results.map((row) => row.data).join(",")}]}`);
}
