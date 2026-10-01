// Typed wrappers around the setup wizard's Rust commands (src-tauri/src/wizard/commands.rs) and
// the JSON that `tau setup status --json` prints (docs/reference/setup.md). No command takes a
// program, a Python or a path to run: the page names a job, and Rust runs it with the tau its
// discovery found. Keys and tokens travel in a job's `input` and go to the child's stdin only.

import { Channel, invoke } from "@tauri-apps/api/core";
import type { ExitInfo } from "../chat/api";

export type Lang = "en" | "tr";

// -- `tau setup status --json` -------------------------------------------------------------

export interface StepInput {
  name: string;
  label: string;
  secret: boolean;
  required: boolean;
  default: string | null;
}

export interface CatalogStep {
  id: string;
  kind: "command" | "note";
  label: string;
  interactive: boolean;
  optional: boolean;
  local_only: boolean;
  /** A step that checks something and reports `check` events (issue 173). */
  check?: boolean;
  command?: string[];
  text?: string;
  url?: string;
  needs?: string[];
  when_command?: string[];
  inputs: StepInput[];
}

export type PermissionId = "camera" | "microphone" | "notifications";

export type FeatureState = "done" | "installed" | "missing" | "available" | "unavailable";

export interface FeatureStatus {
  id: string;
  label: string;
  description: string;
  package: string | null;
  lockstep: boolean;
  platforms: string[];
  available: boolean;
  unavailable_reason: string | null;
  default: boolean;
  advanced: boolean;
  permissions: { id: PermissionId; label: string }[];
  requires: string[];
  installed: boolean;
  version: string | null;
  configured: boolean;
  state: FeatureState;
  docs: string;
  steps: CatalogStep[];
}

export interface SetupStatus {
  protocol: number;
  version: string;
  platform: string;
  platform_label: string;
  language: string;
  ssh: boolean;
  install: { mode: "uv-tool" | "environment"; can_install: boolean };
  home: string;
  config: boolean;
  about: boolean;
  core_steps: string[];
  features: FeatureStatus[];
}

/** Why there is no status: nothing found yet, a tau-core without `tau setup`, or a failure. */
export interface StatusProblem {
  code: "no_tau" | "too_old" | "failed";
  message: string;
}

// -- discovery ---------------------------------------------------------------------------

export type FoundKind = "settings" | "checkout" | "uv_tool" | "command";

export interface Found {
  python: string;
  home: string;
  kind: FoundKind;
  via: string;
  version: string;
  uv_tool: boolean;
}

export interface Discovery {
  tau: Found | null;
  uv: string | null;
  rejected: { python: string; kind: FoundKind; problem: string }[];
  saved_hub: boolean;
  saved_chat: boolean;
  default_home: string;
  install_version: string | null;
  hub_ready: boolean;
}

// -- jobs ----------------------------------------------------------------------------------

export type JobSpec =
  | { kind: "install"; features: string[] }
  | { kind: "run"; target: string }
  | { kind: "telegram_pair" }
  | { kind: "spine_deploy"; dir: string };

/** One JSON line of a job: `event` for tau setup and Telegram, `type` for the spine deploy;
 * `text` and `stderr` are lines the app wrapped. */
export type JobEvent = { event?: string; type?: string } & Record<string, unknown>;

/** How a job ended (Rust `Ended`). */
export interface Ended {
  code: number | null;
  signal: number | null;
  timed_out: boolean;
  cancelled: boolean;
}

export type Access = "granted" | "denied" | "restricted" | "not_determined" | "unsupported";

/**
 * Run a streaming command: every event goes to `onEvent`, and the promise settles with the
 * `ended` event Rust sends last on the same channel (so no event arrives after it), or rejects
 * when the job could not start.
 */
function stream(
  command: string,
  args: Record<string, unknown>,
  onEvent: (event: JobEvent) => void,
): Promise<Ended> {
  return new Promise((resolve, reject) => {
    const events = new Channel<JobEvent>();
    events.onmessage = (event) => {
      if (event.event === "ended") {
        resolve({
          code: (event.code as number | null) ?? null,
          signal: (event.signal as number | null) ?? null,
          timed_out: Boolean(event.timed_out),
          cancelled: Boolean(event.cancelled),
        });
      } else {
        onEvent(event);
      }
    };
    invoke<Ended>(command, { ...args, events }).catch(reject);
  });
}

export const api = {
  /** Find tau (and uv); writes what it finds into the settings that lack it. */
  discover: () => invoke<Discovery>("wizard_discover"),
  /** `tau setup status --json`; rejects with a {@link StatusProblem}. */
  status: (lang: Lang) => invoke<SetupStatus>("wizard_status", { lang }),
  run: (spec: JobSpec, input: object | null, lang: Lang, onEvent: (event: JobEvent) => void) =>
    stream("wizard_run", { spec, input, lang }, onEvent),
  install: (what: "uv" | "tau" | "upgrade", onEvent: (event: JobEvent) => void) =>
    stream("wizard_install", { what }, onEvent),
  /** Stop the running job (Ctrl-C, then a kill). */
  cancel: () => invoke<void>("wizard_cancel"),
  ptyStart: (
    command: string[],
    lang: Lang,
    cols: number,
    rows: number,
    onOutput: (bytes: Uint8Array) => void,
    onExit: (info: ExitInfo) => void,
  ) => {
    const output = new Channel<ArrayBuffer>();
    output.onmessage = (buffer) => onOutput(new Uint8Array(buffer));
    const exit = new Channel<ExitInfo>();
    exit.onmessage = onExit;
    return invoke<void>("wizard_pty_start", { command, lang, cols, rows, output, exit });
  },
  ptyWrite: (bytes: Uint8Array) => invoke<void>("pty_write", bytes),
  ptyResize: (cols: number, rows: number) => invoke<void>("pty_resize", { cols, rows }),
  permission: (permission: PermissionId, request: boolean) =>
    invoke<Access>("wizard_permission", { permission, request }),
  permissionSettings: (permission: PermissionId) =>
    invoke<void>("wizard_permission_settings", { permission }),
  /** http and https only, in the default browser. */
  openLink: (url: string) => invoke<void>("open_link", { url }),
  newChat: () => invoke<void>("new_chat"),
  openSettings: () => invoke<void>("open_settings"),
  setRunHub: (on: boolean) =>
    invoke<{ message: string | null }>("set_run_hub", { on }),
  setLaunchAtLogin: (enabled: boolean) => invoke<unknown>("set_launch_at_login", { enabled }),
};
