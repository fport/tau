// The panel under the menu bar icon (src-tauri/src/panel.rs): the menu's switches and status
// in the order of the native menu, which stays on the right click.

import { useEffect, useRef, useState, type ReactNode } from "react";
import coin from "../../../docs/brand/tau-coin.svg?raw";
import { api, onSnapshot, type SleepMode, type Snapshot } from "./api";
import {
  SLEEP_CHOICES,
  hubTone,
  loginChecked,
  sleepChoiceEnabled,
  sleepNote,
} from "./format";
import { AlertIcon, LaptopIcon, MoonIcon, PlugIcon, SendIcon } from "./icons";
import "./panel.css";

const SLEEP_ICONS: Record<SleepMode, () => ReactNode> = {
  normal: MoonIcon,
  keep_awake_on_ac: PlugIcon,
  keep_awake_lid_closed: LaptopIcon,
};

type Note = { tone: "info" | "error"; text: string };

export default function Panel() {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [note, setNote] = useState<Note | null>(null);
  const [busy, setBusy] = useState(false);
  const panel = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api.snapshot().then(setSnapshot, (e) => setNote({ tone: "error", text: String(e) }));
    const unlisten = onSnapshot(setSnapshot);
    return () => {
      unlisten.then((stop) => stop());
    };
  }, []);

  // The window takes the panel's height.
  useEffect(() => {
    const element = panel.current;
    if (!element) return;
    const observer = new ResizeObserver(() => {
      api.panelFit(Math.ceil(element.getBoundingClientRect().height)).catch(() => undefined);
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  // Esc closes the panel, ⌘, opens the settings, ⌘Q quits; a note lasts one opening.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") api.panelHide();
      else if (event.metaKey && event.key === ",") api.openSettings();
      else if (event.metaKey && event.key.toLowerCase() === "q") api.quit();
      else return;
      event.preventDefault();
    };
    const onBlur = () => setNote(null);
    window.addEventListener("keydown", onKey);
    window.addEventListener("blur", onBlur);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("blur", onBlur);
    };
  }, []);

  const run = async (action: () => Promise<Snapshot>) => {
    try {
      setSnapshot(await action());
    } catch (e) {
      setNote({ tone: "error", text: String(e) });
    }
  };

  const toggleHub = async (on: boolean) => {
    setBusy(true);
    setNote(null);
    try {
      const result = await api.setRunHub(on);
      setSnapshot(result.snapshot);
      if (result.message) setNote({ tone: "info", text: result.message });
    } catch (e) {
      setNote({ tone: "error", text: String(e) });
    } finally {
      setBusy(false);
    }
  };

  // Something opens elsewhere: the panel goes, as a menu would.
  const away = (action: () => Promise<void>) => () => {
    api.panelHide();
    action();
  };

  return (
    <div className="panel" ref={panel}>
      {snapshot ? (
        <Body
          snapshot={snapshot}
          busy={busy}
          note={note}
          onHub={toggleHub}
          onSleep={(mode) => run(() => api.setSleepMode(mode))}
          onLogin={(on) => run(() => api.setLaunchAtLogin(on))}
          away={away}
        />
      ) : (
        <p className="row sub">{note?.text ?? "Loading…"}</p>
      )}
    </div>
  );
}

function Body({
  snapshot,
  busy,
  note,
  onHub,
  onSleep,
  onLogin,
  away,
}: {
  snapshot: Snapshot;
  busy: boolean;
  note: Note | null;
  onHub: (on: boolean) => void;
  onSleep: (mode: SleepMode) => void;
  onLogin: (on: boolean) => void;
  away: (action: () => Promise<void>) => () => void;
}) {
  const { hub, sleep, login } = snapshot;
  const crashed = hub.panel.crash !== "none";
  const sleepExplained = sleepNote(sleep);
  const loginOn = loginChecked(login.status);

  return (
    <>
      <header className="head">
        <span>Hub</span>
        <Switch
          label="Run the hub"
          checked={hub.switch_on}
          disabled={busy || hub.state === "not_configured"}
          onChange={onHub}
        />
      </header>

      <div className="group">
        <div className="row">
          <span
            className={`coin ${hubTone(hub.state)}`}
            aria-hidden
            dangerouslySetInnerHTML={{ __html: coin }}
          />
          <Text title={hub.panel.title} detail={hub.panel.detail} />
        </div>
        {hub.problem ? (
          <InfoRow icon={<AlertIcon />} tone="attention" title="Problem" detail={hub.problem} />
        ) : (
          <InfoRow icon={<SendIcon />} title="Telegram" detail={hub.panel.telegram} />
        )}
        <InfoRow
          icon={<AlertIcon />}
          tone={crashed ? "attention" : undefined}
          title="Last crash"
          detail={hub.panel.crash}
        />
        {hub.state === "not_configured" && (
          <button type="button" className="item" onClick={() => api.openSettings()}>
            Set up the hub…
          </button>
        )}
      </div>
      {note && <p className={`note ${note.tone}`}>{note.text}</p>}

      <hr className="rule" />

      <div className="section">Sleep</div>
      {sleepExplained && <p className="note">{sleepExplained}</p>}
      <div className="group" role="radiogroup" aria-label="Sleep mode">
        {SLEEP_CHOICES.map((choice) => {
          const enabled = sleepChoiceEnabled(choice.mode, sleep);
          const active = sleep.effective === choice.mode;
          const SleepIcon = SLEEP_ICONS[choice.mode];
          return (
            <div className="choice" key={choice.mode}>
              <button
                type="button"
                role="radio"
                className="item"
                aria-checked={active}
                disabled={!enabled}
                title={choice.detail}
                onClick={() => !active && onSleep(choice.mode)}
              >
                <span className={`icon${active ? " selected" : ""}`}>
                  <SleepIcon />
                </span>
                <span className="label">{choice.title}</span>
              </button>
              {!enabled && (
                <button type="button" className="link" onClick={() => api.openSettings()}>
                  Set up…
                </button>
              )}
            </div>
          );
        })}
      </div>

      <hr className="rule" />

      <div className="group">
        <button
          type="button"
          role="switch"
          className="item"
          aria-checked={loginOn}
          onClick={() => onLogin(!loginOn)}
        >
          <span className="label">Launch at login</span>
          <span className="switch small" aria-hidden>
            <span className="knob" />
          </span>
        </button>
        {login.status === "requires_approval" && (
          <button type="button" className="item sub" onClick={away(api.openLoginItems)}>
            Allow it in System Settings…
          </button>
        )}
        <button type="button" className="item" onClick={away(api.openHubLog)}>
          Open Hub Log
        </button>
        <button type="button" className="item" onClick={away(api.openLog)}>
          Open TauBar Log
        </button>
        <button type="button" className="item" onClick={() => api.openSettings()}>
          <span className="label">Settings…</span>
          <kbd>⌘,</kbd>
        </button>
      </div>

      <hr className="rule" />

      <div className="group">
        <button type="button" className="item" onClick={() => api.quit()}>
          <span className="label">Quit TauBar</span>
          <kbd>⌘Q</kbd>
        </button>
      </div>
    </>
  );
}

function Switch({
  label,
  checked,
  disabled,
  onChange,
}: {
  label: string;
  checked: boolean;
  disabled?: boolean;
  onChange: (on: boolean) => void;
}) {
  return (
    <button
      type="button"
      role="switch"
      className="switch"
      aria-label={label}
      aria-checked={checked}
      disabled={disabled}
      onClick={() => onChange(!checked)}
    >
      <span className="knob" />
    </button>
  );
}

function InfoRow({
  icon,
  tone,
  title,
  detail,
}: {
  icon: ReactNode;
  tone?: "attention";
  title: string;
  detail: string;
}) {
  return (
    <div className="row">
      <span className={`icon${tone ? ` ${tone}` : ""}`}>{icon}</span>
      <Text title={title} detail={detail} />
    </div>
  );
}

function Text({ title, detail }: { title: string; detail: string }) {
  return (
    <span className="text">
      <span className="title">{title}</span>
      {detail && (
        <span className="sub" title={detail}>
          {detail}
        </span>
      )}
    </span>
  );
}
