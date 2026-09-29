import { useCallback, useEffect, useState } from "react";
import coin from "../../../docs/brand/tau-coin.svg?raw";
import { api, onSnapshot, type SleepMode, type Snapshot } from "./api";
import { SLEEP_CHOICES, lastLines, loginNote, sleepChoiceEnabled } from "./format";

const LOG_LINES = 30;

export default function App() {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [log, setLog] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  const reloadLog = useCallback(() => {
    api
      .logTail(LOG_LINES)
      .then((lines) => setLog(lastLines(lines, LOG_LINES)))
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    api.snapshot().then(setSnapshot, (e) => setError(String(e)));
    reloadLog();
    const unlisten = onSnapshot((next) => {
      setSnapshot(next);
      reloadLog();
    });
    return () => {
      unlisten.then((stop) => stop());
    };
  }, [reloadLog]);

  const run = async (action: () => Promise<Snapshot>) => {
    setError(null);
    try {
      setSnapshot(await action());
    } catch (e) {
      setError(String(e));
    }
    reloadLog();
  };

  if (!snapshot) {
    return (
      <main className="app">
        <p className="muted">{error ?? "Loading…"}</p>
      </main>
    );
  }

  return (
    <main className="app">
      <header className="top">
        <span className="mark" aria-hidden dangerouslySetInnerHTML={{ __html: coin }} />
        <div>
          <h1>TauBar</h1>
          <p className="muted">tau's menu bar app · v{snapshot.version}</p>
        </div>
      </header>

      {error && <p className="banner error">✗ {error}</p>}

      <SleepSection
        snapshot={snapshot}
        onPick={(mode) => run(() => api.setSleepMode(mode))}
      />

      <section>
        <h2>Launch at login</h2>
        <label className="check">
          <input
            type="checkbox"
            checked={snapshot.login.status === "enabled" || snapshot.login.status === "requires_approval"}
            onChange={(e) => run(() => api.setLaunchAtLogin(e.currentTarget.checked))}
          />
          <span>Open TauBar when I log in</span>
        </label>
        <p className="muted small">{loginNote(snapshot.login.status)}</p>
        {snapshot.login.problem && <p className="banner error">✗ {snapshot.login.problem}</p>}
        {snapshot.login.status === "requires_approval" && (
          <button type="button" onClick={() => api.openLoginItems()}>
            Open Login Items settings
          </button>
        )}
      </section>

      <section>
        <div className="row">
          <h2>TauBar log</h2>
          <button type="button" onClick={() => api.openLog()}>
            Open log
          </button>
        </div>
        <pre className="log">{log.length ? log.join("\n") : "(empty)"}</pre>
      </section>

      <section>
        <div className="row">
          <h2>TauBar</h2>
          <button type="button" onClick={() => api.quit()}>
            Quit TauBar
          </button>
        </div>
        <p className="muted small">
          No τ in the menu bar? On a display with a notch macOS hides menu bar icons that do not
          fit. Open TauBar again (Spotlight or Applications) to get this window, or make room in
          System Settings → Menu Bar. Quitting restores normal sleep.
        </p>
      </section>

      <footer className="muted small">
        <div>Settings: {snapshot.files.settings}</div>
        <div>Log: {snapshot.files.log}</div>
      </footer>
    </main>
  );
}

function SleepSection({
  snapshot,
  onPick,
}: {
  snapshot: Snapshot;
  onPick: (mode: SleepMode) => void;
}) {
  const { sleep } = snapshot;
  return (
    <section>
      <h2>Sleep</h2>
      <p className={sleep.problem ? "status attention" : "status ok"}>
        {sleep.problem ? "◆" : "●"} {snapshot.sleep_summary}
      </p>
      <div className="choices" role="radiogroup" aria-label="Sleep mode">
        {SLEEP_CHOICES.map((choice) => {
          const enabled = sleepChoiceEnabled(choice.mode, sleep);
          const active = sleep.effective === choice.mode;
          return (
            <label
              key={choice.mode}
              className={`choice${active ? " active" : ""}${enabled ? "" : " disabled"}`}
            >
              <input
                type="radio"
                name="sleep"
                checked={active}
                disabled={!enabled}
                onChange={() => onPick(choice.mode)}
              />
              <span>
                <strong>{choice.title}</strong>
                {!enabled && <em> · needs setup</em>}
                <small>{choice.detail}</small>
              </span>
            </label>
          );
        })}
      </div>
      {sleep.problem && <p className="muted small">{sleep.problem}</p>}
      {!sleep.lid_available && (
        <details>
          <summary>Set up the lid-closed mode</summary>
          <p className="small">
            It needs one sudoers rule that allows only <code>pmset -a disablesleep 0|1</code>.
            Run this once in a terminal from the tau checkout (sudo asks for your password):
          </p>
          <pre className="code">apps/taubar/sudoers/install-sudoers.sh</pre>
          <p className="small muted">
            Remove it with <code>apps/taubar/sudoers/uninstall-sudoers.sh</code>. TauBar picks
            the change up within a few seconds.
          </p>
        </details>
      )}
    </section>
  );
}
