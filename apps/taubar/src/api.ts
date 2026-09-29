// Typed wrappers around TauBar's Rust commands (src-tauri/src/commands.rs) and its snapshot
// event. The types mirror the Rust `Snapshot` (serde, snake_case).

import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";

export type SleepMode = "normal" | "keep_awake_on_ac" | "keep_awake_lid_closed";

export type LoginItemStatus =
  | "enabled"
  | "not_registered"
  | "requires_approval"
  | "not_found"
  | "unsupported";

export interface SleepStatus {
  wanted: SleepMode;
  effective: SleepMode;
  lid_available: boolean;
  disabled_elsewhere: boolean;
  problem: string | null;
}

export interface Snapshot {
  version: string;
  sleep: SleepStatus;
  sleep_summary: string;
  login: { status: LoginItemStatus; problem: string | null };
  files: { settings: string; log: string };
}

export const SNAPSHOT_EVENT = "taubar://snapshot";

export const api = {
  snapshot: () => invoke<Snapshot>("snapshot"),
  setSleepMode: (mode: SleepMode) => invoke<Snapshot>("set_sleep_mode", { mode }),
  setLaunchAtLogin: (enabled: boolean) => invoke<Snapshot>("set_launch_at_login", { enabled }),
  openLoginItems: () => invoke<void>("open_login_items"),
  logTail: (lines = 40) => invoke<string[]>("log_tail", { lines }),
  openLog: () => invoke<void>("open_log"),
  quit: () => invoke<void>("quit"),
};

export function onSnapshot(handler: (snapshot: Snapshot) => void): Promise<UnlistenFn> {
  return listen<Snapshot>(SNAPSHOT_EVENT, (event) => handler(event.payload));
}
