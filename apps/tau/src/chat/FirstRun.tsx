import { useState } from "react";
import mark from "../../../../docs/brand/tau-mark.svg";
import { api, type HomeStatus } from "./api";

type Choose = Extract<HomeStatus, { state: "choose" }>;

// First run: which tau checkout the chat windows run. There is deliberately no text field: the
// folder comes from the hub's settings (one click) or the native picker, and the app checks it
// by running its own `.venv/bin/python -m tau_core version` before using it.
export default function FirstRun({
  status,
  onChange,
}: {
  status: Choose;
  onChange: (next: HomeStatus) => void;
}) {
  const [busy, setBusy] = useState(false);

  const choose = async (useHint: boolean) => {
    setBusy(true);
    try {
      onChange(await api.chooseHome(useHint));
    } catch (e) {
      onChange({ ...status, problem: String(e) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="page first-run">
      <img className="mark" src={mark} alt="" />
      <h1>tau</h1>
      <p>
        A chat window runs <code>tau tui</code> from your tau checkout: the folder with{" "}
        <code>tau.toml</code> and the <code>.venv</code> that <code>uv sync</code> created
        (<code>TAU_HOME</code>).
      </p>

      {status.hint && (
        <section className="choice">
          <p className="muted">tau runs the hub from</p>
          <p className="path">{status.hint}</p>
          <button type="button" className="primary" disabled={busy} onClick={() => choose(true)}>
            Use This Folder
          </button>
        </section>
      )}

      <button
        type="button"
        className={status.hint ? "" : "primary"}
        disabled={busy}
        onClick={() => choose(false)}
      >
        {status.hint ? "Choose Another Folder…" : "Choose Folder…"}
      </button>

      {busy && (
        <p className="muted">
          Checking the folder with <code>python -m tau_core version</code>…
        </p>
      )}
      {status.problem && !busy && (
        <p className="problem" role="alert">
          {status.problem}
        </p>
      )}

      <p className="note">
        tau remembers the folder for its chat windows. Set <code>TAU_HOME</code> before opening
        the app to use another one.
      </p>

      <p className="note">
        No tau yet, or installed with <code>uv tool install</code>?{" "}
        <button type="button" disabled={busy} onClick={() => api.openWizard()}>
          Set up tau…
        </button>{" "}
        finds or installs it and sets these windows up.
      </p>
    </main>
  );
}
