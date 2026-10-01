import { useEffect, useRef, useState } from "react";
import { Terminal } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import { Unicode11Addon } from "@xterm/addon-unicode11";
import { WebLinksAddon } from "@xterm/addon-web-links";
import { api, type ExitInfo } from "./api";
import { InputQueue } from "./input";
import { OutputCoalescer } from "./output";
import {
  RESIZE_DEBOUNCE_MS,
  binaryToBytes,
  debounce,
  exitMessage,
  gridChanged,
  keyFilter,
  shouldOpenLink,
  terminalOptions,
  textToBytes,
} from "./terminal";

const IS_MAC = navigator.userAgent.includes("Mac");

/** ⌘-click on an http(s) link opens it in the default browser (through Rust); nothing else. */
function openLink(event: MouseEvent, uri: string) {
  if (shouldOpenLink(event, uri)) api.openLink(uri).catch(() => undefined);
}

/** The PTY a terminal is attached to: the window's own, keyed by its label in Rust. */
export interface Pty {
  start: (
    cols: number,
    rows: number,
    onOutput: (bytes: Uint8Array) => void,
    onExit: (info: ExitInfo) => void,
  ) => Promise<void>;
  write: (bytes: Uint8Array) => Promise<void>;
  resize: (cols: number, rows: number) => Promise<void>;
}

/** A chat window's PTY, running `tau tui`. */
export const chatPty: Pty = {
  start: api.ptyStart,
  write: api.ptyWrite,
  resize: api.ptyResize,
};

// One terminal, attached to the window's own PTY: `tau tui` in a chat window (Enter starts it
// again after it ended), or one command in the setup wizard (`once`: it runs once, and
// `onExit` hears how it ended).
export default function TerminalView({
  pty = chatPty,
  className = "terminal-page",
  once = false,
  exitNotice,
  onExit,
}: {
  pty?: Pty;
  className?: string;
  once?: boolean;
  exitNotice?: (info: ExitInfo) => string;
  onExit?: (info: ExitInfo) => void;
}) {
  const host = useRef<HTMLDivElement>(null);
  const [notice, setNotice] = useState<string | null>(null);
  // The latest callbacks, for the terminal set up once below.
  const latest = useRef({ exitNotice, onExit });
  latest.current = { exitNotice, onExit };

  useEffect(() => {
    const element = host.current;
    if (!element) return;

    const term = new Terminal({
      ...terminalOptions(),
      // OSC 8 hyperlinks (Rich prints them) follow the same rule as plain URLs.
      linkHandler: { activate: openLink, allowNonHttpProtocols: false },
    });
    const fit = new FitAddon();
    term.loadAddon(fit);
    term.loadAddon(new Unicode11Addon());
    term.unicode.activeVersion = "11";
    term.loadAddon(new WebLinksAddon(openLink));
    term.attachCustomKeyEventHandler(keyFilter(IS_MAC));
    term.open(element);
    fit.fit();
    term.focus();

    const output = new OutputCoalescer((data) => term.write(data));
    const input = new InputQueue(pty.write);
    let running = false;
    let finished = false;

    const onExit = (info: ExitInfo) => {
      output.flush();
      input.clear();
      running = false;
      const { exitNotice: describe, onExit: tell } = latest.current;
      if (once) {
        finished = true;
        setNotice(describe ? describe(info) : exitMessage(info));
      } else {
        setNotice(`${exitMessage(info)} Press Enter to start it again, or ⌘W to close the window.`);
      }
      tell?.(info);
    };

    let starting = false;
    const start = () => {
      if (starting) return;
      starting = true;
      setNotice(null);
      let ended = false;
      const ptyExited = (info: ExitInfo) => {
        ended = true;
        onExit(info);
      };
      // After a reload this takes over the window's running TUI, and Rust makes it repaint;
      // a resize to the same size right after would cut that repaint short.
      const sent = { cols: term.cols, rows: term.rows };
      pty
        .start(sent.cols, sent.rows, (bytes) => output.push(bytes), ptyExited)
        .then(() => {
          // A TUI that died at once has already reported its exit.
          if (!ended) running = true;
          // The grid may have changed while the TUI was starting.
          if (gridChanged(sent, term)) pty.resize(term.cols, term.rows).catch(() => undefined);
        })
        .catch((e) => {
          running = false;
          if (once) {
            finished = true;
            setNotice(String(e));
            latest.current.onExit?.({ success: false, code: null, signal: null });
          } else {
            setNotice(`${String(e)} Press Enter to try again.`);
          }
        })
        .finally(() => {
          starting = false;
        });
    };

    const typed = term.onData((data) => {
      if (running) {
        input.push(textToBytes(data));
      } else if (data === "\r" && !finished) {
        term.reset();
        start();
      }
    });
    const mouse = term.onBinary((data) => {
      if (running) input.push(binaryToBytes(data));
    });
    const resized = term.onResize(({ cols, rows }) => {
      if (running) pty.resize(cols, rows).catch(() => undefined);
    });
    const refit = debounce(() => fit.fit(), RESIZE_DEBOUNCE_MS);
    const observer = new ResizeObserver(() => refit());
    observer.observe(element);
    const refocus = () => term.focus();
    window.addEventListener("focus", refocus);

    start();

    return () => {
      window.removeEventListener("focus", refocus);
      observer.disconnect();
      refit.cancel();
      typed.dispose();
      mouse.dispose();
      resized.dispose();
      output.dispose();
      term.dispose();
    };
    // The terminal is set up once per mount; a new command mounts a new view.
  }, []);

  return (
    <main className={className}>
      <div className="terminal" ref={host} />
      {notice && (
        <div className="notice" role="status">
          {notice}
        </div>
      )}
    </main>
  );
}
