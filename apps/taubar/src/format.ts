// Pure display helpers for the settings window (tested in format.test.ts).

import type { LoginItemStatus, SleepMode, SleepStatus } from "./api";

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
