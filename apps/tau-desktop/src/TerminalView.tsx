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

// One terminal per window, attached to the window's own PTY running `tau tui`.
export default function TerminalView() {
  const host = useRef<HTMLDivElement>(null);
  const [notice, setNotice] = useState<string | null>(null);

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
    const input = new InputQueue(api.ptyWrite);
    let running = false;

    const onExit = (info: ExitInfo) => {
      output.flush();
      input.clear();
      running = false;
      setNotice(`${exitMessage(info)} Press Enter to start it again, or ⌘W to close the window.`);
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
      api
        .ptyStart(term.cols, term.rows, (bytes) => output.push(bytes), ptyExited)
        .then(() => {
          // A TUI that died at once has already reported its exit.
          if (!ended) running = true;
          // The grid may have changed while the TUI was starting.
          api.ptyResize(term.cols, term.rows).catch(() => undefined);
        })
        .catch((e) => {
          running = false;
          setNotice(`${String(e)} Press Enter to try again.`);
        })
        .finally(() => {
          starting = false;
        });
    };

    const typed = term.onData((data) => {
      if (running) {
        input.push(textToBytes(data));
      } else if (data === "\r") {
        term.reset();
        start();
      }
    });
    const mouse = term.onBinary((data) => {
      if (running) input.push(binaryToBytes(data));
    });
    const resized = term.onResize(({ cols, rows }) => {
      if (running) api.ptyResize(cols, rows).catch(() => undefined);
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
  }, []);

  return (
    <main className="terminal-page">
      <div className="terminal" ref={host} />
      {notice && (
        <div className="notice" role="status">
          {notice}
        </div>
      )}
    </main>
  );
}
