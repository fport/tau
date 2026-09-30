import React from "react";
import ReactDOM from "react-dom/client";
import { isTauri } from "@tauri-apps/api/core";

// One page, three kinds of window: the panel under the menu bar icon (`index.html#panel`), the
// chat windows (`index.html#chat`, one `tau tui` each) and the settings window. Each view module
// brings its own stylesheet, so a window loads only its own (xterm.js only in chat windows).

async function startChat() {
  const [{ default: Chat }, { shouldBlockContextMenu }] = await Promise.all([
    import("./chat/Chat"),
    import("./chat/terminal"),
  ]);
  // The webview's context menu offers Reload outside the terminal; keep only the terminal's
  // text menu (Copy, Paste).
  document.addEventListener("contextmenu", (event) => {
    if (shouldBlockContextMenu(event.target as Parameters<typeof shouldBlockContextMenu>[0])) {
      event.preventDefault();
    }
  });
  // No React.StrictMode: its double-run of effects in development would attach two terminals to
  // the window's one PTY in turn (the second takes the running TUI over from the first).
  ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(<Chat />);
}

async function view(panel: boolean) {
  if (panel) return (await import("./Panel")).default;
  return (await import("./App")).default;
}

async function start() {
  if (window.location.hash === "#chat") return startChat();
  if (import.meta.env.DEV && !isTauri()) await import("./devmock");
  const panel = window.location.hash === "#panel";
  // The panel sits on macOS's popover material; in a browser it draws its own background.
  document.documentElement.classList.toggle("material", panel && isTauri());
  const View = await view(panel);
  ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
    <React.StrictMode>
      <View />
    </React.StrictMode>,
  );
}

start();
