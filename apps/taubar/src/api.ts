// Typed wrappers around TauBar's Rust commands (src-tauri/src/commands.rs) and its snapshot
// event, for the settings window and the panel. The types mirror the Rust `Snapshot` (serde,
// snake_case).

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

export type HubState =
  | "not_configured"
  | "off"
  | "starting"
  | "up"
  | "stopping"
  | "restarting"
  | "stopped"
  | "elsewhere"
  | "launchd_idle"
  | "error";

/** The owner guard's state from the hub's `/status` (`unknown`: anything else it said). */
export type GuardState = "off" | "locked" | "verifying" | "unlocked" | "unavailable" | "unknown";

/** The `guard` block of the hub's open `/status` (Rust `GuardStatus`). */
export interface GuardStatus {
  state: GuardState;
  enrolled: boolean;
  available: boolean;
  reason: string | null;
}

/** What the menu and the window show about the guard (Rust `GuardMenu`). */
export interface GuardMenu {
  /** The guard line; null hides the whole guard section. */
  line: string | null;
  lock_now: boolean;
  grant_camera: boolean;
}

/** How TauBar starts the hub (Rust `HubSettings`). */
export interface HubSettings {
  python: string | null;
  tau_home: string | null;
  data_dir: string | null;
  port: number | null;
  path: string | null;
  env: Record<string, string>;
}

/** The panel's hub rows (Rust `HubPanel`): `Up 2 h 5 min` / `pid 1234 · started by TauBar`. */
export interface HubPanel {
  title: string;
  detail: string;
  telegram: string;
  crash: string;
}

export interface HubSnapshot {
  switch_on: boolean;
  state: HubState;
  pid: number | null;
  by_taubar: boolean;
  launchd: boolean;
  uptime_s: number | null;
  restart_in_s: number | null;
  restarts: number;
  last_exit: { at: string; pid: number; reason: string } | null;
  /** The owner guard, when the hub runs one. */
  guard: GuardStatus | null;
  control_url: string | null;
  hub_log: string | null;
  command: string | null;
  problem: string | null;
  /** The menu's hub lines: status, Telegram (or a problem), last crash. */
  lines: [string, string, string];
  /** The panel's hub rows, without the menu's labels. */
  panel: HubPanel;
  /** The guard line and its actions (all hidden without a guard). */
  guard_menu: GuardMenu;
  /** The saved switch: what TauBar does at its next start. */
  run_at_start: boolean;
  settings: HubSettings;
}

export interface Snapshot {
  version: string;
  hub: HubSnapshot;
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
  setRunHub: (on: boolean) =>
    invoke<{ snapshot: Snapshot; message: string | null }>("set_run_hub", { on }),
  saveHubSettings: (hub: HubSettings) => invoke<Snapshot>("save_hub_settings", { hub }),
  openHubLog: () => invoke<void>("open_hub_log"),
  /** "Lock now": a signed `POST /guard/lock` from Rust; rejects when tau may not be locked. */
  lockGuard: () => invoke<Snapshot>("lock_guard"),
  openCameraSettings: () => invoke<void>("open_camera_settings"),
  openSettings: () => invoke<void>("open_settings"),
  /** The panel's content height, so its window fits it. */
  panelFit: (height: number) => invoke<void>("panel_fit", { height }),
  panelHide: () => invoke<void>("panel_hide"),
};

export function onSnapshot(handler: (snapshot: Snapshot) => void): Promise<UnlistenFn> {
  return listen<Snapshot>(SNAPSHOT_EVENT, (event) => handler(event.payload));
}
