// What the wizard makes of a job's JSON lines (tested in events.test.ts):
//
// - `tau setup install|run --json`: `progress`, `log`, `check` (issue 173), `needs_ui`, then
//   one `done` or `error` (docs/reference/setup.md);
// - `tau telegram pair --json`: `note`, `bot`, `code`, `waiting`, `paired` or `error`
//   (docs/reference/cli.md);
// - `tau net spine deploy --json`: `type` = `progress`, `need_token`, `choose_account`, `error`
//   or `done` (docs/reference/tau-universe.md §4);
// - and the lines the app wraps itself: `text` (stdout that is not JSON) and `stderr`.

import type { JobEvent } from "./api";

const MAX_LOG = 400;

export type StepStatus =
  | "pending"
  | "running"
  | "checking"
  | "done"
  | "failed"
  | "skipped"
  | "info"
  | "needs_ui";

/** One item of a `check` event's checklist. */
export interface CheckItem {
  status: "ok" | "fail" | "warn" | "info";
  name?: string;
  label?: string;
  detail?: string;
  [key: string]: unknown;
}

/** What the owner does by hand (issue 173): the app shows it and never runs it. */
export interface HandAction {
  kind?: string;
  text?: string;
  command?: string | string[];
  sudo?: boolean;
  url?: string;
  changes?: string[];
  script?: string;
}

export interface CheckEvent {
  ok: boolean;
  summary: string;
  checks: CheckItem[];
  action: HandAction | null;
  values: Record<string, unknown>;
}

export interface StepView {
  id: string;
  label: string;
  status: StepStatus;
  detail?: string;
  reason?: string;
  text?: string;
  url?: string;
  command?: string[];
  code?: number;
  check?: CheckEvent;
}

export interface NeedsUi {
  feature: string;
  step: string;
  label: string;
  /** The words after `tau`. */
  command: string[];
  /** Present when the app runs the step itself. */
  argv?: string[];
  /** Present when the owner runs it by hand (no `argv`): never executed by the app. */
  action?: HandAction;
}

export interface LogLine {
  step?: string;
  line: string;
  stderr?: boolean;
}

export interface Result {
  step: string;
  status: string;
  reason?: string;
  detail?: string;
  code?: number;
}

export interface RunState {
  steps: StepView[];
  logs: LogLine[];
  needsUi: NeedsUi | null;
  done: {
    ok: boolean;
    configured?: boolean;
    results: Result[];
    pending: string[];
    installed?: string[];
    changed?: boolean;
    checks?: { name: string; status: string; detail: string }[];
  } | null;
  error: { code: string; message: string } | null;
  /** The install's phase: `plan`, `install`, or the uv installer's `download`, `install_uv`. */
  phase: string | null;
  plan: { features: string[]; added: string[]; packages: string[] } | null;
}

export const emptyRun: RunState = {
  steps: [],
  logs: [],
  needsUi: null,
  done: null,
  error: null,
  phase: null,
  plan: null,
};

const str = (value: unknown): string | undefined =>
  typeof value === "string" ? value : undefined;
const strings = (value: unknown): string[] | undefined =>
  Array.isArray(value) ? value.filter((v): v is string => typeof v === "string") : undefined;

function log(state: RunState, line: LogLine): RunState {
  const logs = [...state.logs, line];
  return { ...state, logs: logs.length > MAX_LOG ? logs.slice(logs.length - MAX_LOG) : logs };
}

function upsertStep(state: RunState, id: string, patch: Partial<StepView>): RunState {
  const at = state.steps.findIndex((s) => s.id === id);
  if (at < 0) {
    const step: StepView = { id, label: patch.label ?? id, status: "pending", ...patch };
    return { ...state, steps: [...state.steps, step] };
  }
  const steps = state.steps.slice();
  steps[at] = { ...steps[at], ...Object.fromEntries(Object.entries(patch).filter(([, v]) => v !== undefined)) };
  return { ...state, steps };
}

function asCheck(event: JobEvent): CheckEvent {
  const action = event.action;
  return {
    ok: Boolean(event.ok),
    summary: str(event.summary) ?? "",
    checks: Array.isArray(event.checks) ? (event.checks as CheckItem[]) : [],
    action: action && typeof action === "object" ? (action as HandAction) : null,
    values:
      event.values && typeof event.values === "object"
        ? (event.values as Record<string, unknown>)
        : {},
  };
}

/** One event of `tau setup install|run --json` (or of the uv install) into the run's state. */
export function reduceRun(state: RunState, event: JobEvent): RunState {
  switch (event.event) {
    case "progress": {
      const phase = str(event.phase);
      if (phase) {
        const next = { ...state, phase };
        if (phase === "plan") {
          return {
            ...next,
            plan: {
              features: strings(event.features) ?? [],
              added: strings(event.added) ?? [],
              packages: strings(event.packages) ?? [],
            },
          };
        }
        return next;
      }
      const id = str(event.step);
      if (!id) return state;
      return upsertStep(state, id, {
        label: str(event.label),
        status: (str(event.status) as StepStatus) ?? "running",
        detail: str(event.detail),
        reason: str(event.reason),
        text: str(event.text),
        url: str(event.url),
        command: strings(event.command),
        code: typeof event.code === "number" ? event.code : undefined,
      });
    }
    case "check": {
      const check = asCheck(event);
      const id =
        str(event.step) ??
        [...state.steps].reverse().find((s) => s.status === "checking" || s.status === "running")
          ?.id;
      return id ? upsertStep(state, id, { check }) : state;
    }
    case "log":
      return log(state, { step: str(event.step), line: str(event.line) ?? "" });
    case "text":
      return log(state, { line: str(event.line) ?? "" });
    case "stderr":
      return log(state, { line: str(event.line) ?? "", stderr: true });
    case "needs_ui": {
      const action = event.action && typeof event.action === "object" ? (event.action as HandAction) : undefined;
      const needsUi: NeedsUi = {
        feature: str(event.feature) ?? "",
        step: str(event.step) ?? "",
        label: str(event.label) ?? "",
        command: strings(event.command) ?? [],
        argv: strings(event.argv),
        action,
      };
      return upsertStep({ ...state, needsUi }, needsUi.step, {
        label: needsUi.label || undefined,
        status: "needs_ui",
      });
    }
    case "done":
      return {
        ...state,
        done: {
          ok: Boolean(event.ok),
          configured: typeof event.configured === "boolean" ? event.configured : undefined,
          results: Array.isArray(event.results) ? (event.results as Result[]) : [],
          pending: strings(event.pending) ?? [],
          installed: strings(event.installed),
          changed: typeof event.changed === "boolean" ? event.changed : undefined,
          checks: Array.isArray(event.checks)
            ? (event.checks as { name: string; status: string; detail: string }[])
            : undefined,
        },
      };
    case "error":
      return {
        ...state,
        error: { code: str(event.code) ?? "error", message: str(event.message) ?? "" },
      };
    default:
      return state;
  }
}

/** How the wizard handles a `needs_ui` step. */
export type NeedsUiKind =
  /** An action the owner takes in Terminal (issue 173): shown, never run. */
  | "action"
  /** The guard's enrolment: in the wizard's terminal, which holds the camera through the app. */
  | "guard"
  /** `tau telegram pair --json`, with the token field and the code. */
  | "telegram"
  /** `tau net spine deploy --json`, with the token link and the account choice. */
  | "spine"
  /** Anything else: in the wizard's terminal. */
  | "terminal";

export function needsUiKind(needsUi: NeedsUi): NeedsUiKind {
  if (needsUi.action && !needsUi.argv) return "action";
  const [a, b, c] = needsUi.command;
  if (a === "guard" && b === "setup") return "guard";
  if (a === "telegram" && b === "pair") return "telegram";
  if (a === "net" && b === "spine" && c === "deploy" && needsUi.command[3]) return "spine";
  return "terminal";
}

/** An action's command as one line to copy. */
export function actionCommand(action: HandAction): string | null {
  if (Array.isArray(action.command)) return action.command.join(" ") || null;
  return action.command || null;
}

// -- tau telegram pair --json ------------------------------------------------------------

export interface PairState {
  notes: string[];
  bot: string | null;
  token: "written" | "kept" | null;
  code: { code: string; link: string; expires_at: string | null } | null;
  waiting: string | null;
  paired: { name: string; dropped: number; hub: boolean } | null;
  error: { reason: string; message: string } | null;
}

export const emptyPair: PairState = {
  notes: [],
  bot: null,
  token: null,
  code: null,
  waiting: null,
  paired: null,
  error: null,
};

export function reducePair(state: PairState, event: JobEvent): PairState {
  switch (event.event) {
    case "note":
      return { ...state, notes: [...state.notes, str(event.message) ?? ""] };
    case "bot":
      return {
        ...state,
        bot: str(event.bot) ?? null,
        token: event.token === "written" || event.token === "kept" ? event.token : null,
      };
    case "code":
      return {
        ...state,
        bot: str(event.bot) ?? state.bot,
        code: {
          code: str(event.code) ?? "",
          link: str(event.link) ?? "",
          expires_at: str(event.expires_at) ?? null,
        },
      };
    case "waiting":
      return { ...state, waiting: str(event.via) ?? "hub" };
    case "paired":
      return {
        ...state,
        waiting: null,
        paired: {
          name: str(event.name) ?? "",
          dropped: typeof event.dropped === "number" ? event.dropped : 0,
          hub: Boolean(event.hub),
        },
      };
    case "error":
      return {
        ...state,
        waiting: null,
        error: { reason: str(event.reason) ?? "error", message: str(event.message) ?? "" },
      };
    default:
      return state;
  }
}

/** The pairing failed for want of a (good) token: ask for one again. */
export function pairNeedsToken(state: PairState): boolean {
  return ["no_token", "token_invalid", "token_refused"].includes(state.error?.reason ?? "");
}

// -- tau net spine deploy --json ---------------------------------------------------------

export interface SpineState {
  progress: { key: string; text: string }[];
  needToken: { link: string; permissions: string[]; message: string } | null;
  accounts: { id: string; name: string }[] | null;
  message: string | null;
  error: string | null;
  done: { url: string; accountId: string; tokenCreated: boolean; healthy: boolean } | null;
}

export const emptySpine: SpineState = {
  progress: [],
  needToken: null,
  accounts: null,
  message: null,
  error: null,
  done: null,
};

export function reduceSpine(state: SpineState, event: JobEvent): SpineState {
  switch (event.type) {
    case "progress":
      return {
        ...state,
        progress: [...state.progress, { key: str(event.key) ?? "", text: str(event.text) ?? "" }],
      };
    case "need_token": {
      const permissions = Array.isArray(event.permissions)
        ? event.permissions.map((p) => (typeof p === "string" ? p : JSON.stringify(p)))
        : [];
      return {
        ...state,
        needToken: { link: str(event.link) ?? "", permissions, message: str(event.message) ?? "" },
      };
    }
    case "choose_account":
      return {
        ...state,
        accounts: Array.isArray(event.accounts)
          ? (event.accounts as { id: string; name: string }[])
          : [],
        message: str(event.message) ?? null,
      };
    case "error":
      return { ...state, error: str(event.message) ?? "" };
    case "done":
      return {
        ...state,
        done: {
          url: str(event.url) ?? "",
          accountId: str(event.account_id) ?? "",
          tokenCreated: Boolean(event.token_created),
          healthy: Boolean(event.healthy),
        },
      };
    default:
      // The app's own wrapped lines (`text`, `stderr`) carry `event`, not `type`.
      if (event.event === "stderr" || event.event === "text") {
        const line = str(event.line);
        return line ? { ...state, progress: [...state.progress, { key: "log", text: line }] } : state;
      }
      return state;
  }
}
