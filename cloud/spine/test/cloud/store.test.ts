import { createScheduledController } from "cloudflare:test";
import { env } from "cloudflare:workers";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { brainEnvVars } from "../../src/brain";
import type { SpineEnv } from "../../src/env";
import worker from "../../src/index";
import { hub, resetStore, SELF, TOKEN } from "../helpers";

beforeEach(resetStore);

async function body<T = Record<string, unknown>>(res: Response): Promise<T> {
  return (await res.json()) as T;
}

describe("cloud mode", () => {
  it("reports mode cloud", async () => {
    expect(await body(await hub("/hub/health"))).toMatchObject({ mode: "cloud" });
  });

  it("keeps only the cloud store in D1; the mailbox stays in the Durable Object", async () => {
    const { results } = await env.DB.prepare(
      "SELECT name FROM sqlite_master WHERE type = 'table' " +
        "AND name NOT LIKE 'sqlite_%' AND name NOT LIKE '_cf_%' AND name != 'd1_migrations' " +
        "ORDER BY name",
    ).all<{ name: string }>();
    expect(results.map((row) => row.name)).toEqual([
      "agents",
      "events",
      "messages",
      "sessions",
      "state",
    ]);
  });
});

describe("state", () => {
  it("puts, gets and deletes JSON documents", async () => {
    expect((await hub("/hub/state/net.contacts")).status).toBe(404);

    const value = { alice: { state: "accepted", n: [1, 2, 3] }, ü: null };
    const put = await hub("/hub/state/net.contacts", { method: "PUT", body: { value } });
    expect(put.status).toBe(200);
    const { key, updated_at } = await body<{ key: string; updated_at: number }>(put);
    expect(key).toBe("net.contacts");
    expect(Number.isInteger(updated_at)).toBe(true);

    expect(await body(await hub("/hub/state/net.contacts"))).toEqual({
      key: "net.contacts",
      value,
      updated_at,
    });

    for (const scalar of [0, "text", null, [1, "two"], false]) {
      await hub("/hub/state/net.cursor", { method: "PUT", body: { value: scalar } });
      expect((await body(await hub("/hub/state/net.cursor"))).value).toEqual(scalar);
    }

    expect(await body(await hub("/hub/state/net.contacts", { method: "DELETE" }))).toEqual({
      deleted: true,
    });
    expect(await body(await hub("/hub/state/net.contacts", { method: "DELETE" }))).toEqual({
      deleted: false,
    });
    expect((await hub("/hub/state/net.contacts")).status).toBe(404);
  });

  it("validates keys and bodies", async () => {
    for (const bad of ["Upper", "-dash", "a".repeat(129), "sp%20ace"]) {
      expect((await hub(`/hub/state/${bad}`)).status, bad).toBe(400);
    }
    expect((await hub("/hub/state/a:b-c_d.e")).status).toBe(404);
    expect((await hub("/hub/state/k", { method: "PUT", body: { nope: 1 } })).status).toBe(400);
    expect((await hub("/hub/state/k", { method: "PUT", raw: "{not json" })).status).toBe(400);
  });

  it("413 above 1 MiB", async () => {
    const res = await hub("/hub/state/big", {
      method: "PUT",
      body: { value: "x".repeat(1_048_576) },
    });
    expect(res.status).toBe(413);
    expect(await res.json()).toEqual({ error: "too_large" });
  });
});

describe("files", () => {
  it("stores the allowed files as text", async () => {
    expect(await body(await hub("/hub/files"))).toEqual({ files: [] });
    expect((await hub("/hub/files/tau.toml")).status).toBe(404);

    const toml = '[ui]\nlanguage = "tr"\n# ç\n';
    const put = await hub("/hub/files/tau.toml", { method: "PUT", raw: toml });
    expect(put.status).toBe(200);
    const meta = await body<{ name: string; size: number; updated_at: number }>(put);
    expect(meta).toMatchObject({ name: "tau.toml", size: new TextEncoder().encode(toml).length });

    const get = await hub("/hub/files/tau.toml");
    expect(get.headers.get("content-type")).toBe("text/plain; charset=utf-8");
    expect(await get.text()).toBe(toml);

    await hub("/hub/files/persona/user.md", { method: "PUT", raw: "# me" });
    expect(await body(await hub("/hub/files"))).toEqual({
      files: [meta, { name: "persona/user.md", size: 4, updated_at: expect.any(Number) }],
    });
    // Encoded slashes name the same file.
    expect(await (await hub("/hub/files/persona%2Fuser.md")).text()).toBe("# me");
  });

  it("404 for any other name", async () => {
    for (const name of ["other.txt", "persona%2F..%2Ftau.toml", "persona/soul.md", ".env"]) {
      expect((await hub(`/hub/files/${name}`, { method: "PUT", raw: "x" })).status, name).toBe(404);
    }
  });

  it("keeps sub-tau files under persona/subs/, listed after the fixed files", async () => {
    await hub("/hub/files/tau.toml", { method: "PUT", raw: "[ui]\n" });
    for (const name of ["coach.public.md", "coach.md", "landing.md", "A1_b-c.d.md"]) {
      const put = await hub(`/hub/files/persona/subs/${name}`, { method: "PUT", raw: `# ${name}` });
      expect(put.status, name).toBe(200);
      expect(await body(put)).toMatchObject({ name: `persona/subs/${name}` });
    }
    expect(await (await hub("/hub/files/persona/subs/coach.md")).text()).toBe("# coach.md");
    expect(await (await hub("/hub/files/persona%2Fsubs%2Fcoach.md")).text()).toBe("# coach.md");
    const listed = await body<{ files: { name: string; size: number }[] }>(await hub("/hub/files"));
    expect(listed.files.map((file) => file.name)).toEqual([
      "tau.toml",
      "persona/subs/A1_b-c.d.md",
      "persona/subs/coach.md",
      "persona/subs/coach.public.md",
      "persona/subs/landing.md",
    ]);
    expect(listed.files[2]).toEqual({
      name: "persona/subs/coach.md",
      size: 10,
      updated_at: expect.any(Number),
    });
  });

  it("refuses odd names under persona/subs/", async () => {
    const odd = [
      "persona/subs/",
      "persona/subs/.hidden.md",
      "persona/subs/Bad%20Name.md",
      "persona/subs/x.txt",
      "persona/subs/x.md.bak",
      "persona/subs/drafts/x.md",
      "persona/subs/drafts%2Fx.md",
      "persona/subs/..%2F..%2Ftau.toml",
      "persona/subs/..%2Fuser.md",
      "persona/subs/-x.md",
      `persona/subs/${"a".repeat(82)}.md`,
      "persona%2Fsubs%2F..%2Fuser.md",
    ];
    for (const name of odd) {
      expect((await hub(`/hub/files/${name}`, { method: "PUT", raw: "x" })).status, name).toBe(404);
      expect((await hub(`/hub/files/${name}`)).status, name).toBe(404);
      expect((await hub(`/hub/files/${name}`, { method: "DELETE" })).status, name).toBe(404);
    }
    expect(await body(await hub("/hub/files"))).toEqual({ files: [] });
    // The longest allowed name: 81 characters before ".md".
    const longest = `persona/subs/${"a".repeat(81)}.md`;
    expect((await hub(`/hub/files/${longest}`, { method: "PUT", raw: "x" })).status).toBe(200);
  });

  it("deletes a file", async () => {
    await hub("/hub/files/persona/subs/coach.md", { method: "PUT", raw: "x" });
    const deleted = await hub("/hub/files/persona/subs/coach.md", { method: "DELETE" });
    expect(await body(deleted)).toEqual({ deleted: true });
    expect(
      await body(await hub("/hub/files/persona/subs/coach.md", { method: "DELETE" })),
    ).toEqual({ deleted: false });
    expect((await hub("/hub/files/persona/subs/coach.md")).status).toBe(404);
    expect(await body(await hub("/hub/files"))).toEqual({ files: [] });
    const post = await hub("/hub/files/persona/subs/coach.md", { method: "POST", raw: "x" });
    expect(post.status).toBe(405);
    expect(post.headers.get("allow")).toBe("GET, PUT, DELETE");
  });

  it("413 above 512 KiB and 400 for invalid UTF-8", async () => {
    const big = await hub("/hub/files/persona/persona.md", {
      method: "PUT",
      raw: "x".repeat(524_289),
    });
    expect(big.status).toBe(413);
    const bytes = new Uint8Array([0xff, 0xfe, 0x41]);
    expect((await hub("/hub/files/persona/net.md", { method: "PUT", raw: bytes })).status).toBe(
      400,
    );
  });
});

describe("sessions", () => {
  const session = (sid: string) => ({
    session_id: sid,
    session_type: "AGENT",
    created_at: "2026-09-30T10:00:00+00:00",
    updated_at: "2026-09-30T10:00:00+00:00",
  });

  async function createSession(sid: string): Promise<Response> {
    return hub("/hub/sessions", { method: "POST", body: { session_id: sid, data: session(sid) } });
  }

  it("creates, reads and refuses duplicates", async () => {
    expect((await createSession("s1")).status).toBe(201);
    expect((await createSession("s1")).status).toBe(409);
    expect(await body(await hub("/hub/sessions/s1"))).toEqual({ data: session("s1") });
    expect((await hub("/hub/sessions/nope")).status).toBe(404);
    expect(
      (await hub("/hub/sessions", { method: "POST", body: { session_id: "../x", data: {} } }))
        .status,
    ).toBe(400);
    expect(
      (await hub("/hub/sessions", { method: "POST", body: { session_id: "s2" } })).status,
    ).toBe(400);
  });

  it("merges meta and creates the session when missing", async () => {
    expect(await body(await hub("/hub/sessions/s9/meta"))).toEqual({ meta: {} });
    const first = await hub("/hub/sessions/s9/meta", {
      method: "PATCH",
      body: { meta: { channel: "telegram", title: "hello" } },
    });
    expect(first.status).toBe(200);
    expect(await body(first)).toEqual({ meta: { channel: "telegram", title: "hello" } });
    const second = await hub("/hub/sessions/s9/meta", {
      method: "PATCH",
      body: { meta: { channel: "tui", role: "brain" } },
    });
    expect(await body(second)).toEqual({ meta: { channel: "tui", title: "hello", role: "brain" } });
    expect(await body(await hub("/hub/sessions/s9/meta"))).toEqual({
      meta: { channel: "tui", title: "hello", role: "brain" },
    });

    const { data } = await body<{ data: Record<string, string> }>(await hub("/hub/sessions/s9"));
    expect(data).toMatchObject({ session_id: "s9", session_type: "AGENT" });
    expect(new Date(data.created_at!).toISOString()).toBe(data.created_at);
    expect(data.updated_at).toBe(data.created_at);

    expect(
      (await hub("/hub/sessions/s9/meta", { method: "PATCH", body: { meta: [1] } })).status,
    ).toBe(400);
  });

  it("creates, reads and updates agents", async () => {
    const agent = { agent_id: "tau", state: {}, conversation_manager_state: {} };
    expect(
      (
        await hub("/hub/sessions/s1/agents", {
          method: "POST",
          body: { agent_id: "tau", data: agent },
        })
      ).status,
    ).toBe(404);
    await createSession("s1");
    const post = () =>
      hub("/hub/sessions/s1/agents", { method: "POST", body: { agent_id: "tau", data: agent } });
    expect((await post()).status).toBe(201);
    expect((await post()).status).toBe(409);
    expect(await body(await hub("/hub/sessions/s1/agents/tau"))).toEqual({ data: agent });
    expect((await hub("/hub/sessions/s1/agents/other")).status).toBe(404);

    const changed = { ...agent, state: { k: 1 } };
    expect(
      (await hub("/hub/sessions/s1/agents/tau", { method: "PUT", body: { data: changed } })).status,
    ).toBe(200);
    expect(await body(await hub("/hub/sessions/s1/agents/tau"))).toEqual({ data: changed });
    expect(
      (await hub("/hub/sessions/s1/agents/other", { method: "PUT", body: { data: {} } })).status,
    ).toBe(404);
  });

  it("stores messages by id and lists them in order with offset and limit", async () => {
    await createSession("s1");
    await hub("/hub/sessions/s1/agents", { method: "POST", body: { agent_id: "tau", data: {} } });
    const base = "/hub/sessions/s1/agents/tau/messages";
    expect(
      (
        await hub("/hub/sessions/s1/agents/ghost/messages", {
          method: "POST",
          body: { message_id: 0, data: {} },
        })
      ).status,
    ).toBe(404);
    expect((await hub("/hub/sessions/s1/agents/ghost/messages")).status).toBe(404);

    // Out of order on purpose: the listing is ordered by message id.
    for (const id of [2, 0, 10, 1]) {
      const res = await hub(base, {
        method: "POST",
        body: { message_id: id, data: { message_id: id } },
      });
      expect(res.status).toBe(201);
    }
    expect((await hub(base, { method: "POST", body: { message_id: 1, data: {} } })).status).toBe(
      409,
    );
    expect((await hub(base, { method: "POST", body: { message_id: -1, data: {} } })).status).toBe(
      400,
    );

    const ids = async (query: string) =>
      (
        await body<{ messages: { message_id: number }[] }>(await hub(`${base}${query}`))
      ).messages.map((m) => m.message_id);
    expect(await ids("")).toEqual([0, 1, 2, 10]);
    expect(await ids("?offset=1")).toEqual([1, 2, 10]);
    expect(await ids("?offset=1&limit=2")).toEqual([1, 2]);
    expect(await ids("?limit=0")).toEqual([]);
    expect(await ids("?offset=9")).toEqual([]);

    expect(await body(await hub(`${base}/10`))).toEqual({ data: { message_id: 10 } });
    expect((await hub(`${base}/3`)).status).toBe(404);
    expect((await hub(`${base}/x`)).status).toBe(400);
    expect(
      (await hub(`${base}/2`, { method: "PUT", body: { data: { edited: true } } })).status,
    ).toBe(200);
    expect(await body(await hub(`${base}/2`))).toEqual({ data: { edited: true } });
    expect((await hub(`${base}/3`, { method: "PUT", body: { data: {} } })).status).toBe(404);
  });

  it("appends events in insertion order and creates the session when missing", async () => {
    for (const n of [3, 1, 2]) {
      const res = await hub("/hub/sessions/ev/events", {
        method: "POST",
        body: { data: { kind: "notice", n } },
      });
      expect(res.status).toBe(201);
    }
    const { events } = await body<{ events: { n: number }[] }>(
      await hub("/hub/sessions/ev/events"),
    );
    expect(events.map((e) => e.n)).toEqual([3, 1, 2]);
    expect((await hub("/hub/sessions/ev")).status).toBe(200);
    expect(await body(await hub("/hub/sessions/none/events"))).toEqual({ events: [] });
  });

  it("lists the most recently updated first, with meta and message_count", async () => {
    await createSession("a");
    await createSession("b");
    await createSession("c");
    await hub("/hub/sessions/a/agents", { method: "POST", body: { agent_id: "tau", data: {} } });
    await hub("/hub/sessions/a/agents", { method: "POST", body: { agent_id: "helper", data: {} } });
    await hub("/hub/sessions/a/agents/tau/messages", {
      method: "POST",
      body: { message_id: 0, data: {} },
    });
    await hub("/hub/sessions/a/agents/helper/messages", {
      method: "POST",
      body: { message_id: 0, data: {} },
    });
    await hub("/hub/sessions/b/meta", { method: "PATCH", body: { meta: { title: "bee" } } });

    type Row = {
      session_id: string;
      created_at: string;
      updated_at: string;
      meta: object;
      message_count: number;
    };
    const list = async (query = "") =>
      (await body<{ sessions: Row[] }>(await hub(`/hub/sessions${query}`))).sessions;

    let rows = await list();
    expect(rows.map((r) => r.session_id)).toEqual(["b", "a", "c"]);
    expect(rows[0]).toMatchObject({ meta: { title: "bee" }, message_count: 0 });
    expect(rows[1]).toMatchObject({ meta: {}, message_count: 2 });
    expect(Object.keys(rows[0]!).sort()).toEqual([
      "created_at",
      "message_count",
      "meta",
      "session_id",
      "updated_at",
    ]);
    expect(new Date(rows[0]!.updated_at).toISOString()).toBe(rows[0]!.updated_at);

    // Every write moves the session up: agent update, message update, event.
    await hub("/hub/sessions/c/events", { method: "POST", body: { data: {} } });
    expect((await list()).map((r) => r.session_id)).toEqual(["c", "b", "a"]);
    await hub("/hub/sessions/a/agents/tau", { method: "PUT", body: { data: { x: 1 } } });
    expect((await list()).map((r) => r.session_id)).toEqual(["a", "c", "b"]);
    await hub("/hub/sessions/c/meta", { method: "PATCH", body: { meta: {} } });
    rows = await list("?limit=2");
    expect(rows.map((r) => r.session_id)).toEqual(["c", "a"]);

    for (const query of ["?limit=0", "?limit=201", "?limit=x"]) {
      expect((await hub(`/hub/sessions${query}`)).status, query).toBe(400);
    }
  });

  it("413 for a body above 1 MiB", async () => {
    const res = await hub("/hub/sessions", {
      method: "POST",
      body: { session_id: "big", data: { blob: "x".repeat(1_048_576) } },
    });
    expect(res.status).toBe(413);
  });

  it("400 for invalid ids in the path", async () => {
    expect((await hub("/hub/sessions/..%2Fx")).status).toBe(400);
    expect((await hub("/hub/sessions/s1/agents/-x")).status).toBe(400);
  });
});

describe("brain", () => {
  function withBrain(health: () => Promise<{ status: number; body: string }>) {
    const BRAIN = { getByName: () => ({ health }) } as unknown as SpineEnv["BRAIN"];
    return { ...env, BRAIN };
  }

  function brainRequest() {
    return new Request(`https://${SELF}/hub/brain`, {
      headers: { authorization: `Bearer ${TOKEN}` },
    });
  }

  it("503 brain_unavailable without a BRAIN binding", async () => {
    const res = await hub("/hub/brain");
    expect(res.status).toBe(503);
    expect(await res.json()).toEqual({ error: "brain_unavailable" });
  });

  it("proxies the container's /health JSON", async () => {
    const e = withBrain(async () => ({ status: 200, body: '{"ok":true,"services":["telegram"]}' }));
    const res = await worker.fetch(brainRequest(), e);
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ ok: true, services: ["telegram"] });
  });

  it("503 when the container fails, answers badly or cannot start", async () => {
    const answers = [
      async () => ({ status: 500, body: '{"ok":false}' }),
      async () => ({ status: 200, body: "not json" }),
      async () => {
        throw new Error("no container");
      },
    ];
    for (const health of answers) {
      const res = await worker.fetch(brainRequest(), withBrain(health));
      expect(res.status).toBe(503);
      expect(await res.json()).toEqual({ error: "brain_unavailable" });
    }
  });

  it("is pinged by the cron when KEEP_AWAKE=1", async () => {
    const health = vi.fn(async () => ({ status: 200, body: "{}" }));
    const controller = createScheduledController({ cron: "* * * * *" });
    await worker.scheduled(controller, withBrain(health));
    expect(health).toHaveBeenCalledTimes(1);
    await worker.scheduled(controller, { ...withBrain(health), KEEP_AWAKE: "0" });
    expect(health).toHaveBeenCalledTimes(1);
    // Without a BRAIN binding the cron still prunes and does not fail.
    await worker.scheduled(controller, env);
  });

  it("hands the spine URL, the token and the set secrets to the container", () => {
    const base = { ADDRESS: "", ALLOW_INSECURE_PEERS: "0" } as SpineEnv;
    expect(
      brainEnvVars({
        ...base,
        SPINE_URL: "https://tau.example.com/",
        HUB_TOKEN: "t0k3n",
        ANTHROPIC_API_KEY: "sk-test",
        OPENAI_API_KEY: "sk-openai",
        GEMINI_API_KEY: "gm-test",
        GOOGLE_API_KEY: "",
        TELEGRAM_BOT_TOKEN: "",
      }),
    ).toEqual({
      TAU_SPINE_URL: "https://tau.example.com",
      TAU_SPINE_TOKEN: "t0k3n",
      ANTHROPIC_API_KEY: "sk-test",
      OPENAI_API_KEY: "sk-openai",
      GEMINI_API_KEY: "gm-test",
    });
    expect(brainEnvVars({ ...base, GOOGLE_API_KEY: "g-test" })).toEqual({
      GOOGLE_API_KEY: "g-test",
    });
    expect(brainEnvVars({ ...base, ADDRESS: "tau.example.com" })).toEqual({
      TAU_SPINE_URL: "https://tau.example.com",
    });
    expect(brainEnvVars(base)).toEqual({});
  });
});
