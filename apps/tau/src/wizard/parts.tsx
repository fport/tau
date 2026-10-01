// Small pieces the wizard's steps share: the footer, the output log, copy and link buttons,
// and the hook that runs a job and folds its events into a state.

import { useCallback, useRef, useState, type ReactNode } from "react";
import { api, type Ended, type JobEvent } from "./api";
import type { LogLine } from "./events";
import type { T } from "./strings";

export function Footer({
  t,
  busy,
  onBack,
  onSkip,
  children,
}: {
  t: T;
  busy: boolean;
  onBack?: () => void;
  onSkip?: () => void;
  children?: ReactNode;
}) {
  return (
    <footer className="wizard-footer">
      <div className="buttons">
        {onBack && (
          <button type="button" disabled={busy} onClick={onBack}>
            {t("nav.back")}
          </button>
        )}
      </div>
      <div className="buttons">
        {busy && (
          <button type="button" onClick={() => api.cancel().catch(() => undefined)}>
            {t("nav.cancel")}
          </button>
        )}
        {onSkip && (
          <button type="button" disabled={busy} onClick={onSkip}>
            {t("nav.skip")}
          </button>
        )}
        {children}
      </div>
    </footer>
  );
}

/** A job's output lines, folded away unless something failed. */
export function Output({ t, lines, open }: { t: T; lines: LogLine[]; open?: boolean }) {
  if (!lines.length) return null;
  return (
    <details className="output" open={open}>
      <summary>
        {t("common.output")} ({lines.length})
      </summary>
      <pre className="log">
        {lines.map((l, i) => (
          <span key={i} className={l.stderr ? "stderr" : undefined}>
            {l.line}
            {"\n"}
          </span>
        ))}
      </pre>
    </details>
  );
}

export function CopyButton({ t, text }: { t: T; text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      className="small-button"
      onClick={() => {
        navigator.clipboard
          .writeText(text)
          .then(() => {
            setCopied(true);
            window.setTimeout(() => setCopied(false), 1500);
          })
          .catch(() => undefined);
      }}
    >
      {copied ? t("common.copied") : t("common.copy")}
    </button>
  );
}

/** A command to copy, never to run. */
export function CommandLine({ t, command }: { t: T; command: string }) {
  return (
    <div className="command-line">
      <pre className="code">{command}</pre>
      <CopyButton t={t} text={command} />
    </div>
  );
}

/** Opens an http(s) link in the default browser (through Rust). */
export function LinkButton({
  url,
  children,
  primary,
}: {
  url: string;
  children: ReactNode;
  primary?: boolean;
}) {
  return (
    <button
      type="button"
      className={primary ? "primary" : undefined}
      onClick={() => api.openLink(url).catch(() => undefined)}
    >
      {children} ↗
    </button>
  );
}

export function Problem({ children }: { children: ReactNode }) {
  if (!children) return null;
  return (
    <p className="banner error" role="alert">
      {children}
    </p>
  );
}

/** The mark of a check line: ok, fail, warn, info. */
export function checkMark(status: string): string {
  switch (status) {
    case "ok":
      return "✓";
    case "fail":
      return "✗";
    case "warn":
      return "!";
    default:
      return "·";
  }
}

/** The sentence for a job that ended without its own error event. */
export function endedProblem(t: T, ended: Ended | null): string | null {
  if (!ended) return null;
  if (ended.cancelled) return t("common.cancelled");
  if (ended.timed_out) return t("common.timed_out");
  if (ended.code !== 0) return t("common.exit", { code: ended.code ?? ended.signal ?? "?" });
  return null;
}

export interface JobResult<S> {
  state: S;
  ended: Ended | null;
  failure: string | null;
}

/**
 * Run one job at a time and fold its events into a state with `reduce`. `setBusy` keeps the
 * rest of the wizard still while it runs.
 */
export function useJob<S>(
  reduce: (state: S, event: JobEvent) => S,
  empty: S,
  setBusy: (busy: boolean) => void,
) {
  const [state, setState] = useState<S>(empty);
  const [running, setRunning] = useState(false);
  const [ended, setEnded] = useState<Ended | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const reduceRef = useRef(reduce);
  reduceRef.current = reduce;

  const start = useCallback(
    async (
      go: (onEvent: (event: JobEvent) => void) => Promise<Ended>,
      /** Start from what the last job left, through this (a feature's next run keeps the
       * steps shown so far); without it, from `empty`. */
      carry?: (last: S) => S,
    ): Promise<JobResult<S>> => {
      let current = carry ? carry(state) : empty;
      setState(current);
      setEnded(null);
      setFailure(null);
      setRunning(true);
      setBusy(true);
      try {
        const end = await go((event) => {
          current = reduceRef.current(current, event);
          setState(current);
        });
        setEnded(end);
        return { state: current, ended: end, failure: null };
      } catch (e) {
        const message = String(e);
        setFailure(message);
        return { state: current, ended: null, failure: message };
      } finally {
        setRunning(false);
        setBusy(false);
      }
    },
    // `state` only matters for `carry`; the latest is read through the closure on each call.
    [state, empty, setBusy],
  );

  const reset = useCallback(() => {
    setState(empty);
    setEnded(null);
    setFailure(null);
  }, [empty]);

  return { state, running, ended, failure, start, reset };
}
