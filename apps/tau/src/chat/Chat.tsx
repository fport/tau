import { useEffect, useState } from "react";
import { api, type HomeStatus } from "./api";
import FirstRun from "./FirstRun";
import TerminalView from "./TerminalView";
import "@xterm/xterm/css/xterm.css";
import "./chat.css";

// A chat window shows the terminal once the app knows the checkout (TAU_HOME, or the folder
// chosen on the first run); until then it shows the first-run choice.
export default function Chat() {
  const [status, setStatus] = useState<HomeStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.homeStatus().then(setStatus, (e) => setError(String(e)));
  }, []);

  if (status?.state === "ready") return <TerminalView />;
  if (status?.state === "choose") return <FirstRun status={status} onChange={setStatus} />;
  return (
    <main className="page">
      <p className="muted">{error ?? "Looking for tau…"}</p>
    </main>
  );
}
