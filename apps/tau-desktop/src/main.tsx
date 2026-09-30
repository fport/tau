import ReactDOM from "react-dom/client";
import App from "./App";
import "@xterm/xterm/css/xterm.css";
import "./styles.css";

// No React.StrictMode: its double-run of effects in development would start a second PTY for
// the window (the Rust side refuses it).
ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(<App />);
