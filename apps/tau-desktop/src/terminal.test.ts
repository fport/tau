import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  FONT_STACK,
  RESIZE_DEBOUNCE_MS,
  binaryToBytes,
  debounce,
  exitMessage,
  gridChanged,
  isAppShortcut,
  isWebLink,
  keyFilter,
  shouldBlockContextMenu,
  shouldOpenLink,
  terminalOptions,
  textToBytes,
  type KeyLike,
} from "./terminal";

const key = (k: string, mods: Partial<KeyLike> = {}): KeyLike => ({
  type: "keydown",
  key: k,
  metaKey: false,
  ctrlKey: false,
  altKey: false,
  ...mods,
});

describe("terminal options", () => {
  const options = terminalOptions();

  it("keeps Option for typing and Option-click for selecting", () => {
    // Option+Q is @ and Option+7 is { on a Turkish Mac layout: never Meta.
    expect(options.macOptionIsMeta).toBe(false);
    // Textual turns on mouse tracking; Option-drag still selects.
    expect(options.macOptionClickForcesSelection).toBe(true);
    expect(options.altClickMovesCursor).toBe(false);
    expect(options.allowProposedApi).toBe(true); // the Unicode 11 addon needs it
  });

  it("uses system monospace fonts only", () => {
    expect(options.fontFamily).toBe(FONT_STACK);
    expect(FONT_STACK.startsWith("Menlo")).toBe(true);
    expect(FONT_STACK).toContain("SF Mono");
    expect(FONT_STACK).not.toMatch(/url\(|https?:|\.woff|\.ttf/);
  });

  it("frames the TUI in the brand palette", () => {
    expect(options.theme?.background).toBe("#05071a");
    expect(options.theme?.foreground).toBe("#fff4e0");
  });
});

describe("key handling", () => {
  it("sends ⌘ combinations to the menu, except ⌘A", () => {
    for (const k of ["n", "w", "q", "c", "v", "h", "m", ","]) {
      expect(isAppShortcut(key(k, { metaKey: true }), true)).toBe(true);
    }
    expect(isAppShortcut(key("a", { metaKey: true }), true)).toBe(false);
    expect(isAppShortcut(key("A", { metaKey: true }), true)).toBe(false);
  });

  it("lets ctrl, Option and plain keys through to the TUI", () => {
    const filter = keyFilter(true);
    expect(filter(key("q", { ctrlKey: true }))).toBe(true); // ctrl+q: quit the TUI
    expect(filter(key("n", { ctrlKey: true }))).toBe(true); // ctrl+n: new session, not ⌘N
    expect(filter(key("@", { altKey: true }))).toBe(true); // Option+Q on a Turkish layout
    expect(filter(key("{", { altKey: true }))).toBe(true);
    expect(filter(key("F2"))).toBe(true);
    expect(filter(key("Escape"))).toBe(true);
    expect(filter(key("ğ"))).toBe(true);
    expect(filter(key("w", { metaKey: true }))).toBe(false);
  });

  it("treats the Meta key as an ordinary key off the Mac", () => {
    expect(isAppShortcut(key("n", { metaKey: true }), false)).toBe(false);
  });
});

describe("links", () => {
  it("opens only ⌘-clicked http(s) links", () => {
    expect(shouldOpenLink({ metaKey: true }, "https://example.com/a")).toBe(true);
    expect(shouldOpenLink({ metaKey: false }, "https://example.com/a")).toBe(false);
    for (const uri of ["file:///etc/passwd", "javascript:alert(1)", "tauri://localhost", "https://", "nope"]) {
      expect(isWebLink(uri)).toBe(false);
      expect(shouldOpenLink({ metaKey: true }, uri)).toBe(false);
    }
  });
});

describe("input bytes", () => {
  it("encodes typed text as UTF-8", () => {
    expect(Array.from(textToBytes("ğ"))).toEqual([0xc4, 0x9f]);
    expect(Array.from(textToBytes("\x11"))).toEqual([0x11]); // ctrl+q
    expect(new TextDecoder().decode(textToBytes("ğüşıöç"))).toBe("ğüşıöç");
  });

  it("maps binary mouse reports byte for byte", () => {
    // X10 mouse report with a coordinate byte above 127: must stay one byte.
    const report = "\x1b[M" + String.fromCharCode(32, 200, 255);
    expect(Array.from(binaryToBytes(report))).toEqual([0x1b, 0x5b, 0x4d, 32, 200, 255]);
  });
});

describe("resize debounce", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("turns a burst of resizes into one call with the last arguments", () => {
    const fit = vi.fn();
    const refit = debounce(fit, RESIZE_DEBOUNCE_MS);
    refit(80, 24);
    vi.advanceTimersByTime(RESIZE_DEBOUNCE_MS - 1);
    refit(100, 30);
    vi.advanceTimersByTime(RESIZE_DEBOUNCE_MS - 1);
    refit(120, 40);
    expect(fit).not.toHaveBeenCalled();
    vi.advanceTimersByTime(RESIZE_DEBOUNCE_MS);
    expect(fit).toHaveBeenCalledTimes(1);
    expect(fit).toHaveBeenCalledWith(120, 40);
  });

  it("can be cancelled", () => {
    const fit = vi.fn();
    const refit = debounce(fit, RESIZE_DEBOUNCE_MS);
    refit();
    refit.cancel();
    vi.advanceTimersByTime(RESIZE_DEBOUNCE_MS * 2);
    expect(fit).not.toHaveBeenCalled();
  });
});

describe("exit message", () => {
  it("says how the TUI ended", () => {
    expect(exitMessage({ success: false, code: 1, signal: null })).toBe("tau tui exited with code 1.");
    expect(exitMessage({ success: false, code: null, signal: "Killed: 9" })).toBe(
      "tau tui was stopped (Killed: 9).",
    );
    expect(exitMessage({ success: true, code: 0, signal: null })).toBe("tau tui exited.");
  });
});

describe("context menu", () => {
  // A stand-in for an Element: `closest(".xterm")` finds the terminal or nothing.
  const inTerminal = { closest: (selector: string) => (selector === ".xterm" ? {} : null) };
  const outside = { closest: () => null };

  it("keeps the text menu inside the terminal", () => {
    expect(shouldBlockContextMenu(inTerminal)).toBe(false);
  });

  it("suppresses the webview menu (with Reload) everywhere else", () => {
    expect(shouldBlockContextMenu(outside)).toBe(true);
    expect(shouldBlockContextMenu({})).toBe(true); // not an element
    expect(shouldBlockContextMenu(null)).toBe(true);
  });
});

describe("resize after start", () => {
  it("resizes only when the grid changed while the TUI was starting", () => {
    expect(gridChanged({ cols: 120, rows: 40 }, { cols: 120, rows: 40 })).toBe(false);
    expect(gridChanged({ cols: 120, rows: 40 }, { cols: 121, rows: 40 })).toBe(true);
    expect(gridChanged({ cols: 120, rows: 40 }, { cols: 120, rows: 39 })).toBe(true);
  });
});
