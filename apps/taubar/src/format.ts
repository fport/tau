// Pure display helpers for the settings window and the panel (tested in format.test.ts).

import type { HubSettings, HubState, LoginItemStatus, SleepMode, SleepStatus } from "./api";

/** The colour class of the hub's status line (brand state colours, no green or red). */
export function hubTone(state: HubState): "ok" | "pending" | "attention" | "error" {
  switch (state) {
    case "up":
    case "elsewhere":
      return "ok";
    case "starting":
    case "stopping":
    case "off":
    case "stopped":
      return "pending";
    case "restarting":
    case "launchd_idle":
    case "not_configured":
      return "attention";
    case "error":
      return "error";
  }
}

/** The hub form as the user types it (every field a string). */
export interface HubForm {
  python: string;
  tau_home: string;
  data_dir: string;
  port: string;
  path: string;
  env: string;
}

export function formFromSettings(settings: HubSettings): HubForm {
  return {
    python: settings.python ?? "",
    tau_home: settings.tau_home ?? "",
    data_dir: settings.data_dir ?? "",
    port: settings.port == null ? "" : String(settings.port),
    path: settings.path ?? "",
    env: formatEnv(settings.env),
  };
}

/** Settings from the form, or the problems that keep it from being saved. */
export function settingsFromForm(form: HubForm): { settings: HubSettings; errors: string[] } {
  const errors: string[] = [];
  const text = (value: string) => (value.trim() === "" ? null : value.trim());
  let port: number | null = null;
  if (form.port.trim() !== "") {
    const parsed = Number(form.port.trim());
    if (Number.isInteger(parsed) && parsed >= 1 && parsed <= 65535) {
      port = parsed;
    } else {
      errors.push(`Control port must be a number from 1 to 65535, not "${form.port.trim()}".`);
    }
  }
  const env = parseEnv(form.env);
  errors.push(...env.errors);
  return {
    settings: {
      python: text(form.python),
      tau_home: text(form.tau_home),
      data_dir: text(form.data_dir),
      port,
      path: text(form.path),
      env: env.env,
    },
    errors,
  };
}

/** `KEY=value` lines (blank lines and `#` comments ignored; an empty value is allowed). */
export function parseEnv(text: string): { env: Record<string, string>; errors: string[] } {
  const env: Record<string, string> = {};
  const errors: string[] = [];
  text.split("\n").forEach((raw, index) => {
    const line = raw.trim();
    if (line === "" || line.startsWith("#")) return;
    const eq = line.indexOf("=");
    const key = eq < 0 ? line : line.slice(0, eq).trim();
    if (eq < 0 || !/^[A-Za-z_][A-Za-z0-9_]*$/.test(key)) {
      errors.push(`Environment line ${index + 1} is not KEY=value: "${line}".`);
      return;
    }
    env[key] = line.slice(eq + 1).trim();
  });
  return { env, errors };
}

export function formatEnv(env: Record<string, string>): string {
  return Object.keys(env)
    .sort()
    .map((key) => `${key}=${env[key]}`)
    .join("\n");
}

/** Python and TAU_HOME for a tau checkout (its uv virtualenv). */
export function checkoutSettings(dir: string): { python: string; tau_home: string } {
  const home = dir.replace(/\/+$/, "");
  return { python: `${home}/.venv/bin/python`, tau_home: home };
}

export interface SleepChoice {
  mode: SleepMode;
  title: string;
  detail: string;
}

export const SLEEP_CHOICES: SleepChoice[] = [
  {
    mode: "normal",
    title: "Normal",
    detail: "TauBar holds nothing; the Mac sleeps as usual.",
  },
  {
    mode: "keep_awake_on_ac",
    title: "Keep awake on AC power",
    detail:
      "No system sleep while plugged in (like caffeinate -s). On battery or with the lid closed the Mac still sleeps.",
  },
  {
    mode: "keep_awake_lid_closed",
    title: "Keep awake with the lid closed",
    detail:
      "Also stays awake with the lid closed (pmset disablesleep 1). Needs the narrow sudoers rule; watch the temperature in a bag.",
  },
];

/** Whether a sleep choice can be picked right now. */
export function sleepChoiceEnabled(mode: SleepMode, status: SleepStatus): boolean {
  return mode !== "keep_awake_lid_closed" || status.lid_available;
}

/** The panel's line under "Sleep" when what is in force needs explaining, else null. */
export function sleepNote(status: SleepStatus): string | null {
  if (status.disabled_elsewhere) {
    return "Sleep is disabled outside TauBar (pmset disablesleep 1).";
  }
  if (status.wanted !== status.effective) {
    return `"${choiceTitle(status.wanted)}" is unavailable, so "${choiceTitle(status.effective)}" is in force.`;
  }
  return status.problem;
}

function choiceTitle(mode: SleepMode): string {
  return SLEEP_CHOICES.find((choice) => choice.mode === mode)?.title ?? mode;
}

/** Whether "Launch at login" shows as on (macOS may still wait for the user's approval). */
export function loginChecked(status: LoginItemStatus): boolean {
  return status === "enabled" || status === "requires_approval";
}

/** The sentence under the "Launch at login" checkbox. */
export function loginNote(status: LoginItemStatus): string {
  switch (status) {
    case "enabled":
      return "TauBar opens when you log in (System Settings → General → Login Items).";
    case "not_registered":
      return "TauBar does not open at login.";
    case "requires_approval":
      return "Registered, but macOS is waiting for you to allow it in System Settings → Login Items.";
    case "not_found":
      return "TauBar does not open at login (it has never been registered as a login item).";
    case "unsupported":
      return "Launch at login is only available on macOS.";
  }
}

/** Keep the most recent `max` lines, newest last. */
export function lastLines(lines: string[], max: number): string[] {
  return lines.length <= max ? lines : lines.slice(lines.length - max);
}
