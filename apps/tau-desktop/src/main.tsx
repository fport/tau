import ReactDOM from "react-dom/client";
import App from "./App";
import { shouldBlockContextMenu, type TargetLike } from "./terminal";
import "@xterm/xterm/css/xterm.css";
import "./styles.css";

// The webview's context menu offers Reload outside the terminal; keep only the terminal's text
// menu (Copy, Paste).
document.addEventListener("contextmenu", (event) => {
  if (shouldBlockContextMenu(event.target as TargetLike | null)) event.preventDefault();
});

// No React.StrictMode: its double-run of effects in development would attach two terminals to
// the window's one PTY in turn (the second takes the running TUI over from the first).
ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(<App />);
