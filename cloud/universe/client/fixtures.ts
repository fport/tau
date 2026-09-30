/**
 * Development fixtures: an example universe for the pages when `?fixture=1` is on at
 * localhost (see client/api.ts). Loaded on demand, never on a real host.
 *
 * Everything here is made up: example.com addresses, alice, bob and friends. The visitor
 * chat answers from a script after a short delay, and one answer carries markup so the page
 * can be seen printing it as text.
 */

import type {
  ChatMessage,
  ChatPoll,
  ChatSent,
  ClaimResult,
  PageSub,
  PersonView,
  SiteSnapshot,
  SnapshotSub,
  SnapshotTau,
  SubView,
} from "./types";

const NOW = Math.floor(Date.now() / 1000);
const DAY = 86_400;

interface FixtureSub {
  name: string;
  about: string;
  web: boolean;
  starters: string[];
  age: number;
  slug: string | null;
}

interface FixtureTau {
  address: string;
  name: string;
  owner: string;
  about: string;
  handle: string | null;
  online: boolean;
  age: number;
  subs: FixtureSub[];
}

const sub = (
  name: string,
  about: string,
  web: boolean,
  starters: string[] = [],
  age = 20,
  slug: string | null = name,
): FixtureSub => ({ name, about, web, starters, age, slug });

const TAUS: FixtureTau[] = [
  {
    address: "alice.example.com",
    name: "Alice’s tau",
    owner: "Alice",
    about: "Runs, reads and builds small robots.",
    handle: "alice",
    online: true,
    age: 64,
    subs: [
      sub("coach", "A patient running coach for beginners.", true, [
        "What can you do?",
        "Plan my first week",
        "I have bad knees",
        "Surprise me",
      ]),
      sub("landing", "Writes landing pages that say one thing well.", false, [], 30),
      sub("reader", "Talks about the book you are reading, without spoilers.", true, [
        "Recommend a short novel",
        "Who made you?",
      ]),
    ],
  },
  {
    address: "bob.example.net",
    name: "Bob’s tau",
    owner: "Bob",
    about: "Cooking, calendars and a very old synthesiser.",
    handle: "bob",
    online: true,
    age: 50,
    subs: [
      sub("chef", "Turns what is in your fridge into dinner.", true, [
        "Eggs, rice, spinach",
        "Something for two",
      ]),
    ],
  },
  {
    address: "tau.example.com/@carol",
    name: "Carol’s tau",
    owner: "Carol",
    about: "Hosted. Maths homework and bad puns.",
    handle: "carol",
    online: true,
    age: 12,
    subs: [
      sub("tutor", "Explains maths step by step, and asks before it tells.", true, [
        "Why is 0.999… equal to 1?",
        "Quiz me on fractions",
      ]),
    ],
  },
  {
    address: "dave.example.org",
    name: "Dave’s tau",
    owner: "Dave",
    about: "",
    handle: null,
    online: false,
    age: 40,
    subs: [sub("arm", "Drives a desk robot arm, in simulation.", false, [], 35)],
  },
  {
    address: "erin.example.com",
    name: "Erin’s tau",
    owner: "Erin",
    about: "Birds, maps and weekend hikes.",
    handle: "erin",
    online: false,
    age: 22,
    subs: [
      sub("scout", "Plans a day hike from a map and the weather.", true, ["A loop near a lake"]),
    ],
  },
  {
    address: "workshop.example.com",
    name: "Workshop",
    owner: "Frank",
    about: "The tau in the garage.",
    handle: null,
    online: true,
    age: 33,
    subs: [],
  },
  {
    address: "lab.example.com",
    name: "Lab",
    owner: "Frank",
    about: "Sensors, printers and one cat.",
    handle: null,
    online: true,
    age: 31,
    subs: [],
  },
  {
    address: "tau.example.com/@grace",
    name: "Grace’s tau",
    owner: "Grace",
    about: "Hosted. Poems on request.",
    handle: "grace",
    online: true,
    age: 5,
    subs: [sub("poet", "Short poems about ordinary things.", true, ["A poem about Mondays"], 4)],
  },
  {
    address: "heidi.example.net",
    name: "tau",
    owner: "",
    about: "",
    handle: null,
    online: false,
    age: 9,
    subs: [],
  },
];

const LINKS: [string, string, number][] = [
  ["alice.example.com", "bob.example.net", 42],
  ["alice.example.com", "tau.example.com/@carol", 12],
  ["alice.example.com", "erin.example.com", 5],
  ["bob.example.net", "dave.example.org", 3],
  ["bob.example.net", "tau.example.com/@grace", 2],
  ["tau.example.com/@carol", "tau.example.com/@grace", 7],
  ["lab.example.com", "workshop.example.com", 20],
];

const HOSTED = (tau: FixtureTau) => tau.address.startsWith("tau.example.com/@");

function pageSub(tau: FixtureTau, s: FixtureSub): PageSub {
  const path =
    s.slug !== null ? `/${s.slug}` : tau.handle !== null ? `/@${tau.handle}/${s.name}` : null;
  return {
    name: s.name,
    about: s.about,
    web: s.web,
    starters: s.starters,
    first_seen: NOW - s.age * DAY,
    slug: s.slug,
    path,
    url: path === null ? null : `${window.location.origin}${path}`,
  };
}

function snapshot(): SiteSnapshot {
  const taus: SnapshotTau[] = TAUS.map((tau) => ({
    address: tau.address,
    name: tau.name,
    owner: tau.owner,
    about: tau.about,
    joined_at: NOW - tau.age * DAY,
    last_seen: tau.online ? NOW - 900 : NOW - 5 * 3_600,
    online: tau.online,
    handle: tau.handle,
    subs: tau.subs.map((s): SnapshotSub => {
      const { name, about, web, starters, first_seen, slug } = pageSub(tau, s);
      return { name, about, web, starters, first_seen, slug };
    }),
  }));
  const links = LINKS.map(([a, b, messages]) => (a < b ? { a, b, messages } : { a: b, b: a, messages }));
  return {
    universe: window.location.host,
    generated_at: NOW,
    stats: {
      taus: taus.length,
      online: taus.filter((tau) => tau.online).length,
      messages: links.reduce((sum, link) => sum + link.messages, 0),
    },
    taus,
    links,
  };
}

function linksOf(address: string): { peer: string; messages: number }[] {
  return LINKS.filter(([a, b]) => a === address || b === address).map(([a, b, messages]) => ({
    peer: a === address ? b : a,
    messages,
  }));
}

function person(handle: string): PersonView | null {
  const tau = TAUS.find((candidate) => candidate.handle === handle);
  if (tau === undefined) return null;
  const links = linksOf(tau.address);
  return {
    handle,
    github: `https://github.com/${handle}`,
    building_since: NOW - tau.age * DAY,
    counts: {
      subs: tau.subs.length,
      links: links.length,
      messages: links.reduce((sum, link) => sum + link.messages, 0),
    },
    address: tau.address,
    name: tau.name,
    owner: tau.owner,
    about: tau.about,
    joined_at: NOW - tau.age * DAY,
    last_seen: tau.online ? NOW - 900 : NOW - 5 * 3_600,
    online: tau.online,
    hosted: HOSTED(tau),
    subs: tau.subs.map((s) => pageSub(tau, s)),
    links: links.map((link) => {
      const peer = TAUS.find((candidate) => candidate.address === link.peer);
      return {
        peer: link.peer,
        messages: link.messages,
        name: peer?.name ?? link.peer,
        handle: peer?.handle ?? null,
        online: peer?.online ?? false,
      };
    }),
  };
}

function subView(target: string): SubView | null {
  for (const tau of TAUS) {
    for (const s of tau.subs) {
      const bySlug = s.slug === target;
      const byHandle = tau.handle !== null && target === `@${tau.handle}/${s.name}`;
      if (!bySlug && !byHandle) continue;
      return {
        ...pageSub(tau, s),
        online: tau.online,
        owner: { handle: tau.handle, name: tau.owner, address: tau.address },
        hosted: HOSTED(tau),
      };
    }
  }
  return null;
}

// ---------------------------------------------------------------------------------------
// The visitor chat: threads in memory, scripted answers.

interface Thread {
  target: string;
  messages: ChatMessage[];
  pending: number;
}

const threads = new Map<string, Thread>();
let nextThread = 1;

function answer(target: string, text: string): string {
  const name = target.split("/").pop() ?? target;
  if (/<|>/.test(text)) {
    return `You wrote markup: ${text}\nIt stays text here, like everything a sub-tau says. <b>Not bold.</b>`;
  }
  if (/can you do/i.test(text)) {
    return `I’m ${name}, a fixture. On a real universe I answer with my owner’s model and within their daily cap.\n\nTry another starter, or type anything.`;
  }
  if (/who made/i.test(text)) return "Someone with a tau and a keyboard. The universe relays us.";
  return `(${name}, fixture) You said: “${text.slice(0, 140)}”. A real answer would come from the owner’s tau.`;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function chatPost(target: string, body: unknown): { status: number; data: unknown } {
  const view = subView(target);
  if (view === null) return { status: 404, data: { error: "not_found" } };
  if (!view.web) return { status: 403, data: { error: "not_web" } };
  const input = (body ?? {}) as { text?: unknown; thread?: unknown };
  const text = typeof input.text === "string" ? input.text.trim() : "";
  if (text === "") return { status: 400, data: { error: "bad_request" } };
  if (text.length > 2000) return { status: 413, data: { error: "too_long" } };
  let id = typeof input.thread === "string" ? input.thread : "";
  let thread = threads.get(id);
  if (thread === undefined || thread.target !== target) {
    id = `fx-${nextThread++}`;
    thread = { target, messages: [], pending: 0 };
    threads.set(id, thread);
  }
  const n = thread.messages.length + 1;
  thread.messages.push({ n, from: "visitor", text, ts: Math.floor(Date.now() / 1000) });
  if (view.online || view.hosted) {
    thread.pending++;
    const current = thread;
    setTimeout(() => {
      current.messages.push({
        n: current.messages.length + 1,
        from: "sub",
        text: answer(target, text),
        ts: Math.floor(Date.now() / 1000),
      });
      current.pending--;
    }, 1400);
  }
  const sent: ChatSent = { thread: id, id: n };
  return { status: 200, data: sent };
}

async function chatPoll(target: string, id: string, after: number): Promise<{ status: number; data: unknown }> {
  const thread = threads.get(id);
  if (thread === undefined || thread.target !== target) return { status: 404, data: { error: "not_found" } };
  for (let waited = 0; waited < 3_000; waited += 200) {
    if (thread.messages.some((message) => message.n > after)) break;
    await sleep(200);
  }
  const poll: ChatPoll = {
    messages: thread.messages.filter((message) => message.n > after),
    done: thread.pending === 0,
  };
  return { status: 200, data: poll };
}

// ---------------------------------------------------------------------------------------

/** Answers a call of client/api.ts from the example universe. */
export async function fixtureFetch(
  method: "GET" | "POST",
  path: string,
  body?: unknown,
): Promise<{ status: number; data: unknown }> {
  await sleep(150);
  const url = new URL(path, window.location.origin);
  const route = decodeURIComponent(url.pathname);
  if (method === "GET" && route === "/api/universe") return { status: 200, data: snapshot() };

  const people = /^\/api\/people\/([^/]+)$/.exec(route);
  if (method === "GET" && people !== null) {
    const view = person(people[1]!.toLowerCase());
    return view === null ? { status: 404, data: { error: "not_found" } } : { status: 200, data: view };
  }

  const subs = /^\/api\/subs\/(.+)$/.exec(route);
  if (method === "GET" && subs !== null) {
    const view = subView(subs[1]!);
    return view === null ? { status: 404, data: { error: "not_found" } } : { status: 200, data: view };
  }

  const chat = /^\/api\/chat\/((?:@[^/]+\/)?[^/@]+)(?:\/([^/]+))?$/.exec(route);
  if (chat !== null) {
    const target = chat[1]!;
    if (method === "POST" && chat[2] === undefined) return chatPost(target, body);
    if (method === "GET" && chat[2] !== undefined) {
      return chatPoll(target, chat[2], Number(url.searchParams.get("after") ?? "0") || 0);
    }
  }

  if (method === "POST" && route === "/api/claim") {
    const result: ClaimResult = {
      ok: true,
      handle: "alice",
      url: `${window.location.origin}/@alice`,
      moved_from: null,
    };
    return { status: 200, data: result };
  }
  return { status: 404, data: { error: "not_found" } };
}

/** A claim link's fragment for the claim page to show when fixtures are on and it has none. */
export function fixtureClaim(): string {
  const payload = {
    v: 1,
    kind: "claim",
    universe: window.location.host,
    address: "alice.example.com",
    ts: Math.floor(Date.now() / 1000) - 120,
    nonce: "ZXhhbXBsZS1ub25jZQ",
  };
  const b64u = (text: string) =>
    btoa(String.fromCharCode(...new TextEncoder().encode(text)))
      .replaceAll("+", "-")
      .replaceAll("/", "_")
      .replace(/=+$/, "");
  const wire = { payload: b64u(JSON.stringify(payload)), sig: "A".repeat(86) };
  return b64u(JSON.stringify(wire));
}
