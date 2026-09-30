/**
 * Sub-tau definitions in tau-host (ADR 0012, ADR 0013 §3 and §5).
 *
 * The same fields as tau-sub's `persona/subs/<name>.md`, kept as rows in the tau's Durable
 * Object instead of files, plus the web fields of ADR 0013:
 *
 *   name         ^[a-z][a-z0-9-]{1,30}$, not one of the reserved names
 *   about        one line, at most 200 characters
 *   persona      the specialist's character and task, at most 20 000 characters
 *   role         brain | fast (a hosted tau has no local model)
 *   public       contacts and visitors may reach it (false by default)
 *   public_note  what it may share about its owner with them (the `## User` of their turns)
 *   web          a chat page for anonymous visitors; meaningful only with public
 *   web_daily    visitor turns per UTC day, 1–1000, 50 by default
 *   starters     up to 4 suggested first messages, each 1–80 characters
 *
 * A hosted tau offers no tools to sub-taus: its only tools are ask_sub and create_sub, which
 * a sub-tau may never use, so a sub-tau works with conversation alone.
 *
 * Every message is plain English for the owner's app, which shows it as it is.
 */

import type { ModelRole } from "../providers/types";

export const NAME_RE = /^[a-z][a-z0-9-]{1,30}$/;
/** Route names of the host and the universe that a sub-tau can never be called. */
export const RESERVED_NAMES: ReadonlySet<string> = new Set(["net", "app", "api", "auth", "claim", "hub"]);
export const ABOUT_LIMIT = 200;
export const PERSONA_LIMIT = 20_000;
export const PUBLIC_NOTE_LIMIT = 4_000;
export const WEB_DAILY_DEFAULT = 50;
export const WEB_DAILY_MIN = 1;
export const WEB_DAILY_MAX = 1000;
export const STARTERS_MAX = 4;
export const STARTER_LIMIT = 80;

export interface SubTau {
  name: string;
  about: string;
  persona: string;
  role: ModelRole;
  public: boolean;
  public_note: string;
  web: boolean;
  web_daily: number;
  starters: string[];
}

export class SubTauError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "SubTauError";
  }
}

/** Checks a name; returns it or throws a SubTauError that says what is wrong. */
export function validateName(name: unknown): string {
  if (typeof name !== "string" || !NAME_RE.test(name)) {
    throw new SubTauError(
      `Invalid sub-tau name ${JSON.stringify(name)}: use 2 to 31 characters (lowercase letters, digits and '-'), starting with a letter.`,
    );
  }
  if (RESERVED_NAMES.has(name)) {
    throw new SubTauError(`/${name} is a reserved name; pick another one.`);
  }
  return name;
}

function line(text: string): string {
  return text.split(/\s+/).filter(Boolean).join(" ");
}

/**
 * A complete, normalized definition from untrusted input (the app, the brain's draft or a
 * create_sub call). Missing optional fields take their defaults; wrong types and values
 * throw.
 */
export function validateSub(input: Record<string, unknown>): SubTau {
  const name = validateName(input.name);
  if (typeof input.about !== "string") throw new SubTauError(`/${name}: 'about' must be text.`);
  const about = line(input.about);
  if (!about) throw new SubTauError(`/${name}: 'about' is empty; say in one line what /${name} does.`);
  if (about.length > ABOUT_LIMIT) {
    throw new SubTauError(`/${name}: 'about' is ${about.length} characters; the limit is ${ABOUT_LIMIT}.`);
  }
  if (typeof input.persona !== "string") throw new SubTauError(`/${name}: the persona must be text.`);
  const persona = input.persona.replaceAll("\r\n", "\n").trim();
  if (!persona.replace(/<!--[\s\S]*?-->/g, "").trim()) {
    throw new SubTauError(`/${name}: the persona is empty; describe the specialist's character and task.`);
  }
  if (persona.length > PERSONA_LIMIT) {
    throw new SubTauError(`/${name}: the persona is ${persona.length} characters; the limit is ${PERSONA_LIMIT}.`);
  }
  const role = input.role ?? "brain";
  if (role !== "brain" && role !== "fast") {
    throw new SubTauError(`/${name}: unknown role ${JSON.stringify(role)}; use brain or fast.`);
  }
  const flag = (key: string): boolean => {
    const value = input[key] ?? false;
    if (typeof value !== "boolean") throw new SubTauError(`/${name}: '${key}' must be true or false.`);
    return value;
  };
  const isPublic = flag("public");
  const web = flag("web");
  const noteRaw = input.public_note ?? "";
  if (typeof noteRaw !== "string") throw new SubTauError(`/${name}: 'public_note' must be text.`);
  const publicNote = noteRaw.replaceAll("\r\n", "\n").trim();
  if (publicNote.length > PUBLIC_NOTE_LIMIT) {
    throw new SubTauError(
      `/${name}: the public note is ${publicNote.length} characters; the limit is ${PUBLIC_NOTE_LIMIT}.`,
    );
  }
  const daily = input.web_daily ?? WEB_DAILY_DEFAULT;
  if (typeof daily !== "number" || !Number.isInteger(daily) || daily < WEB_DAILY_MIN || daily > WEB_DAILY_MAX) {
    throw new SubTauError(`/${name}: 'web_daily' must be a whole number from ${WEB_DAILY_MIN} to ${WEB_DAILY_MAX}.`);
  }
  const startersRaw = input.starters ?? [];
  if (!Array.isArray(startersRaw)) throw new SubTauError(`/${name}: 'starters' must be a list of texts.`);
  const starters: string[] = [];
  for (const starter of startersRaw) {
    if (typeof starter !== "string") throw new SubTauError(`/${name}: every starter must be text.`);
    const text = line(starter);
    if (!text) continue;
    if (text.length > STARTER_LIMIT) {
      throw new SubTauError(`/${name}: a starter is ${text.length} characters; the limit is ${STARTER_LIMIT}.`);
    }
    if (!starters.includes(text)) starters.push(text);
  }
  if (starters.length > STARTERS_MAX) {
    throw new SubTauError(`/${name}: at most ${STARTERS_MAX} starters.`);
  }
  return {
    name,
    about,
    persona,
    role,
    public: isPublic,
    public_note: publicNote,
    web,
    web_daily: daily,
    starters,
  };
}

/** Visitors may talk to it: public and web. */
export function isWebSub(sub: SubTau): boolean {
  return sub.public && sub.web;
}

export interface SubTemplate {
  id: string;
  about: string;
  persona: string;
}

/**
 * Starting points for a new sub-tau (English: the persona is a prompt, and the persona's
 * language rule makes the sub-tau answer in the owner's language). `blank` matches tau-sub's
 * template.
 */
export const TEMPLATES: readonly SubTemplate[] = [
  {
    id: "blank",
    about: "A specialist of your tau; say in one line what it does.",
    persona:
      "Help your owner with the task in your about line. Keep answers short and concrete, and ask one short question when something important is unclear.",
  },
  {
    id: "coach",
    about: "A strict but kind workout coach who plans short sessions.",
    persona:
      "You plan short, safe workouts for your owner and adjust them to how the last ones went. Ask about time, equipment and any pain before you plan. Keep each plan to a few exercises with sets, reps and rest. You do not give medical advice; for pain or injury you say to see a professional.",
  },
  {
    id: "writer",
    about: "Turns rough notes into clear, short texts.",
    persona:
      "You turn your owner's rough notes into clear, short texts: messages, posts, landing-page copy. Ask who the reader is and what they should do after reading when it is not clear. Offer one version first and change it on request. Keep the owner's voice; do not invent facts.",
  },
  {
    id: "tutor",
    about: "Explains one topic step by step and checks understanding.",
    persona:
      "You explain one topic at a time, step by step, starting from what your owner already knows. Ask one question to find the starting point. Use small examples, then check understanding with a short question. Say plainly when you are not sure.",
  },
];
