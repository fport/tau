import { useCallback, useEffect, useState } from "react";
import { open } from "@tauri-apps/plugin-dialog";
import coin from "../../../docs/brand/tau-coin.svg?raw";
import { api, onSnapshot, type SleepMode, type Snapshot } from "./api";
import {
  SLEEP_CHOICES,
  checkoutSettings,
  formFromSettings,
  guardTone,
  hubTone,
  lastLines,
  loginChecked,
  loginNote,
  settingsFromForm,
  sleepChoiceEnabled,
  type HubForm,
} from "./format";
import "./styles.css";

const LOG_LINES = 30;

// The app menu has no Select All (⌘A must reach xterm.js in a chat window), so the fields here
// handle ⌘A themselves.
function selectAllInFields(event: KeyboardEvent) {
  if (!event.metaKey || event.key.toLowerCase() !== "a") return;
  const target = event.target;
  if (target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement) {
    event.preventDefault();
    target.select();
  }
}

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
    window.addEventListener("keydown", selectAllInFields);
    return () => window.removeEventListener("keydown", selectAllInFields);
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
          <h1>tau</h1>
          <p className="muted">The menu bar, the hub and chat windows · v{snapshot.version}</p>
        </div>
      </header>

      {error && <p className="banner error">✗ {error}</p>}

      <HubSection snapshot={snapshot} onSnapshot={setSnapshot} />

      <section>
        <div className="row">
          <h2>Chat</h2>
          <button type="button" onClick={() => api.newChat()}>
            New Chat Window
          </button>
        </div>
        <p className="muted small">
          A chat window runs <code>tau tui</code> from your tau checkout, as in Terminal. ⌘N opens
          one from anywhere in tau; closing it quits its TUI.
        </p>
      </section>

      <SleepSection
        snapshot={snapshot}
        onPick={(mode) => run(() => api.setSleepMode(mode))}
      />

      <section>
        <h2>Launch at login</h2>
        <label className="check">
          <input
            type="checkbox"
            checked={loginChecked(snapshot.login.status)}
            onChange={(e) => run(() => api.setLaunchAtLogin(e.currentTarget.checked))}
          />
          <span>Open tau when I log in</span>
        </label>
        <p className="muted small">{loginNote(snapshot.login.status)}</p>
        {snapshot.login.problem && <p className="banner error">✗ {snapshot.login.problem}</p>}
        {snapshot.login.status === "requires_approval" && (
          <button type="button" onClick={() => api.openLoginItems()}>
            Open Login Items settings
          </button>
        )}
      </section>

      <UpdatesSection snapshot={snapshot} onSnapshot={setSnapshot} />

      <section>
        <div className="row">
          <h2>App log</h2>
          <button type="button" onClick={() => api.openLog()}>
            Open log
          </button>
        </div>
        <pre className="log">{log.length ? log.join("\n") : "(empty)"}</pre>
      </section>

      <section>
        <div className="row">
          <h2>Quit</h2>
          <button type="button" onClick={() => api.quit()}>
            Quit tau
          </button>
        </div>
        <p className="muted small">
          No τ in the menu bar? On a display with a notch macOS hides menu bar icons that do not
          fit. Open tau again (Spotlight or Applications) to get a window, or make room in System
          Settings → Menu Bar. Quitting closes the chat windows, restores normal sleep and stops
          a hub tau started.
        </p>
      </section>

      <footer className="muted small">
        <div>Settings: {snapshot.files.settings}</div>
        <div>Log: {snapshot.files.log}</div>
      </footer>
    </main>
  );
}

function HubSection({
  snapshot,
  onSnapshot,
}: {
  snapshot: Snapshot;
  onSnapshot: (next: Snapshot) => void;
}) {
  const { hub } = snapshot;
  const [form, setForm] = useState<HubForm>(() => formFromSettings(hub.settings));
  const [dirty, setDirty] = useState(false);
  const [note, setNote] = useState<{ tone: "ok" | "error" | "info"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  // Follow the saved settings until the user starts editing.
  useEffect(() => {
    if (!dirty) setForm(formFromSettings(hub.settings));
  }, [hub.settings, dirty]);

  const edit = (patch: Partial<HubForm>) => {
    setForm((current) => ({ ...current, ...patch }));
    setDirty(true);
  };

  const toggle = async (on: boolean) => {
    setBusy(true);
    setNote(null);
    try {
      const result = await api.setRunHub(on);
      onSnapshot(result.snapshot);
      if (result.message) setNote({ tone: "info", text: result.message });
    } catch (e) {
      setNote({ tone: "error", text: String(e) });
    } finally {
      setBusy(false);
    }
  };

  const lockNow = async () => {
    setBusy(true);
    setNote(null);
    try {
      onSnapshot(await api.lockGuard());
      setNote({ tone: "ok", text: "tau is locked." });
    } catch (e) {
      setNote({ tone: "error", text: `tau may not be locked: ${String(e)}` });
    } finally {
      setBusy(false);
    }
  };

  const pickCheckout = async () => {
    const dir = await open({ directory: true, multiple: false, title: "The tau checkout" });
    if (typeof dir === "string") edit(checkoutSettings(dir));
  };

  const save = async () => {
    const { settings, errors } = settingsFromForm(form);
    if (errors.length) {
      setNote({ tone: "error", text: errors.join("\n") });
      return;
    }
    setBusy(true);
    try {
      onSnapshot(await api.saveHubSettings(settings));
      setDirty(false);
      setNote({ tone: "ok", text: "Saved. They apply the next time tau starts the hub." });
    } catch (e) {
      setDirty(false);
      setNote({ tone: "error", text: `Saved, but: ${String(e)}` });
    } finally {
      setBusy(false);
    }
  };

  const pausedByCleanExit = hub.run_at_start && !hub.switch_on && hub.state === "stopped";

  return (
    <section>
      <div className="row">
        <h2>Hub</h2>
        <button type="button" onClick={() => api.openHubLog()}>
          Open hub log
        </button>
      </div>
      <p className={`status ${hubTone(hub.state)}`}>
        {hub.state === "up" || hub.state === "elsewhere" ? "●" : "○"} {hub.lines[0]}
      </p>
      <p className="muted small">{hub.lines[1]}</p>
      <p className="muted small">{hub.lines[2]}</p>
      {hub.guard_menu.line && (
        <GuardLine snapshot={snapshot} busy={busy} onLock={lockNow} />
      )}
      <label className="check">
        <input
          type="checkbox"
          checked={hub.switch_on}
          disabled={busy || hub.state === "not_configured"}
          onChange={(e) => toggle(e.currentTarget.checked)}
        />
        <span>Run the hub</span>
      </label>
      <p className="muted small">
        tau starts the hub, restarts it within seconds after a crash or a kill, leaves it stopped
        after <code>tau hub stop</code>, and stops it when tau quits. It never starts a second hub
        next to one that is already running.
        {pausedByCleanExit &&
          " The hub exited cleanly, so the switch is off for now; tau starts it again at its next start."}
      </p>
      {note && <p className={`banner ${note.tone === "error" ? "error" : ""}`}>{note.text}</p>}

      <details open={hub.state === "not_configured"}>
        <summary>How tau starts the hub</summary>
        <div className="buttons">
          <button type="button" onClick={pickCheckout}>
            Use a tau checkout…
          </button>
        </div>
        <label className="field">
          <span>Python with tau-core (a checkout's .venv/bin/python)</span>
          <input
            type="text"
            value={form.python}
            placeholder="/path/to/tau/.venv/bin/python"
            onChange={(e) => edit({ python: e.currentTarget.value })}
          />
        </label>
        <label className="field">
          <span>TAU_HOME (the directory with tau.toml; also the working directory)</span>
          <input
            type="text"
            value={form.tau_home}
            placeholder="/path/to/tau"
            onChange={(e) => edit({ tau_home: e.currentTarget.value })}
          />
        </label>
        <label className="field">
          <span>TAU_DATA_DIR (optional; empty: what tau.toml and .env say)</span>
          <input
            type="text"
            value={form.data_dir}
            placeholder="~/.local/share/tau"
            onChange={(e) => edit({ data_dir: e.currentTarget.value })}
          />
        </label>
        <label className="field">
          <span>Control port, TAU_HUB_PORT (optional; empty: [hub] control_port)</span>
          <input
            type="text"
            inputMode="numeric"
            value={form.port}
            placeholder="7877"
            onChange={(e) => edit({ port: e.currentTarget.value })}
          />
        </label>
        <label className="field">
          <span>PATH for the hub (optional)</span>
          <input
            type="text"
            value={form.path}
            placeholder="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
            onChange={(e) => edit({ path: e.currentTarget.value })}
          />
        </label>
        <label className="field">
          <span>More environment, one KEY=value per line (wins over .env)</span>
          <textarea
            rows={3}
            value={form.env}
            onChange={(e) => edit({ env: e.currentTarget.value })}
          />
        </label>
        <div className="buttons">
          <button type="button" className="primary" disabled={busy || !dirty} onClick={save}>
            Save
          </button>
          {dirty && (
            <button
              type="button"
              onClick={() => {
                setForm(formFromSettings(hub.settings));
                setDirty(false);
              }}
            >
              Discard
            </button>
          )}
        </div>
        <dl className="facts">
          <dt>Runs</dt>
          <dd>
            <code>{hub.command ?? "(not set up)"}</code>
          </dd>
          <dt>Control API</dt>
          <dd>{hub.control_url ?? "–"}</dd>
          <dt>Hub log</dt>
          <dd>{hub.hub_log ?? "–"}</dd>
        </dl>
      </details>
    </section>
  );
}

function GuardLine({
  snapshot,
  busy,
  onLock,
}: {
  snapshot: Snapshot;
  busy: boolean;
  onLock: () => void;
}) {
  const { guard, guard_menu } = snapshot.hub;
  const { tone, mark } = guardTone(guard?.state ?? "unknown");
  return (
    <>
      <p className={`status ${tone}`}>
        {mark} {guard_menu.line}
      </p>
      {guard_menu.grant_camera && (
        <p className="muted small">
          The hub tau runs cannot use the camera. Allow tau under System Settings → Privacy &amp;
          Security → Camera.
        </p>
      )}
      <div className="buttons">
        {guard_menu.lock_now && (
          <button type="button" disabled={busy} onClick={onLock}>
            Lock now
          </button>
        )}
        {guard_menu.grant_camera && (
          <button type="button" onClick={() => api.openCameraSettings()}>
            Grant camera access…
          </button>
        )}
      </div>
    </>
  );
}

function UpdatesSection({
  snapshot,
  onSnapshot,
}: {
  snapshot: Snapshot;
  onSnapshot: (next: Snapshot) => void;
}) {
  const { updates } = snapshot;
  return (
    <section>
      <div className="row">
        <h2>Updates</h2>
        <button type="button" onClick={() => api.checkUpdates()}>
          Check for Updates…
        </button>
      </div>
      <label className="check">
        <input
          type="checkbox"
          checked={updates.check}
          onChange={(e) => {
            api.setCheckUpdates(e.currentTarget.checked).then(onSnapshot, () => undefined);
          }}
        />
        <span>Look for an update once a day</span>
      </label>
      <p className="muted small">
        {updates.release_build
          ? "tau asks GitHub for its latest release a minute after it starts and then once a day, and offers a newer one; nothing is installed without your click."
          : "This build does not look by itself: release builds from GitHub do. Check for Updates… still asks."}
      </p>
    </section>
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
          <pre className="code">apps/tau/sudoers/install-sudoers.sh</pre>
          <p className="small muted">
            Remove it with <code>apps/tau/sudoers/uninstall-sudoers.sh</code>. tau picks the
            change up within a few seconds.
          </p>
        </details>
      )}
    </section>
  );
}
