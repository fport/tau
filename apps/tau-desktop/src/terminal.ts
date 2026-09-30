// The terminal's configuration and the small pure helpers around it: options, keys, links,
// input bytes and resize debouncing. Types only from xterm.js, so the tests run without a DOM.

import type { ITerminalInitOnlyOptions, ITerminalOptions, ITheme } from "@xterm/xterm";

/** System monospace fonts only; nothing is fetched from the network (ADR 0006). Menlo first:
 * it ships with every macOS and covers box drawing and the block elements of tau's mark. */
export const FONT_STACK = 'Menlo, "SF Mono", ui-monospace, Monaco, monospace';

/** The brand palette (docs/brand/README.md); the TUI draws in truecolor, so these frame it. */
export const THEME: ITheme = {
  background: "#05071a", // Void
  foreground: "#fff4e0", // Core
  cursor: "#ff7a3d", // Ember
  cursorAccent: "#05071a",
  selectionBackground: "rgba(255, 122, 61, 0.35)", // Ember
  selectionForeground: "#fff4e0",
};

export function terminalOptions(): ITerminalOptions & ITerminalInitOnlyOptions {
  return {
    fontFamily: FONT_STACK,
    fontSize: 13,
    lineHeight: 1.0,
    theme: THEME,
    // Option types @ # $ [ ] { } | \ ~ on Turkish and other layouts; tau's bindings are ctrl
    // and F-keys, so Option must never become Meta.
    macOptionIsMeta: false,
    // Textual turns mouse tracking on; Option-drag still selects text for ⌘C.
    macOptionClickForcesSelection: true,
    // Option-click must not send arrow keys into the TUI.
    altClickMovesCursor: false,
    // The Unicode 11 width tables (emoji, CJK) need the proposed API.
    allowProposedApi: true,
    cursorBlink: false,
    scrollback: 1000,
    drawBoldTextInBrightColors: false,
  };
}

/** The subset of a KeyboardEvent the key filter looks at. */
export interface KeyLike {
  type: string;
  key: string;
  metaKey: boolean;
  ctrlKey: boolean;
  altKey: boolean;
}

/**
 * Keys that belong to the app, not the TUI: on a Mac every ⌘ combination (New Window, Close,
 * Copy, Paste, Quit, Hide, …) goes to the menu, except ⌘A, which selects the terminal's text.
 * Everything else, ctrl and Option included, goes to xterm.js and on to the PTY.
 */
export function isAppShortcut(event: KeyLike, isMac: boolean): boolean {
  if (!isMac || !event.metaKey) return false;
  return event.key.toLowerCase() !== "a";
}

/** For `attachCustomKeyEventHandler`: `true` lets xterm.js handle the key. */
export function keyFilter(isMac: boolean): (event: KeyLike) => boolean {
  return (event) => !isAppShortcut(event, isMac);
}

/** Whether a link click opens the browser: ⌘-click on an http(s) link, as in Terminal. */
export function shouldOpenLink(event: { metaKey: boolean }, uri: string): boolean {
  return event.metaKey && isWebLink(uri);
}

export function isWebLink(uri: string): boolean {
  try {
    const url = new URL(uri);
    return (url.protocol === "http:" || url.protocol === "https:") && url.hostname !== "";
  } catch {
    return false;
  }
}

const encoder = new TextEncoder();

/** `onData`: typed text and key sequences, UTF-8 encoded for the PTY. */
export function textToBytes(data: string): Uint8Array {
  return encoder.encode(data);
}

/** `onBinary`: legacy mouse reports, one byte per UTF-16 code unit (0–255). */
export function binaryToBytes(data: string): Uint8Array {
  const out = new Uint8Array(data.length);
  for (let i = 0; i < data.length; i++) out[i] = data.charCodeAt(i) & 0xff;
  return out;
}

/** How long a window resize must settle before the grid (and the PTY) is resized. */
export const RESIZE_DEBOUNCE_MS = 50;

export interface Debounced<A extends unknown[]> {
  (...args: A): void;
  cancel(): void;
}

/** Call `fn` once, `ms` after the last call; a live resize drag becomes one SIGWINCH. */
export function debounce<A extends unknown[]>(fn: (...args: A) => void, ms: number): Debounced<A> {
  let timer: ReturnType<typeof setTimeout> | null = null;
  const debounced = (...args: A) => {
    if (timer !== null) clearTimeout(timer);
    timer = setTimeout(() => {
      timer = null;
      fn(...args);
    }, ms);
  };
  debounced.cancel = () => {
    if (timer !== null) clearTimeout(timer);
    timer = null;
  };
  return debounced;
}

/** One line for a TUI that ended on its own. */
export function exitMessage(info: { success: boolean; code: number | null; signal: string | null }): string {
  if (info.signal) return `tau tui was stopped (${info.signal}).`;
  if (info.code !== null && info.code !== 0) return `tau tui exited with code ${info.code}.`;
  return "tau tui exited.";
}
