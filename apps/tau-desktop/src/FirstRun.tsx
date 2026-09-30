import { useState } from "react";
import mark from "../../../docs/brand/tau-mark.svg";
import { api, type HomeStatus } from "./api";

type Choose = Extract<HomeStatus, { state: "choose" }>;

// First run: which tau checkout to run. There is deliberately no text field: the folder comes
// from TauBar's settings (one click) or the native picker, and tau Desktop checks it by running
// its own `.venv/bin/python -m tau_core version` before using it.
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
      <h1>tau Desktop</h1>
      <p>
        tau Desktop runs <code>tau tui</code> from your tau checkout: the folder with{" "}
        <code>tau.toml</code> and the <code>.venv</code> that <code>uv sync</code> created
        (<code>TAU_HOME</code>).
      </p>

      {status.hint && (
        <section className="choice">
          <p className="muted">TauBar runs the hub from</p>
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
        tau Desktop remembers the folder. Set <code>TAU_HOME</code> before opening the app to use
        another one.
      </p>
    </main>
  );
}
