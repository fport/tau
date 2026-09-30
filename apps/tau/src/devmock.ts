// `bun run dev` in a plain browser: a stand-in for TauBar's Rust side, so the settings window
// (http://localhost:1420/) and the panel (http://localhost:1420/#panel) can be looked at without
// the app. main.tsx imports it only in development and outside Tauri, so no build contains it.

import { mockIPC } from "@tauri-apps/api/mocks";
import type { SleepMode, Snapshot } from "./api";

const crash = "unexpected exit (no clean shutdown), pid 44305";

let snapshot: Snapshot = {
  version: "0.1.0",
  hub: {
    switch_on: true,
    state: "up",
    pid: 79081,
    by_taubar: true,
    launchd: false,
    uptime_s: 9_540,
    restart_in_s: null,
    restarts: 0,
    last_exit: null,
    guard: { state: "locked", enrolled: true, available: true, reason: null },
    control_url: "http://127.0.0.1:7877",
    hub_log: "~/.local/share/tau/logs/tau.log",
    command: "/path/to/tau/.venv/bin/python -m tau_core hub run",
    problem: null,
    lines: [
      "Hub: up 2 h 39 min · pid 79081",
      "Telegram: polling as @tau_bot",
      `Last crash: ${crash}`,
    ],
    panel: {
      title: "Up 2 h 39 min",
      detail: "pid 79081 · started by TauBar",
      telegram: "polling as @tau_bot",
      crash,
      guard: "locked",
    },
    guard_menu: { line: "Guard: locked", lock_now: true, grant_camera: false },
    run_at_start: true,
    settings: {
      python: "/path/to/tau/.venv/bin/python",
      tau_home: "/path/to/tau",
      data_dir: null,
      port: null,
      path: null,
      env: {},
    },
  },
  sleep: {
    wanted: "keep_awake_on_ac",
    effective: "keep_awake_on_ac",
    lid_available: false,
    disabled_elsewhere: false,
    problem: null,
  },
  sleep_summary: "Sleep: kept awake on AC power",
  login: { status: "enabled", problem: null },
  files: {
    settings: "~/Library/Application Support/com.tau.taubar/settings.json",
    log: "~/Library/Logs/com.tau.taubar/taubar.log",
  },
};

function runHub(on: boolean) {
  const { hub } = snapshot;
  snapshot = {
    ...snapshot,
    hub: on
      ? {
          ...hub,
          switch_on: true,
          state: "up",
          pid: 79081,
          uptime_s: 1,
          panel: { ...hub.panel, title: "Up 1 s", detail: "pid 79081 · started by TauBar", telegram: "polling as @tau_bot" },
        }
      : {
          ...hub,
          switch_on: false,
          state: "off",
          pid: null,
          uptime_s: null,
          panel: { ...hub.panel, title: "Off", detail: "Switch it on to start the hub", telegram: "–" },
        },
  };
}

mockIPC(
  (cmd, args) => {
    const payload = (args ?? {}) as Record<string, unknown>;
    switch (cmd) {
      case "snapshot":
        return snapshot;
      case "set_sleep_mode": {
        const mode = payload.mode as SleepMode;
        snapshot = { ...snapshot, sleep: { ...snapshot.sleep, wanted: mode, effective: mode } };
        return snapshot;
      }
      case "set_launch_at_login":
        snapshot = {
          ...snapshot,
          login: { status: payload.enabled ? "enabled" : "not_registered", problem: null },
        };
        return snapshot;
      case "set_run_hub":
        runHub(Boolean(payload.on));
        return { snapshot, message: null };
      case "save_hub_settings":
        return snapshot;
      case "lock_guard":
        return snapshot;
      case "log_tail":
        return ["2026-09-30 12:00:00 TauBar 0.1.0 started (pid 1234)"];
      default:
        return undefined;
    }
  },
  { shouldMockEvents: true },
);
