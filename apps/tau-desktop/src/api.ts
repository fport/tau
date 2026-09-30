// Typed wrappers around tau Desktop's Rust commands (src-tauri/src/commands.rs). Every command
// acts on the calling window's own PTY; none takes a program or a path.

import { Channel, invoke } from "@tauri-apps/api/core";

export type HomeSource = "env" | "saved" | "picked" | "taubar";

/** Rust `HomeStatus`: ready to run `tau tui`, or asking for the checkout. */
export type HomeStatus =
  | { state: "ready"; home: string; source: HomeSource; version: string }
  | { state: "choose"; hint: string | null; problem: string | null };

/** Rust `ExitInfo`: how `tau tui` ended when it ended on its own. */
export interface ExitInfo {
  success: boolean;
  code: number | null;
  signal: string | null;
}

export const api = {
  homeStatus: () => invoke<HomeStatus>("home_status"),
  /** TauBar's checkout (`useHint`) or the native folder picker, then the version check. */
  chooseHome: (useHint: boolean) => invoke<HomeStatus>("choose_home", { useHint }),
  ptyStart: (
    cols: number,
    rows: number,
    onOutput: (bytes: Uint8Array) => void,
    onExit: (info: ExitInfo) => void,
  ) => {
    const output = new Channel<ArrayBuffer>();
    output.onmessage = (buffer) => onOutput(new Uint8Array(buffer));
    const exit = new Channel<ExitInfo>();
    exit.onmessage = onExit;
    return invoke<void>("pty_start", { cols, rows, output, exit });
  },
  /** Raw bytes as the request body: no JSON, no string round trip. */
  ptyWrite: (bytes: Uint8Array) => invoke<void>("pty_write", bytes),
  ptyResize: (cols: number, rows: number) => invoke<void>("pty_resize", { cols, rows }),
  openLink: (url: string) => invoke<void>("open_link", { url }),
};
